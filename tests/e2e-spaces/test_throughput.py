import secrets
import threading
import time

from gradio_client import Client

import trackio


def test_burst_logs_single_process(test_space_id, wait_for_client):
    """
    Burst-sends many trackio.log() calls in one process; all entries should
    eventually arrive at the Space. Kept moderate in count so CI stays fast.
    """
    project_name = f"test_burst_{secrets.token_urlsafe(8)}"
    run_name = "burst_run"
    num_logs = 400

    run = trackio.init(project=project_name, name=run_name, space_id=test_space_id)
    wait_for_client(run)

    t0 = time.time()
    for i in range(num_logs):
        trackio.log({"loss": 1.0 / (i + 1), "step_val": i})
    burst_duration = time.time() - t0
    print(f"Burst of {num_logs} log() calls took {burst_duration:.2f}s")

    trackio.finish()

    verify_client = Client(test_space_id)
    summary = verify_client.predict(
        project=project_name, run=run_name, api_name="/get_run_summary"
    )
    assert summary["num_logs"] == num_logs, (
        f"Expected {num_logs} logs on Space, got {summary['num_logs']}"
    )

    loss_values = verify_client.predict(
        project=project_name,
        run=run_name,
        metric_name="loss",
        api_name="/get_metric_values",
    )
    assert len(loss_values) == num_logs
    assert loss_values[0]["step"] == 0
    assert loss_values[-1]["step"] == num_logs - 1


def test_parallel_threads_log_smoke(test_space_id, wait_for_client):
    """
    A few concurrent runs with modest log volume to exercise concurrent writes
    without the wall time of a full stress test.
    """
    project_name = f"test_parallel_{secrets.token_urlsafe(8)}"
    num_threads = 4
    logs_per_thread = 50
    errors = []

    def worker(thread_idx):
        try:
            run_name = f"thread_{thread_idx}"
            run = trackio.init(
                project=project_name, name=run_name, space_id=test_space_id
            )
            wait_for_client(run)
            for i in range(logs_per_thread):
                run.log({"loss": 1.0 / (i + 1), "thread": thread_idx})
            run.finish()
        except Exception as e:
            errors.append((thread_idx, e))

    t0 = time.time()
    threads = []
    for t_idx in range(num_threads):
        t = threading.Thread(target=worker, args=(t_idx,))
        threads.append(t)
        t.start()

    for t in threads:
        t.join(timeout=120)

    alive_threads = [idx for idx, t in enumerate(threads) if t.is_alive()]
    assert not alive_threads, f"Threads did not finish before timeout: {alive_threads}"

    wall_time = time.time() - t0
    print(
        f"{num_threads} threads x {logs_per_thread} logs = "
        f"{num_threads * logs_per_thread} total, wall time {wall_time:.1f}s"
    )

    assert not errors, f"Worker errors: {errors}"

    verify_client = Client(test_space_id)
    runs = []
    deadline = time.time() + 90
    while time.time() < deadline:
        try:
            runs = verify_client.predict(
                project=project_name, api_name="/get_runs_for_project"
            )
            if len(runs) == num_threads:
                break
        except Exception:
            verify_client = Client(test_space_id, verbose=False)
        time.sleep(3)
    assert len(runs) == num_threads, f"Expected {num_threads} runs, got {len(runs)}"

    total_logs = 0
    for run_name in runs:
        for attempt in range(3):
            try:
                summary = verify_client.predict(
                    project=project_name,
                    run=run_name,
                    api_name="/get_run_summary",
                )
                break
            except Exception:
                if attempt == 2:
                    raise
                time.sleep(3)
                verify_client = Client(test_space_id)
        total_logs += summary["num_logs"]
        assert summary["num_logs"] == logs_per_thread, (
            f"Run {run_name}: expected {logs_per_thread} logs, got {summary['num_logs']}"
        )

    assert total_logs == num_threads * logs_per_thread
