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


def _user_version(db_path):
    with sqlite3.connect(db_path) as conn:
        return conn.execute("PRAGMA user_version").fetchone()[0]


def _set_user_version(db_path, version):
    with sqlite3.connect(db_path) as conn:
        conn.execute(f"PRAGMA user_version = {version}")


def _register_migrations(monkeypatch, migrations):
    monkeypatch.setattr(trackio.sqlite_storage, "_SCHEMA_MIGRATIONS", migrations)
    monkeypatch.setattr(trackio.sqlite_storage, "SCHEMA_VERSION", 1 + len(migrations))


def test_schema_migrations_upgrade_legacy_database_once_in_order(temp_dir, monkeypatch):
    SQLiteStorage.bulk_log("proj", "run", [{"loss": 1.0}, {"loss": 0.5}])
    db_path = SQLiteStorage.get_project_db_path("proj")
    _set_user_version(db_path, 0)
    applied = []

    def add_loss_column(cursor):
        applied.append(2)
        cursor.execute("ALTER TABLE metrics ADD COLUMN loss REAL")

    def backfill_loss(cursor):
        applied.append(3)
        cursor.execute("UPDATE metrics SET loss = json_extract(metrics, '$.loss')")

    _register_migrations(monkeypatch, {2: add_loss_column, 3: backfill_loss})
    SQLiteStorage.init_db("proj")
    SQLiteStorage.init_db("proj")

    assert applied == [2, 3]
    assert _user_version(db_path) == 3
    with sqlite3.connect(db_path) as conn:
        losses = [
            row[0] for row in conn.execute("SELECT loss FROM metrics ORDER BY id")
        ]
    assert losses == [1.0, 0.5]


def test_failed_schema_migration_keeps_last_completed_version(temp_dir, monkeypatch):
    db_path = SQLiteStorage.init_db("proj")
    _set_user_version(db_path, 1)

    def create_kept(cursor):
        cursor.execute("CREATE TABLE kept (id INTEGER)")

    def create_then_fail(cursor):
        cursor.execute("CREATE TABLE discarded (id INTEGER)")
        raise RuntimeError("migration failed")

    _register_migrations(monkeypatch, {2: create_kept, 3: create_then_fail})
    with pytest.raises(RuntimeError, match="migration failed"):
        SQLiteStorage.init_db("proj")

    assert _user_version(db_path) == 2
    with sqlite3.connect(db_path) as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master")}
    assert "kept" in tables
    assert "discarded" not in tables


_TRACKIO_0_21_SCHEMA = """
CREATE TABLE metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT NOT NULL,
    run_name TEXT NOT NULL, step INTEGER NOT NULL, metrics TEXT NOT NULL
);
CREATE TABLE configs (
    id INTEGER PRIMARY KEY AUTOINCREMENT, run_name TEXT NOT NULL,
    config TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(run_name)
);
CREATE INDEX idx_metrics_run_step ON metrics(run_name, step);
CREATE INDEX idx_configs_run_name ON configs(run_name);
CREATE INDEX idx_metrics_run_timestamp ON metrics(run_name, timestamp);
CREATE TABLE system_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT NOT NULL,
    run_name TEXT NOT NULL, metrics TEXT NOT NULL
);
CREATE INDEX idx_system_metrics_run_timestamp ON system_metrics(run_name, timestamp);
CREATE TABLE project_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE pending_uploads (
    id INTEGER PRIMARY KEY AUTOINCREMENT, space_id TEXT NOT NULL, run_name TEXT,
    step INTEGER, file_path TEXT NOT NULL, relative_path TEXT, created_at TEXT NOT NULL
);
CREATE TABLE alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT NOT NULL,
    run_name TEXT NOT NULL, title TEXT NOT NULL, text TEXT,
    level TEXT NOT NULL DEFAULT 'warn', step INTEGER, alert_id TEXT
);
CREATE INDEX idx_alerts_run ON alerts(run_name);
CREATE INDEX idx_alerts_timestamp ON alerts(timestamp);
CREATE UNIQUE INDEX idx_alerts_alert_id ON alerts(alert_id) WHERE alert_id IS NOT NULL;
"""


def _write_trackio_0_21_project(project):
    db_path = SQLiteStorage.get_project_db_path(project)
    with sqlite3.connect(db_path) as conn:
        conn.executescript(_TRACKIO_0_21_SCHEMA)
        for run, losses in (("run-a", [1.0, 0.5]), ("run-b", [0.9])):
            conn.execute(
                "INSERT INTO configs (run_name, config, created_at) VALUES (?, ?, ?)",
                (run, orjson.dumps({"lr": 0.1, "run": run}).decode(), "2025-01-01"),
            )
            for step, loss in enumerate(losses):
                conn.execute(
                    "INSERT INTO metrics (timestamp, run_name, step, metrics) "
                    "VALUES (?, ?, ?, ?)",
                    (f"2025-01-01T00:00:0{step}", run, step, f'{{"loss": {loss}}}'),
                )
        conn.execute(
            "INSERT INTO alerts (timestamp, run_name, title) VALUES (?, ?, ?)",
            ("2025-01-01T00:00:09", "run-b", "plateau"),
        )
        conn.execute(
            "INSERT INTO pending_uploads (space_id, run_name, file_path, created_at) "
            "VALUES (?, ?, ?, ?)",
            ("u/s", "run-a", "a.png", "2025-01-01"),
        )
    return db_path


def _schema_shape(db_path):
    with sqlite3.connect(db_path) as conn:
        tables = [
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            )
        ]
        shape = {}
        for table in tables:
            columns = sorted(
                tuple(row[1:]) for row in conn.execute(f"PRAGMA table_info({table})")
            )
            indexes = sorted(
                (
                    row[1],
                    row[2],
                    row[4],
                    tuple(
                        info[2]
                        for info in conn.execute(f"PRAGMA index_info('{row[1]}')")
                    ),
                )
                for row in conn.execute(f"PRAGMA index_list({table})")
            )
            shape[table] = (columns, indexes)
        return shape


def test_trackio_0_21_database_migrates_to_current_schema(temp_dir):
    legacy_path = _write_trackio_0_21_project("legacy")
    SQLiteStorage.init_db("legacy")
    fresh_path = SQLiteStorage.init_db("fresh")

    assert _user_version(legacy_path) == trackio.sqlite_storage.SCHEMA_VERSION
    assert _schema_shape(legacy_path) == _schema_shape(fresh_path)


def test_trackio_0_21_runs_get_one_id_shared_across_tables(temp_dir):
    db_path = _write_trackio_0_21_project("legacy")
    SQLiteStorage.init_db("legacy")

    runs = SQLiteStorage.get_run_records("legacy")
    ids = {run["name"]: run["id"] for run in runs}
    assert sorted(ids) == ["run-a", "run-b"]
    assert len(set(ids.values())) == 2
    with sqlite3.connect(db_path) as conn:
        for table in ("metrics", "configs", "alerts", "pending_uploads"):
            pairs = set(conn.execute(f"SELECT run_name, run_id FROM {table}"))
            assert pairs <= set(ids.items()), table

    assert [log["loss"] for log in SQLiteStorage.get_logs("legacy", "run-a")] == [
        1.0,
        0.5,
    ]
    assert [a["title"] for a in SQLiteStorage.get_alerts("legacy")] == ["plateau"]
    configs = SQLiteStorage.get_all_run_configs("legacy")
    assert configs[ids["run-b"]]["lr"] == 0.1


def test_query_project_reads_but_cannot_set_schema_version(temp_dir):
    SQLiteStorage.init_db("proj")
    result = SQLiteStorage.query_project("proj", "PRAGMA user_version")
    assert result["rows"] == [{"user_version": trackio.sqlite_storage.SCHEMA_VERSION}]
    with pytest.raises(Exception):
        SQLiteStorage.query_project("proj", "PRAGMA user_version = 99")
    assert (
        _user_version(SQLiteStorage.get_project_db_path("proj"))
        == trackio.sqlite_storage.SCHEMA_VERSION
    )


def test_log_and_get_metrics(temp_dir):
    metrics = {"acc": 0.9}
    SQLiteStorage.log(project="proj1", run="run1", metrics=metrics)
    results = SQLiteStorage.get_logs(project="proj1", run="run1")
    assert len(results) == 1
    assert results[0]["acc"] == 0.9
    assert results[0]["step"] == 0
    assert "timestamp" in results[0]


def test_get_logs_scalar_only_excludes_heavy_values(temp_dir):
    metrics = {
        "acc": 0.9,
        "count": 3,
        "note": "not plotted",
        "table": {
            "_type": "trackio.table",
            "_value": [{"prompt": "x" * 10_000}],
        },
    }
    SQLiteStorage.log(project="proj1", run="run1", metrics=metrics)

    results = SQLiteStorage.get_logs(project="proj1", run="run1", scalar_only=True)

    assert results == [
        {
            "acc": 0.9,
            "count": 3,
            "timestamp": results[0]["timestamp"],
            "step": 0,
        }
    ]


def test_subsample_metric_rows_preserves_sparse_metrics(temp_dir):
    metrics = []
    steps = []
    for step in range(800):
        for metric_index in range(9):
            metrics.append({f"dense/metric_{metric_index}": 0.0})
            steps.append(step)
        if step % 10 == 0:
            metrics.append({"sparse/value": float(step)})
            steps.append(step)

    SQLiteStorage.bulk_log("proj1", "run1", metrics, steps=steps)

    logs = SQLiteStorage.get_logs("proj1", "run1", max_points=3000)
    sparse_steps = [row["step"] for row in logs if "sparse/value" in row]

    assert len(logs) <= 3000
    assert sparse_steps == list(range(0, 800, 10))


def test_subsample_metric_rows_is_stable_as_rows_are_appended(temp_dir):
    previous_metric_steps = None
    for step_count in range(800, 805):
        metrics = []
        steps = []
        for step in range(step_count):
            for metric_index in range(9):
                metrics.append({f"dense/metric_{metric_index}": 0.0})
                steps.append(step)
            if step % 10 == 0:
                metrics.append({"sparse/value": float(step)})
                steps.append(step)

        project = f"proj-{step_count}"
        SQLiteStorage.bulk_log(project, "run1", metrics, steps=steps)
        logs = SQLiteStorage.get_logs(project, "run1", max_points=3000)
        metric_steps = {
            metric: {row["step"] for row in logs if metric in row}
            for metric in [
                *(f"dense/metric_{index}" for index in range(9)),
                "sparse/value",
            ]
        }

        assert len(logs) <= 3000
        if previous_metric_steps is not None:
            for metric, current_steps in metric_steps.items():
                previous_steps = previous_metric_steps[metric]
                assert previous_steps - current_steps <= {max(previous_steps)}
        previous_metric_steps = metric_steps


def test_scalar_only_rows_do_not_spend_sampling_budget(temp_dir):
    metrics = [
        {
            "table": {
                "_type": "trackio.table",
                "_value": [{"value": index}],
            }
        }
        for index in range(100)
    ]
    metrics.extend({"loss": float(index)} for index in range(10))
    SQLiteStorage.bulk_log("proj1", "run1", metrics)

    logs = SQLiteStorage.get_logs("proj1", "run1", max_points=10, scalar_only=True)

    assert len(logs) == 10
    assert [row["loss"] for row in logs] == [float(index) for index in range(10)]


def test_metric_group_budgets_scale_with_group_size():
    budgets = SQLiteStorage._allocate_metric_group_budgets([100_000, 50, 50, 50], 3000)

    assert sum(budgets) <= 3000
    assert all(budget > 0 for budget in budgets)
    assert budgets[0] > sum(budgets[1:])


def test_metric_group_budgets_keep_every_group_when_budget_allows():
    budgets = SQLiteStorage._allocate_metric_group_budgets([500_000] + [5] * 999, 3000)

    assert sum(budgets) <= 3000
    assert all(budget > 0 for budget in budgets)


def test_dense_metric_survives_many_distinct_signatures(temp_dir):
    metrics = [{"train/loss": float(step)} for step in range(20_000)]
    steps = list(range(20_000))
    metrics.extend({f"eval/sample_{index}/score": 1.0} for index in range(4000))
    steps.extend(range(4000))

    SQLiteStorage.bulk_log("proj1", "run1", metrics, steps=steps)

    logs = SQLiteStorage.get_logs("proj1", "run1", max_points=3000)

    assert len(logs) <= 3000
    assert sum(1 for row in logs if "train/loss" in row) > 1000


def test_spaces_logs_cache_invalidated_by_writes_without_mtime_change(
    temp_dir, monkeypatch
):
    monkeypatch.setattr(trackio.sqlite_storage, "on_spaces", lambda: True)
    monkeypatch.setenv("TRACKIO_DISABLE_LOGS_CACHE", "0")
    project, run_id = "cache-proj", "run-1"
    runs = [{"run": "run", "run_id": run_id}]

    def logged_values():
        single = SQLiteStorage.get_logs(
            project, run_id=run_id, max_points=3000, scalar_only=True
        )
        batch = SQLiteStorage.get_logs_batch(
            project, runs, max_points=3000, scalar_only=True
        )[0]["logs"]
        system = SQLiteStorage.get_system_logs(project, run_id=run_id)
        system_batch = SQLiteStorage.get_system_logs_batch(project, runs)[0]["logs"]
        return (
            [row["step"] for row in single],
            [row["step"] for row in batch],
            [row["gpu"] for row in system],
            [row["gpu"] for row in system_batch],
        )

    try:
        SQLiteStorage.bulk_log(
            project, "run", [{"reward": 0.1}], steps=[0], run_id=run_id
        )
        SQLiteStorage.bulk_log_system(project, "run", [{"gpu": 1}], run_id=run_id)
        db_path = SQLiteStorage.get_project_db_path(project)
        stat = db_path.stat()
        assert logged_values() == ([0], [0], [1], [1])

        SQLiteStorage.bulk_log(
            project, "run", [{"reward": 0.2}], steps=[1], run_id=run_id
        )
        SQLiteStorage.bulk_log_system(project, "run", [{"gpu": 2}], run_id=run_id)
        os.utime(db_path, ns=(stat.st_atime_ns, stat.st_mtime_ns))

        assert logged_values() == ([0, 1], [0, 1], [1, 2], [1, 2])
    finally:
        trackio.sqlite_storage._close_all_persistent_connections()


def test_get_projects_and_runs(temp_dir):
    SQLiteStorage.log(project="proj1", run="run1", metrics={"a": 1})
    SQLiteStorage.log(project="proj2", run="run2", metrics={"b": 2})
    projects = set(SQLiteStorage.get_projects())
    assert {"proj1", "proj2"}.issubset(projects)
    runs = set(SQLiteStorage.get_runs("proj1"))
    assert "run1" in runs


def test_storage_connection_context_closes_connection(temp_dir):
    db_path = SQLiteStorage.init_db("proj1")
    with SQLiteStorage._get_connection(db_path) as conn:
        conn.execute("SELECT 1").fetchone()
    # Confirming that Trackio's _get_connection() closes the connection on exiting the context manager.
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        conn.execute("SELECT 1")


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
    os.unlink(db_path_1)
    os.unlink(db_path_2)

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


def test_get_metric_values_respects_run_id_and_name_resolves_latest_run(temp_dir):
    project = "proj_metric_values"
    run_name = "dup-run"

    SQLiteStorage.bulk_log(
        project,
        run_name,
        [{"loss": 1.0}],
        run_id="run-id-1",
        timestamps=["2024-01-01T00:00:00+00:00"],
    )
    SQLiteStorage.bulk_log(
        project,
        run_name,
        [{"loss": 2.0}],
        run_id="run-id-2",
        timestamps=["2024-01-02T00:00:00+00:00"],
    )

    latest_by_name = SQLiteStorage.get_metric_values(project, run_name, "loss")
    first_by_id = SQLiteStorage.get_metric_values(
        project, run_name, "loss", run_id="run-id-1"
    )
    second_by_id = SQLiteStorage.get_metric_values(
        project, run_name, "loss", run_id="run-id-2"
    )

    assert [row["value"] for row in latest_by_name] == [2.0]
    assert [row["value"] for row in first_by_id] == [1.0]
    assert [row["value"] for row in second_by_id] == [2.0]


def test_rename_run(temp_dir):
    project = "test_project"
    old_name = "old_run"
    new_name = "new_run"

    config = {"param1": "value1", "_Created": "2023-01-01T00:00:00"}
    metrics = [{"accuracy": 0.95, "loss": 0.1}]
    SQLiteStorage.bulk_log(project, old_name, metrics, config=config)

    assert SQLiteStorage.get_run_config(project, old_name) is not None
    assert len(SQLiteStorage.get_logs(project, old_name)) > 0

    SQLiteStorage.rename_run(project, old_name, new_name)

    assert SQLiteStorage.get_run_config(project, old_name) is None
    assert len(SQLiteStorage.get_logs(project, old_name)) == 0

    assert SQLiteStorage.get_run_config(project, new_name) is not None
    assert len(SQLiteStorage.get_logs(project, new_name)) > 0

    new_logs = SQLiteStorage.get_logs(project, new_name)
    assert new_logs[0]["accuracy"] == 0.95
    assert new_logs[0]["loss"] == 0.1


def test_rename_run_allows_duplicate_name_in_new_schema(temp_dir):
    project = "test_project"
    run1 = "run1"
    run2 = "run2"

    SQLiteStorage.bulk_log(project, run1, [{"a": 1}])
    SQLiteStorage.bulk_log(project, run2, [{"b": 2}])

    SQLiteStorage.rename_run(project, run1, run2)

    records = SQLiteStorage.get_run_records(project)
    duplicate_names = [record for record in records if record["name"] == run2]
    assert len(duplicate_names) == 2


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

    SQLiteStorage.rename_run(project, old_name, new_name)

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

    with pytest.raises(ValueError, match="does not exist"):
        SQLiteStorage.rename_run(project, old_name, new_name)


def test_rename_run_empty_name(temp_dir):
    project = "test_project"
    old_name = "old_run"

    SQLiteStorage.bulk_log(project, old_name, [{"a": 1}])

    with pytest.raises(ValueError, match="cannot be empty"):
        SQLiteStorage.rename_run(project, old_name, "")

    with pytest.raises(ValueError, match="cannot be empty"):
        SQLiteStorage.rename_run(project, old_name, "   ")

    assert len(SQLiteStorage.get_logs(project, old_name)) > 0


def test_rename_run_with_system_metrics(temp_dir):
    project = "test_project"
    old_name = "old_run"
    new_name = "new_run"

    metrics = [{"accuracy": 0.95}]
    SQLiteStorage.bulk_log(project, old_name, metrics)

    system_metrics = [{"gpu_usage": 80.5}]
    SQLiteStorage.bulk_log_system(project, old_name, system_metrics)

    SQLiteStorage.rename_run(project, old_name, new_name)

    assert len(SQLiteStorage.get_logs(project, new_name)) > 0
    assert len(SQLiteStorage.get_system_logs(project, new_name)) > 0
    assert len(SQLiteStorage.get_system_logs(project, old_name)) == 0

    new_system_logs = SQLiteStorage.get_system_logs(project, new_name)
    assert new_system_logs[0]["gpu_usage"] == 80.5


def test_bucket_upload_paths_match_mount_layout(temp_dir):
    project = "proj_bucket"
    SQLiteStorage.log(project=project, run="run1", metrics={"loss": 0.5})

    media_dir = Path(temp_dir) / "media" / project
    media_dir.mkdir(parents=True)
    (media_dir / "img.png").write_bytes(b"fake")

    db_path = SQLiteStorage.get_project_db_path(project)
    files_to_add = [(str(db_path), f"trackio/{db_path.name}")]
    for media_file in media_dir.rglob("*"):
        if media_file.is_file():
            rel = media_file.relative_to(Path(temp_dir))
            files_to_add.append((str(media_file), f"trackio/{rel}"))

    mount_point = Path("/data")
    trackio_dir = mount_point / "trackio"
    for local_path, remote_path in files_to_add:
        mounted = mount_point / remote_path
        assert str(mounted).startswith(str(trackio_dir)), (
            f"Bucket path {remote_path!r} would mount at {mounted}, "
            f"outside TRACKIO_DIR={trackio_dir}"
        )
        assert Path(local_path).exists()


def test_query_project_allows_select(temp_dir):
    SQLiteStorage.log(project="qproj", run="r1", metrics={"acc": 0.9})
    result = SQLiteStorage.query_project("qproj", "SELECT run_name FROM metrics")
    assert result["project"] == "qproj"
    assert result["columns"] == ["run_name"]
    assert result["row_count"] == 1
    assert result["rows"][0]["run_name"] == "r1"


def test_query_project_allows_with_and_safe_pragma(temp_dir):
    SQLiteStorage.log(project="qproj", run="r1", metrics={"acc": 0.9})
    cte = SQLiteStorage.query_project(
        "qproj", "WITH t AS (SELECT 1 AS x) SELECT x FROM t"
    )
    assert cte["rows"] == [{"x": 1}]
    pragma = SQLiteStorage.query_project("qproj", "PRAGMA table_info(metrics)")
    assert pragma["row_count"] > 0


def test_query_project_denies_writes(temp_dir):
    SQLiteStorage.log(project="qproj", run="r1", metrics={"acc": 0.9})
    for bad in [
        "INSERT INTO metrics (project_name, run_name, step, metrics, timestamp) VALUES ('x','y',0,'{}','t')",
        "UPDATE metrics SET run_name='x'",
        "DELETE FROM metrics",
        "DROP TABLE metrics",
        "PRAGMA journal_mode = DELETE",
    ]:
        with pytest.raises(ValueError):
            SQLiteStorage.query_project("qproj", bad)


def test_query_project_row_limit(temp_dir):
    for i in range(5):
        SQLiteStorage.log(project="qproj", run=f"r{i}", metrics={"a": i})
    with pytest.raises(ValueError, match="more than"):
        SQLiteStorage.query_project("qproj", "SELECT * FROM metrics", max_rows=2)


def test_query_project_normalizes_bytes(temp_dir):
    SQLiteStorage.log(project="qproj", run="r1", metrics={"a": 1})
    result = SQLiteStorage.query_project("qproj", "SELECT x'80FF8081' AS b")
    assert result["rows"][0]["b"] == "80ff8081"


def test_query_project_decodes_utf8_blobs(temp_dir):
    """JSON columns are stored as UTF-8 blobs and must come back readable."""
    SQLiteStorage.bulk_log(
        project="qproj",
        run="r1",
        metrics_list=[{"a": 1}],
        config={"lr": 0.01, "_Group": "sweep-1"},
    )
    result = SQLiteStorage.query_project(
        "qproj", "SELECT config FROM configs WHERE run_name = 'r1'"
    )
    config = result["rows"][0]["config"]
    assert isinstance(config, str)
    parsed = orjson.loads(config)
    assert parsed["lr"] == 0.01
    assert parsed["_Group"] == "sweep-1"


def test_query_project_missing_project(temp_dir):
    with pytest.raises(FileNotFoundError):
        SQLiteStorage.query_project("nonexistent", "SELECT 1")


def test_get_metric_values_max_points_keeps_ends_within_range(temp_dir):
    project = "proj_metric_values_max_points"
    SQLiteStorage.bulk_log(
        project,
        "run",
        [{"loss": float(i)} for i in range(1000)],
        steps=list(range(1000)),
    )

    rows = SQLiteStorage.get_metric_values(
        project, "run", "loss", around_step=500, window=100, max_points=11
    )

    assert len(rows) == 11
    assert rows[0]["step"] == 400
    assert rows[-1]["step"] == 600
    assert [row["step"] for row in rows] == sorted(row["step"] for row in rows)
    assert (
        len(SQLiteStorage.get_metric_values(project, "run", "loss", max_points=None))
        == 1000
    )


@pytest.mark.parametrize("use_index", [True, False])
def test_run_records_preserve_metric_only_runs_and_first_timestamps(
    temp_dir, use_index
):
    db_path = SQLiteStorage.init_db("records")
    with sqlite3.connect(db_path) as conn:
        conn.executemany(
            "INSERT INTO metrics (run_id, run_name, timestamp, step, metrics) "
            "VALUES (?, ?, ?, ?, '{}')",
            [
                ("b", "same name", "2026-01-03", 0),
                ("a", "same name", "2026-01-02", 0),
                ("a", "same name", "2026-01-01", 1),
                ("a", "other name", "2026-01-04", 2),
            ],
        )
        if not use_index:
            conn.execute("DROP INDEX idx_metrics_run_record")
    assert SQLiteStorage.get_run_records("records") == [
        {"id": "a", "name": "same name", "created_at": "2026-01-01"},
        {"id": "b", "name": "same name", "created_at": "2026-01-03"},
        {"id": "a", "name": "other name", "created_at": "2026-01-04"},
    ]


def test_run_records_query_work_does_not_grow_with_metric_count(temp_dir, monkeypatch):
    from contextlib import contextmanager

    db_path = SQLiteStorage.init_db("records")
    assert SQLiteStorage.get_run_records("records") == []
    original_connection = SQLiteStorage._get_connection
    instructions = 0

    def progress():
        nonlocal instructions
        instructions += 1
        return 0

    @contextmanager
    def measured_connection(*args, **kwargs):
        with original_connection(*args, **kwargs) as conn:
            conn.set_progress_handler(progress, 1)
            try:
                yield conn
            finally:
                conn.set_progress_handler(None, 0)

    monkeypatch.setattr(SQLiteStorage, "_get_connection", measured_connection)

    def add_metrics(start, stop):
        with sqlite3.connect(db_path) as conn:
            conn.executemany(
                "INSERT INTO metrics (run_id, run_name, timestamp, step, metrics) "
                "VALUES ('run-id', 'no-config', '2026-01-01', ?, '{}')",
                ((step,) for step in range(start, stop)),
            )

    add_metrics(0, 100)
    expected = SQLiteStorage.get_run_records("records")
    small_query_work = instructions
    add_metrics(100, 20000)
    instructions = 0
    assert SQLiteStorage.get_run_records("records") == expected
    # Count SQLite VM instructions rather than using a noisy wall-clock budget.
    assert instructions < small_query_work * 3
