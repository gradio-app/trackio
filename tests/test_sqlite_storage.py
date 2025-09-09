import os
import random
import sqlite3
import threading
import time
from pathlib import Path

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


def test_concurrent_database_access_without_errors(temp_dir):
    """
    Test that concurrent database access doesn't produce 'database is locked' errors.
    This test validates the ProcessLock fix in SQLiteStorage using threading.
    """
    # Import here to get the patched TRACKIO_DIR
    from trackio.utils import TRACKIO_DIR

    project = "concurrent_test"

    # Clean up any existing database and lock file
    db_path = SQLiteStorage.get_project_db_path(project)
    lock_path = TRACKIO_DIR / f"{project}.lock"

    if db_path.exists():
        db_path.unlink()
    if lock_path.exists():
        lock_path.unlink()

    # Results collection
    results = []

    def concurrent_worker(worker_id):
        """Worker function that aggressively writes to SQLite database."""
        run_name = f"worker_{worker_id}"
        operations = 0
        db_locked_errors = 0

        start_time = time.time()
        while time.time() - start_time < 2:  # 2 seconds
            try:
                if random.random() < 0.6:  # 60% single logs
                    metrics = {
                        "value": random.random(),
                        "worker": worker_id,
                        "op": operations,
                    }
                    SQLiteStorage.log(project, run_name, metrics, operations)
                    operations += 1
                else:  # 40% bulk logs
                    batch_size = random.randint(3, 8)
                    metrics_list = [
                        {"batch": True, "worker": worker_id, "item": i}
                        for i in range(batch_size)
                    ]
                    SQLiteStorage.bulk_log(project, run_name, metrics_list)
                    operations += batch_size

            except sqlite3.OperationalError as e:
                if "database is locked" in str(e).lower():
                    db_locked_errors += 1
            except Exception:
                pass  # Ignore other errors for this test

        results.append((operations, db_locked_errors))

    try:
        # Start 4 concurrent threads
        threads = []
        for i in range(4):
            thread = threading.Thread(target=concurrent_worker, args=(i,))
            threads.append(thread)
            thread.start()

        # Wait for all threads to complete
        for thread in threads:
            thread.join()

        # Collect results
        total_operations = sum(ops for ops, _ in results)
        total_db_locked_errors = sum(db_locked for _, db_locked in results)

        # Verify no database locking errors occurred
        assert total_db_locked_errors == 0, (
            f"Got {total_db_locked_errors} 'database is locked' errors - ProcessLock fix failed"
        )

        # Verify operations were successful
        assert total_operations > 0, "No operations completed - test setup issue"

        # Verify database integrity
        assert db_path.exists(), "Database should exist after operations"

        with sqlite3.connect(str(db_path)) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM metrics")
            count = cursor.fetchone()[0]
            assert count > 0, "Database should contain metrics"

            # Check database integrity
            cursor.execute("PRAGMA integrity_check")
            result = cursor.fetchone()[0]
            assert result == "ok", f"Database integrity check failed: {result}"

    finally:
        # Clean up after test
        if db_path.exists():
            db_path.unlink()
        if lock_path.exists():
            lock_path.unlink()
