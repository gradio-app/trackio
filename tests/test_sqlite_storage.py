import multiprocessing
import os
import random
import sqlite3
import tempfile
import time

from trackio.sqlite_storage import SQLiteStorage


def test_init_creates_metrics_table(temp_dir):
    db_path = SQLiteStorage.init_db("proj1")
    assert os.path.exists(db_path)
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM metrics")


def test_log_and_get_metrics(temp_dir):
    metrics = {"acc": 0.9}
    run_id = SQLiteStorage.add_run(project="proj1", name="run1")
    SQLiteStorage.log(project="proj1", run_id=run_id, metrics=metrics)
    results = SQLiteStorage.get_logs(project="proj1", run_id=run_id)
    assert len(results) == 1
    assert results[0]["acc"] == 0.9
    assert results[0]["step"] == 0
    assert "timestamp" in results[0]


def test_get_projects_and_runs(temp_dir):
    run1_id = SQLiteStorage.add_run(project="proj1", name="run1")
    run2_id = SQLiteStorage.add_run(project="proj2", name="run2")
    SQLiteStorage.log(project="proj1", run_id=run1_id, metrics={"a": 1})
    SQLiteStorage.log(project="proj2", run_id=run2_id, metrics={"b": 2})
    projects = set(SQLiteStorage.get_projects())
    assert {"proj1", "proj2"}.issubset(projects)
    run_names = set(run.name for run in SQLiteStorage.get_runs("proj1"))
    assert "run1" in run_names


def test_import_export(temp_dir):
    db_path_1 = SQLiteStorage.init_db("proj1")
    db_path_2 = SQLiteStorage.init_db("proj2")

    # log some data, export to parquet, keep a copy in `metrics`
    run1_id = SQLiteStorage.add_run(project="proj1", name="run1")
    run2_id = SQLiteStorage.add_run(project="proj2", name="run2")
    SQLiteStorage.log(project="proj1", run_id=run1_id, metrics={"a": 1})
    SQLiteStorage.log(project="proj2", run_id=run2_id, metrics={"b": 2})
    SQLiteStorage.export_to_parquet()
    metrics_before = {}
    for proj in SQLiteStorage.get_projects():
        if proj not in metrics_before:
            metrics_before[proj] = {}
        for run in SQLiteStorage.get_runs(proj):
            metrics_before[proj][run.id] = SQLiteStorage.get_logs(proj, run.id)

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
            metrics_after[proj][run.id] = SQLiteStorage.get_logs(proj, run.id)

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
    run_id = SQLiteStorage.add_run(project, run_name)
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
                SQLiteStorage.bulk_log(project, run_id, metrics_list)

        except sqlite3.OperationalError as e:
            error_msg = str(e).lower()
            if "database is locked" in error_msg or "database is busy" in error_msg:
                db_locked_errors += 1
                time.sleep(random.uniform(0.0001, 0.001))
        except Exception:
            pass

    return db_locked_errors


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
            logs = SQLiteStorage.get_logs(project, run.id)
            total_logs += len(logs)

        assert total_logs > 0, "Should have created some log entries"
