import secrets
import threading
import time

from gradio_client import Client

import trackio


def test_burst_2000_logs_single_process(test_space_id, wait_for_client):
    """
    A single process burst-sends 2,000 trackio.log() calls in ~2 seconds.
    All 2,000 entries should eventually arrive at the Space.
    """
    project_name = f"test_burst_{secrets.token_urlsafe(8)}"
    run_name = "burst_run"
    num_logs = 2000

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


def test_32_parallel_threads_1000_logs_each(test_space_id, wait_for_client):
    """
    32 parallel threads each run their own trackio run and send 1,000
    log() calls. All 32,000 entries across 32 runs should arrive at the
    Space. This tests concurrent write throughput and server-side locking.
    """
    project_name = f"test_parallel_{secrets.token_urlsafe(8)}"
    num_threads = 32
    logs_per_thread = 1000
    thread_stagger = 0.2
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
        time.sleep(thread_stagger)

    for t in threads:
        t.join(timeout=180)

    wall_time = time.time() - t0
    print(
        f"{num_threads} threads x {logs_per_thread} logs = "
        f"{num_threads * logs_per_thread} total, wall time {wall_time:.1f}s"
    )

    assert not errors, f"Worker errors: {errors}"

    verify_client = Client(test_space_id)

    deadline = time.time() + 120
    while time.time() < deadline:
        runs = verify_client.predict(
            project=project_name, api_name="/get_runs_for_project"
        )
        if len(runs) == num_threads:
            break
        time.sleep(5)
    assert len(runs) == num_threads, f"Expected {num_threads} runs, got {len(runs)}"

    total_logs = 0
    for run_name in runs:
        dl = time.time() + 60
        while time.time() < dl:
            summary = verify_client.predict(
                project=project_name, run=run_name, api_name="/get_run_summary"
            )
            if summary["num_logs"] == logs_per_thread:
                break
            time.sleep(3)
        total_logs += summary["num_logs"]
        assert summary["num_logs"] == logs_per_thread, (
            f"Run {run_name}: expected {logs_per_thread} logs, got {summary['num_logs']}"
        )

    assert total_logs == num_threads * logs_per_thread
