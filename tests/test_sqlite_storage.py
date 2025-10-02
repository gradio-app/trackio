import multiprocessing
import os
import platform
import random
import sqlite3
import tempfile
import time

import orjson
import pytest

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
    SQLiteStorage.store_config(project, run_name, config)

    metrics = [{"accuracy": 0.95, "loss": 0.1}]
    SQLiteStorage.bulk_log(project, run_name, metrics)

    assert SQLiteStorage.get_run_config(project, run_name) is not None
    assert len(SQLiteStorage.get_logs(project, run_name)) > 0

    SQLiteStorage.delete_run(project, run_name)
    assert SQLiteStorage.get_run_config(project, run_name) is None
    assert len(SQLiteStorage.get_logs(project, run_name)) == 0


def test_import_export(temp_dir):
    db_path_1 = SQLiteStorage.init_db("proj1")
    db_path_2 = SQLiteStorage.init_db("proj2")

    # log some data, export to parquet, keep a copy in `metrics`
    SQLiteStorage.log(project="proj1", run="run1", metrics={"a": 1})
    SQLiteStorage.log(project="proj2", run="run2", metrics={"b": 2})
    SQLiteStorage.export_to_parquet()
    metrics_before = {}
    for proj in SQLiteStorage.get_projects():
        if proj not in metrics_before:
            metrics_before[proj] = {}
        for run in SQLiteStorage.get_runs(proj):
            metrics_before[proj][run] = SQLiteStorage.get_logs(proj, run)

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
    project, worker_id, duration_seconds=2, sync_start_time=None
):
    """
    Worker that uses SQLiteStorage methods for database access.
    This will be protected by ProcessLock when available.
    """

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
    This test should fail on main (without ProcessLock) and pass with ProcessLock fix.
    """
    with tempfile.TemporaryDirectory() as temp_dir:
        os.environ["TRACKIO_DIR"] = str(temp_dir)
        project = "concurrent_test"

        num_processes = 8
        duration = 2

        # Synchronized start time (0.5s from now) to make all processes hit db simultaneously
        sync_start_time = time.time() + 0.5

        with multiprocessing.Pool(processes=num_processes) as pool:
            results = [
                pool.apply_async(
                    _worker_using_sqlite_storage,
                    (project, i, duration, sync_start_time),
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
