"""
Test for database locking issues with concurrent access.
This test is designed to fail on main (without ProcessLock) and pass on branches with ProcessLock fix.
"""

import multiprocessing
import random
import sqlite3
import tempfile
import time
from pathlib import Path

import pytest


def _worker_using_sqlite_storage(
    temp_trackio_dir, project, worker_id, duration_seconds=2, sync_start_time=None
):
    """
    Worker that uses SQLiteStorage methods for database access.
    This will be protected by ProcessLock when available.
    """
    import os
    import random
    import sqlite3
    import time

    # Set environment to use the temp directory
    os.environ["XDG_CACHE_HOME"] = str(temp_trackio_dir)

    # Import SQLiteStorage in the worker process
    from trackio.sqlite_storage import SQLiteStorage

    # Each process gets its own scheduler with its own thread lock
    # The thread locks don't coordinate across processes - this is the original issue!

    # Monkey patch SQLiteStorage._get_connection to use a very short timeout
    original_get_connection = SQLiteStorage._get_connection

    def aggressive_get_connection(db_path):
        import sqlite3

        # Very short timeout to make database locking more likely
        conn = sqlite3.connect(str(db_path), timeout=0.01)  # 10ms timeout!
        conn.row_factory = sqlite3.Row
        return conn

    SQLiteStorage._get_connection = aggressive_get_connection

    # Wait for synchronized start if provided
    if sync_start_time:
        while time.time() < sync_start_time:
            time.sleep(0.001)

    run_name = f"worker_{worker_id}"
    operations = 0
    db_locked_errors = 0

    start_time = time.time()
    while time.time() - start_time < duration_seconds:
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

            # NO delay and do multiple operations in tight loops for maximum contention!
            # Do extra operations in quick succession to increase collision probability
            for _ in range(3):
                if random.random() < 0.5:
                    extra_metrics = {
                        "extra": True,
                        "worker": worker_id,
                        "round": operations,
                    }
                    SQLiteStorage.log(project, run_name + "_extra", extra_metrics)
                    operations += 1

        except sqlite3.OperationalError as e:
            error_msg = str(e).lower()
            if "database is locked" in error_msg or "database is busy" in error_msg:
                db_locked_errors += 1
                # Very small backoff to keep pressure high
                time.sleep(random.uniform(0.0001, 0.001))
        except Exception:
            pass  # Ignore other errors for this test

    return operations, db_locked_errors


def test_concurrent_database_access_without_errors():
    """
    Test that concurrent database access doesn't produce 'database is locked' errors.
    This test should fail on main (without ProcessLock) and pass with ProcessLock fix.
    """
    # Create a temporary directory for this test
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_trackio_dir = Path(temp_dir)
        project = "concurrent_test"

        # Run many concurrent processes for longer to create maximum contention
        num_processes = 8
        duration = 3

        # Synchronized start time (1 second from now) to make all processes hit DB simultaneously
        sync_start_time = time.time() + 1.0

        with multiprocessing.Pool(processes=num_processes) as pool:
            results = [
                pool.apply_async(
                    _worker_using_sqlite_storage,
                    (temp_trackio_dir, project, i, duration, sync_start_time),
                )
                for i in range(num_processes)
            ]

            total_operations = 0
            total_db_locked_errors = 0

            for result in results:
                ops, db_locked = result.get(timeout=duration + 10)
                total_operations += ops
                total_db_locked_errors += db_locked

        print(f"Total operations: {total_operations}")
        print(f"Database locked errors: {total_db_locked_errors}")

        # The test expectation: ProcessLock should prevent database locked errors
        assert total_db_locked_errors == 0, (
            f"Got {total_db_locked_errors} 'database is locked' errors - ProcessLock fix failed"
        )

        # Verify that operations were successful
        assert total_operations > 0, "Some operations should have succeeded"

        # Verify database integrity by using SQLiteStorage methods
        import os

        os.environ["XDG_CACHE_HOME"] = str(temp_trackio_dir)

        from trackio.sqlite_storage import SQLiteStorage

        # Check that we can read the data back
        runs = SQLiteStorage.get_runs(project)
        assert len(runs) > 0, "Should have created some runs"

        # Verify we can get logs for the runs
        total_logs = 0
        for run in runs:
            logs = SQLiteStorage.get_logs(project, run)
            total_logs += len(logs)

        assert total_logs > 0, "Should have created some log entries"
        print(f"Total log entries created: {total_logs}")


if __name__ == "__main__":
    test_concurrent_database_access_without_errors()
