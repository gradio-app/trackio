import secrets
import time

from gradio_client import Client

import trackio


def test_burst_logs_single_process(test_space_id, wait_for_client):
    """
    Burst-sends trackio.log() calls in one process; all entries should arrive at
    the Space. Count is kept small because /get_metric_values returns every step
    (large responses are a major part of e2e wall time).
    """
    project_name = f"test_burst_{secrets.token_urlsafe(8)}"
    run_name = "burst_run"
    num_logs = 120

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
