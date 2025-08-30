import time

import trackio
from trackio.sqlite_storage import SQLiteStorage


def test_rapid_bulk_logging():
    """
    Test that logs sent rapidly across different runs are all successfully logged with correct run names.
    Also tests that trackio.log() is not too slow.
    """

    project_name = "test_bulk_logging"
    run1_name = "bulk_test_run1"
    run2_name = "bulk_test_run2"

    trackio.init(project=project_name, name=run1_name)
    start_time = time.time()

    num_logs_run1 = 300
    for i in range(num_logs_run1):
        trackio.log({"metric": i, "value": i * 2}, step=i)

    trackio.init(project=project_name, name=run2_name)
    num_logs_run2 = 700
    for i in range(num_logs_run2):
        trackio.log({"metric": i, "value": i * 3}, step=i)
    time_to_run_1000_logs = time.time() - start_time

    assert time_to_run_1000_logs < 0.1, (
        f"1000 calls of trackio.log() took {time_to_run_1000_logs} seconds, which is too long"
    )
    trackio.finish()

    time.sleep(0.6)  # Wait for the client to send the logs

    # Verify run1 metrics
    metrics_run1 = SQLiteStorage.get_logs(project_name, run1_name)
    assert len(metrics_run1) == num_logs_run1, (
        f"Expected {num_logs_run1} logs for run1, but found {len(metrics_run1)}"
    )

    for i, metric_entry in enumerate(metrics_run1):
        assert metric_entry["metric"] == i, (
            f"Expected metric={i}, got {metric_entry['metric']}"
        )
        assert metric_entry["value"] == i * 2, (
            f"Expected value={i * 2}, got {metric_entry['value']}"
        )
        assert metric_entry["step"] == i, (
            f"Expected step={i}, got {metric_entry['step']}"
        )

    # Verify run2 metrics
    metrics_run2 = SQLiteStorage.get_logs(project_name, run2_name)
    assert len(metrics_run2) == num_logs_run2, (
        f"Expected {num_logs_run2} logs for run2, but found {len(metrics_run2)}"
    )

    for i, metric_entry in enumerate(metrics_run2):
        assert metric_entry["metric"] == i, (
            f"Expected metric={i}, got {metric_entry['metric']}"
        )
        assert metric_entry["value"] == i * 3, (
            f"Expected value={i * 3}, got {metric_entry['value']}"
        )
        assert metric_entry["step"] == i, (
            f"Expected step={i}, got {metric_entry['step']}"
        )
