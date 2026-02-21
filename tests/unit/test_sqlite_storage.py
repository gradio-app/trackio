import gc
import multiprocessing
import os
import platform
import random
import sqlite3
import tempfile
import time
from pathlib import Path

import orjson
import pytest

import trackio.sqlite_storage
import trackio.utils
from trackio.sqlite_storage import SQLiteStorage


def test_init_creates_metrics_table(temp_dir):
    db_path = SQLiteStorage.init_db("proj1")
    assert os.path.exists(db_path)
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM metrics")


def test_log_and_get_metrics(temp_dir):
    metrics = {"acc": 0.9}
    SQLiteStorage.log(project="proj1", run="run1", metrics=metrics)
    results = SQLiteStorage.get_logs(project="proj1", run="run1")
    assert len(results) == 1
    assert results[0]["acc"] == 0.9
    assert results[0]["step"] == 0
    assert "timestamp" in results[0]


def test_get_projects_and_runs(temp_dir):
    SQLiteStorage.log(project="proj1", run="run1", metrics={"a": 1})
    SQLiteStorage.log(project="proj2", run="run2", metrics={"b": 2})
    projects = set(SQLiteStorage.get_projects())
    assert {"proj1", "proj2"}.issubset(projects)
    runs = set(SQLiteStorage.get_runs("proj1"))
    assert "run1" in runs


def test_delete_run(temp_dir):
    project = "test_project"
    run_name = "test_run"

    config = {"param1": "value1", "_Created": "2023-01-01T00:00:00"}
    metrics = [{"accuracy": 0.95, "loss": 0.1}]
    SQLiteStorage.bulk_log(project, run_name, metrics, config=config)

    assert SQLiteStorage.get_run_config(project, run_name) is not None
    assert len(SQLiteStorage.get_logs(project, run_name)) > 0

    SQLiteStorage.delete_run(project, run_name)
    assert SQLiteStorage.get_run_config(project, run_name) is None
    assert len(SQLiteStorage.get_logs(project, run_name)) == 0


def test_import_export(temp_dir):
    db_path_1 = SQLiteStorage.init_db("proj1")
    db_path_2 = SQLiteStorage.init_db("proj2")

    SQLiteStorage.log(project="proj1", run="run1", metrics={"a": 1})
    SQLiteStorage.log(project="proj2", run="run2", metrics={"b": 2})
    SQLiteStorage._dataset_import_attempted = True
    SQLiteStorage.export_to_parquet()

    metrics_before = {}
    for proj in SQLiteStorage.get_projects():
        if proj not in metrics_before:
            metrics_before[proj] = {}
        for run in SQLiteStorage.get_runs(proj):
            metrics_before[proj][run] = SQLiteStorage.get_logs(proj, run)

    ## there might be open connections from previous test, hence closing them
    gc.collect()
    [conn.close() for conn in gc.get_objects() if isinstance(conn, sqlite3.Connection)]
    # clear existing SQLite data
    os.unlink(db_path_1)
    os.unlink(db_path_2)

    # import from parquet, compare copies
    SQLiteStorage.import_from_parquet()
    metrics_after = {}
    for proj in SQLiteStorage.get_projects():
        if proj not in metrics_after:
            metrics_after[proj] = {}
        for run in SQLiteStorage.get_runs(proj):
            metrics_after[proj][run] = SQLiteStorage.get_logs(proj, run)

    assert metrics_before == metrics_after


def _worker_using_sqlite_storage(
    project, worker_id, duration_seconds=2, sync_start_time=None, temp_dir=None
):
    """
    Worker that uses SQLiteStorage methods for database access.
    This will be protected by ProcessLock when available.
    """
    if temp_dir:
        os.environ["TRACKIO_DIR"] = temp_dir
        from pathlib import Path

        import trackio.sqlite_storage
        import trackio.utils

        trackio.utils.TRACKIO_DIR = Path(temp_dir)
        trackio.sqlite_storage.TRACKIO_DIR = Path(temp_dir)

    def aggressive_get_connection(db_path):
        conn = sqlite3.connect(str(db_path), timeout=0.01)
        conn.row_factory = sqlite3.Row
        return conn

    SQLiteStorage._get_connection = aggressive_get_connection

    if sync_start_time:
        while time.time() < sync_start_time:
            time.sleep(0.001)

    run_name = f"worker_{worker_id}"
    db_locked_errors = 0

    start_time = time.time()
    while time.time() - start_time < duration_seconds:
        try:
            for _ in range(4):
                batch_size = random.randint(3, 8)
                metrics_list = [
                    {"batch": True, "worker": worker_id, "item": i}
                    for i in range(batch_size)
                ]
                SQLiteStorage.bulk_log(project, run_name, metrics_list)

        except sqlite3.OperationalError as e:
            error_msg = str(e).lower()
            if "database is locked" in error_msg or "database is busy" in error_msg:
                db_locked_errors += 1
                time.sleep(random.uniform(0.0001, 0.001))
        except Exception:
            pass

    return db_locked_errors


@pytest.mark.skipif(
    platform.system() == "Windows",
    reason="Windows multiprocessing has different behavior",
)
def test_concurrent_database_access_without_errors():
    """
    Test that concurrent database access doesn't produce 'database is locked' errors.
    """
    with tempfile.TemporaryDirectory() as temp_dir:
        os.environ["TRACKIO_DIR"] = str(temp_dir)
        trackio.utils.TRACKIO_DIR = Path(temp_dir)
        trackio.sqlite_storage.TRACKIO_DIR = Path(temp_dir)

        project = "concurrent_test"

        num_processes = 8
        duration = 2

        sync_start_time = time.time() + 0.5

        with multiprocessing.Pool(processes=num_processes) as pool:
            results = [
                pool.apply_async(
                    _worker_using_sqlite_storage,
                    (project, i, duration, sync_start_time, temp_dir),
                )
                for i in range(num_processes)
            ]

            total_db_locked_errors = 0

            for result in results:
                db_locked = result.get(timeout=duration + 10)
                total_db_locked_errors += db_locked

        print(f"Database locked errors: {total_db_locked_errors}")

        assert total_db_locked_errors == 0, (
            f"Got {total_db_locked_errors} 'database is locked' errors - ProcessLock fix failed"
        )

        runs = SQLiteStorage.get_runs(project)
        assert len(runs) > 0, "Should have created some runs"
        total_logs = 0
        for run in runs:
            logs = SQLiteStorage.get_logs(project, run)
            total_logs += len(logs)

        assert total_logs > 0, "Should have created some log entries"


def test_config_storage_in_database(temp_dir):
    config = {
        "epochs": 10,
        "_Username": "testuser",
        "_Created": "2024-01-01T00:00:00+00:00",
    }

    SQLiteStorage.bulk_log(
        project="test_project",
        run="test_run",
        metrics_list=[{"loss": 0.5}],
        config=config,
    )

    stored_config = SQLiteStorage.get_run_config("test_project", "test_run")
    assert stored_config["epochs"] == 10
    assert stored_config["_Username"] == "testuser"
    assert stored_config["_Created"] == "2024-01-01T00:00:00+00:00"


def test_old_database_without_configs_table(temp_dir):
    # To make sure that we can continue to work with projects created with older versions of Trackio.
    db_path = SQLiteStorage.get_project_db_path("test")
    db_path.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(db_path) as conn:
        conn.execute("""
            CREATE TABLE metrics (
                id INTEGER PRIMARY KEY,
                timestamp TEXT,
                run_name TEXT,
                step INTEGER,
                metrics TEXT
            )
        """)
        conn.execute(
            "INSERT INTO metrics (timestamp, run_name, step, metrics) VALUES (?, ?, ?, ?)",
            ("2024-01-01", "test_run", 0, orjson.dumps({"loss": 0.5})),
        )

    config = SQLiteStorage.get_run_config("test", "test_run")
    assert config is None

    all_configs = SQLiteStorage.get_all_run_configs("test")
    assert all_configs == {}


def test_get_runs_returns_chronological_order(temp_dir):
    db_path = SQLiteStorage.get_project_db_path("proj")
    db_path.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(db_path) as conn:
        conn.execute("""
            CREATE TABLE metrics (
                id INTEGER PRIMARY KEY,
                timestamp TEXT,
                run_name TEXT,
                step INTEGER,
                metrics TEXT
            )
        """)
        conn.execute(
            "INSERT INTO metrics (timestamp, run_name, step, metrics) VALUES (?, ?, ?, ?)",
            ("2024-01-01", "run-z", 0, orjson.dumps({"loss": 0.5})),
        )
        conn.execute(
            "INSERT INTO metrics (timestamp, run_name, step, metrics) VALUES (?, ?, ?, ?)",
            ("2024-01-02", "run-a", 0, orjson.dumps({"loss": 0.5})),
        )
        conn.execute(
            "INSERT INTO metrics (timestamp, run_name, step, metrics) VALUES (?, ?, ?, ?)",
            ("2024-01-03", "run-m", 0, orjson.dumps({"loss": 0.5})),
        )

    runs = SQLiteStorage.get_runs("proj")
    assert runs == ["run-z", "run-a", "run-m"]


def test_rename_run(temp_dir):
    project = "test_project"
    old_name = "old_run"
    new_name = "new_run"

    config = {"param1": "value1", "_Created": "2023-01-01T00:00:00"}
    metrics = [{"accuracy": 0.95, "loss": 0.1}]
    SQLiteStorage.bulk_log(project, old_name, metrics, config=config)

    assert SQLiteStorage.get_run_config(project, old_name) is not None
    assert len(SQLiteStorage.get_logs(project, old_name)) > 0

    success = SQLiteStorage.rename_run(project, old_name, new_name)
    assert success is True

    assert SQLiteStorage.get_run_config(project, old_name) is None
    assert len(SQLiteStorage.get_logs(project, old_name)) == 0

    assert SQLiteStorage.get_run_config(project, new_name) is not None
    assert len(SQLiteStorage.get_logs(project, new_name)) > 0

    new_logs = SQLiteStorage.get_logs(project, new_name)
    assert new_logs[0]["accuracy"] == 0.95
    assert new_logs[0]["loss"] == 0.1


def test_rename_run_duplicate_name(temp_dir):
    project = "test_project"
    run1 = "run1"
    run2 = "run2"

    SQLiteStorage.bulk_log(project, run1, [{"a": 1}])
    SQLiteStorage.bulk_log(project, run2, [{"b": 2}])

    success = SQLiteStorage.rename_run(project, run1, run2)
    assert success is False

    assert len(SQLiteStorage.get_logs(project, run1)) > 0
    assert len(SQLiteStorage.get_logs(project, run2)) > 0


def test_rename_run_with_media(temp_dir):
    from trackio.utils import MEDIA_DIR

    project = "test_project"
    old_name = "old_run"
    new_name = "new_run"

    media_dir = MEDIA_DIR / project / old_name
    media_dir.mkdir(parents=True, exist_ok=True)
    test_file = media_dir / "test.txt"
    test_file.write_text("test content")

    metrics = [
        {
            "image": {
                "_type": "trackio.image",
                "file_path": f"{project}/{old_name}/test.txt",
                "caption": "test",
            }
        }
    ]
    SQLiteStorage.bulk_log(project, old_name, metrics)

    success = SQLiteStorage.rename_run(project, old_name, new_name)
    assert success is True

    new_media_dir = MEDIA_DIR / project / new_name
    assert new_media_dir.exists()
    assert (new_media_dir / "test.txt").exists()

    old_media_dir = MEDIA_DIR / project / old_name
    assert not old_media_dir.exists()

    new_logs = SQLiteStorage.get_logs(project, new_name)
    assert len(new_logs) > 0
    assert "image" in new_logs[0]
    assert new_logs[0]["image"]["file_path"].startswith(f"{project}/{new_name}/")


def test_rename_run_nonexistent(temp_dir):
    project = "test_project"
    old_name = "nonexistent_run"
    new_name = "new_run"

    success = SQLiteStorage.rename_run(project, old_name, new_name)
    assert success is False


def test_rename_run_empty_name(temp_dir):
    project = "test_project"
    old_name = "old_run"

    SQLiteStorage.bulk_log(project, old_name, [{"a": 1}])

    success = SQLiteStorage.rename_run(project, old_name, "")
    assert success is False

    success = SQLiteStorage.rename_run(project, old_name, "   ")
    assert success is False

    assert len(SQLiteStorage.get_logs(project, old_name)) > 0


def test_rename_run_with_system_metrics(temp_dir):
    project = "test_project"
    old_name = "old_run"
    new_name = "new_run"

    metrics = [{"accuracy": 0.95}]
    SQLiteStorage.bulk_log(project, old_name, metrics)

    system_metrics = [{"gpu_usage": 80.5}]
    SQLiteStorage.bulk_log_system(project, old_name, system_metrics)

    success = SQLiteStorage.rename_run(project, old_name, new_name)
    assert success is True

    assert len(SQLiteStorage.get_logs(project, new_name)) > 0
    assert len(SQLiteStorage.get_system_logs(project, new_name)) > 0
    assert len(SQLiteStorage.get_system_logs(project, old_name)) == 0

    new_system_logs = SQLiteStorage.get_system_logs(project, new_name)
    assert new_system_logs[0]["gpu_usage"] == 80.5
