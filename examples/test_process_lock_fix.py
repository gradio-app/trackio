#!/usr/bin/env python3
"""
Test script to validate the ProcessLock fix by using SQLiteStorage methods directly.
This bypasses trackio's queuing mechanism to test the cross-process locking.
"""

import json
import multiprocessing
import random
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from trackio.sqlite_storage import SQLiteStorage


def direct_storage_worker(worker_id, duration_seconds=8):
    """
    Worker that uses SQLiteStorage.log() and bulk_log() directly
    to test the ProcessLock implementation.
    """
    print(f"🚀 Worker {worker_id} starting (using SQLiteStorage directly)...")

    project = "process_lock_test"
    run_name = f"test_run_{worker_id}"

    start_time = time.time()
    operations = 0
    errors = 0
    db_locked_errors = 0

    while time.time() - start_time < duration_seconds:
        try:
            # Randomly choose between single log and bulk log
            if random.random() < 0.6:  # 60% single logs
                # Single log operation
                metrics = {
                    "value": random.random() * 100,
                    "worker_id": worker_id,
                    "operation": operations,
                    "type": "single",
                }

                SQLiteStorage.log(
                    project=project, run=run_name, metrics=metrics, step=operations
                )
                operations += 1

            else:  # 40% bulk logs
                # Bulk log operation
                batch_size = random.randint(5, 20)
                metrics_list = []
                steps = []

                for i in range(batch_size):
                    metrics = {
                        "value": random.random() * 100,
                        "worker_id": worker_id,
                        "batch_item": i,
                        "type": "bulk",
                    }
                    metrics_list.append(metrics)
                    steps.append(operations + i)

                SQLiteStorage.bulk_log(
                    project=project,
                    run=run_name,
                    metrics_list=metrics_list,
                    steps=steps,
                )
                operations += batch_size

            # Very short random delay to create more contention
            if random.random() < 0.1:  # 10% chance of tiny delay
                time.sleep(0.001)

            if operations % 100 == 0:
                print(f"Worker {worker_id}: {operations} operations completed")

        except Exception as e:
            errors += 1
            error_msg = str(e).lower()
            if "database is locked" in error_msg or "database locked" in error_msg:
                db_locked_errors += 1
                print(
                    f"🔒 Worker {worker_id} got DATABASE LOCKED error #{db_locked_errors}"
                )
            elif errors <= 5:  # Only print first few non-lock errors
                print(f"❌ Worker {worker_id} error: {e}")

    print(
        f"Worker {worker_id} finished: {operations} ops, {errors} total errors, {db_locked_errors} 'database is locked' errors"
    )
    return operations, errors, db_locked_errors


def aggressive_direct_storage_worker(worker_id, duration_seconds=8):
    """
    More aggressive worker that rapidly alternates between log types
    and uses no delays at all.
    """
    print(f"💥 Aggressive worker {worker_id} starting (rapid SQLiteStorage calls)...")

    project = "process_lock_test"
    run_name = f"aggressive_run_{worker_id}"

    start_time = time.time()
    operations = 0
    errors = 0
    db_locked_errors = 0

    while time.time() - start_time < duration_seconds:
        try:
            # Rapidly alternate between single and bulk operations
            for _ in range(10):  # Do 10 operations in rapid succession
                metrics = {"rapid": True, "worker": worker_id, "seq": operations}

                SQLiteStorage.log(
                    project=project, run=run_name, metrics=metrics, step=operations
                )
                operations += 1

            # Then do a bulk operation
            metrics_list = [
                {"bulk": True, "worker": worker_id, "item": i} for i in range(15)
            ]

            SQLiteStorage.bulk_log(
                project=project, run=run_name, metrics_list=metrics_list
            )
            operations += 15

            # NO DELAY - maximum stress!

        except Exception as e:
            errors += 1
            error_msg = str(e).lower()
            if "database is locked" in error_msg or "database locked" in error_msg:
                db_locked_errors += 1
                print(
                    f"🔒 Aggressive worker {worker_id} LOCKED! (error #{db_locked_errors})"
                )

    print(
        f"Aggressive worker {worker_id}: {operations} ops, {errors} errors, {db_locked_errors} locked"
    )
    return operations, errors, db_locked_errors


def mixed_read_write_worker(worker_id, duration_seconds=8):
    """
    Worker that mixes reads and writes using SQLiteStorage methods.
    """
    print(f"📖 Mixed R/W worker {worker_id} starting...")

    project = "process_lock_test"
    run_name = f"mixed_run_{worker_id}"

    start_time = time.time()
    operations = 0
    errors = 0
    db_locked_errors = 0

    while time.time() - start_time < duration_seconds:
        try:
            # Write some data
            metrics = {"mixed": True, "worker": worker_id, "op": operations}
            SQLiteStorage.log(project, run_name, metrics, operations)
            operations += 1

            # Read data back
            if operations % 10 == 0:
                logs = SQLiteStorage.get_logs(project, run_name)
                # Also get runs to stress the database more
                runs = SQLiteStorage.get_runs(project)
                if runs:
                    max_steps = SQLiteStorage.get_max_steps_for_runs(project, runs[:5])

        except Exception as e:
            errors += 1
            error_msg = str(e).lower()
            if "database is locked" in error_msg or "database locked" in error_msg:
                db_locked_errors += 1
                print(f"🔒 Mixed worker {worker_id} LOCKED!")

    print(
        f"Mixed worker {worker_id}: {operations} ops, {errors} errors, {db_locked_errors} locked"
    )
    return operations, errors, db_locked_errors


def run_process_lock_test():
    """
    Run the test using SQLiteStorage methods directly.
    """
    print("=" * 70)
    print("🔧 TESTING PROCESSLOCK FIX WITH DIRECT SQLITESTORAGE CALLS")
    print("=" * 70)
    print()
    print("This test uses SQLiteStorage.log() and bulk_log() directly")
    print("to validate the ProcessLock cross-process synchronization.")
    print()

    # Clean up
    project = "process_lock_test"
    db_path = SQLiteStorage.get_project_db_path(project)
    lock_path = Path(SQLiteStorage._get_process_lock(project).lockfile_path)

    if db_path.exists():
        db_path.unlink()
        print(f"🧹 Cleaned existing database")
    if lock_path.exists():
        lock_path.unlink()
        print(f"🧹 Cleaned existing lock file")

    duration = 8  # seconds
    num_normal = 4  # Normal workers
    num_aggressive = 4  # Aggressive workers
    num_mixed = 2  # Mixed read/write workers

    total_processes = num_normal + num_aggressive + num_mixed

    print(f"Starting {total_processes} concurrent processes:")
    print(f"  - {num_normal} normal workers (using log/bulk_log)")
    print(f"  - {num_aggressive} aggressive workers (rapid calls)")
    print(f"  - {num_mixed} mixed read/write workers")
    print(f"  - Duration: {duration} seconds")
    print()

    with multiprocessing.Pool(processes=total_processes) as pool:
        results = []

        # Start normal workers
        for i in range(num_normal):
            result = pool.apply_async(direct_storage_worker, (i, duration))
            results.append(("normal", i, result))

        # Start aggressive workers
        for i in range(num_aggressive):
            result = pool.apply_async(aggressive_direct_storage_worker, (i, duration))
            results.append(("aggressive", i, result))

        # Start mixed workers
        for i in range(num_mixed):
            result = pool.apply_async(mixed_read_write_worker, (i, duration))
            results.append(("mixed", i, result))

        print(f"⏳ Running for {duration} seconds...")
        print()

        # Collect results
        total_operations = 0
        total_errors = 0
        total_db_locked_errors = 0

        for worker_type, worker_id, result in results:
            try:
                ops, errors, db_locked = result.get(timeout=duration + 10)
                total_operations += ops
                total_errors += errors
                total_db_locked_errors += db_locked
            except Exception as e:
                print(f"❌ {worker_type} worker {worker_id} failed: {e}")
                total_errors += 1

    print()
    print("=" * 70)
    print("📊 TEST RESULTS")
    print("=" * 70)
    print(f"Total operations completed: {total_operations}")
    print(f"Total errors (all types): {total_errors}")
    print(f"\n🔒 'database is locked' errors: {total_db_locked_errors}")
    print()

    if total_db_locked_errors == 0:
        print("✅ SUCCESS! No 'database is locked' errors!")
        print("The ProcessLock fix is working correctly.")
        print()
        print("The cross-process file lock ensures that:")
        print("1. Only one process can write to the database at a time")
        print("2. Lock acquisition has retry logic with timeout")
        print("3. Both log() and bulk_log() are protected")
    else:
        print(f"⚠️ WARNING: Still got {total_db_locked_errors} database locked errors!")
        print("The ProcessLock may need adjustment or there may be other issues.")

    # Verify database integrity
    if db_path.exists():
        try:
            import sqlite3

            conn = sqlite3.connect(str(db_path))
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM metrics")
            count = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(DISTINCT run_name) FROM metrics")
            run_count = cursor.fetchone()[0]

            print()
            print(f"📈 Database stats:")
            print(f"  - Total entries: {count}")
            print(f"  - Unique runs: {run_count}")

            cursor.execute("PRAGMA integrity_check")
            result = cursor.fetchone()[0]
            if result == "ok":
                print("  - Integrity check: ✅ PASSED")
            else:
                print(f"  - Integrity check: ⚠️ {result}")

            conn.close()
        except Exception as e:
            print(f"❌ Failed to verify database: {e}")

    # Check if lock file was cleaned up
    if lock_path.exists():
        print(f"\n⚠️ Lock file still exists at: {lock_path}")
        print("This is expected if a process was interrupted.")

    return total_db_locked_errors == 0


if __name__ == "__main__":
    success = run_process_lock_test()
    sys.exit(0 if success else 1)
