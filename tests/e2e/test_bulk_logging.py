import time

import trackio


def test_rapid_bulk_logging():
    """Test that 1000 logs sent rapidly are all successfully logged."""
    project_name = "test_bulk_logging"
    run_name = "bulk_test_run"

    # Initialize a new run
    run = trackio.init(project=project_name, name=run_name)

    # Log 1000 metrics rapidly
    num_logs = 1000
    for i in range(num_logs):
        trackio.log({"metric": i, "value": i * 2}, step=i)

    # Finish the run to ensure all logs are sent
    trackio.finish()

    # Give a small buffer for any final processing
    time.sleep(1)

    # Verify all logs were saved
    from trackio.sqlite_storage import SQLiteStorage

    metrics = SQLiteStorage.get_metrics(project_name, run_name)

    # Check that we have all 1000 logs
    assert len(metrics) == num_logs, (
        f"Expected {num_logs} logs, but found {len(metrics)}"
    )

    # Verify the content of logs
    for i, metric_entry in enumerate(metrics):
        assert metric_entry["metric"] == i, (
            f"Expected metric={i}, got {metric_entry['metric']}"
        )
        assert metric_entry["value"] == i * 2, (
            f"Expected value={i * 2}, got {metric_entry['value']}"
        )
        assert metric_entry["step"] == i, (
            f"Expected step={i}, got {metric_entry['step']}"
        )

    print(
        f"✓ Successfully logged and verified {num_logs} rapid logs with bulk batching"
    )


def test_bulk_logging_with_interruption():
    """Test that bulk logging handles interruptions gracefully."""
    project_name = "test_bulk_interrupt"
    run_name = "interrupt_test_run"

    # Initialize a new run
    run = trackio.init(project=project_name, name=run_name)

    # Log some metrics rapidly
    for i in range(100):
        trackio.log({"metric": i}, step=i)

    # Sleep to let some batches go through
    time.sleep(0.6)

    # Log more metrics
    for i in range(100, 200):
        trackio.log({"metric": i}, step=i)

    # Finish immediately without waiting
    trackio.finish()

    # Give a small buffer for final processing
    time.sleep(1)

    # Verify all logs were saved
    from trackio.sqlite_storage import SQLiteStorage

    metrics = SQLiteStorage.get_metrics(project_name, run_name)

    # Check that we have all 200 logs
    assert len(metrics) == 200, f"Expected 200 logs, but found {len(metrics)}"

    # Verify they're in order
    for i, metric_entry in enumerate(metrics):
        assert metric_entry["metric"] == i, (
            f"Expected metric={i}, got {metric_entry['metric']}"
        )
        assert metric_entry["step"] == i, (
            f"Expected step={i}, got {metric_entry['step']}"
        )

    print("✓ Successfully handled bulk logging with interruption")


def test_mixed_size_batches():
    """Test that different sized log payloads are handled correctly in batches."""
    project_name = "test_mixed_batches"
    run_name = "mixed_batch_run"

    # Initialize a new run
    run = trackio.init(project=project_name, name=run_name)

    # Log metrics with varying sizes
    for i in range(100):
        if i % 10 == 0:
            # Every 10th log has many metrics
            metrics = {f"metric_{j}": i * j for j in range(10)}
        else:
            # Regular logs have just one metric
            metrics = {"value": i}

        trackio.log(metrics, step=i)

    # Finish the run
    trackio.finish()

    # Give a small buffer for final processing
    time.sleep(1)

    # Verify all logs were saved
    from trackio.sqlite_storage import SQLiteStorage

    metrics = SQLiteStorage.get_metrics(project_name, run_name)

    # Check that we have all 100 logs
    assert len(metrics) == 100, f"Expected 100 logs, but found {len(metrics)}"

    # Verify the content
    for i, metric_entry in enumerate(metrics):
        if i % 10 == 0:
            # Check multi-metric entries
            for j in range(10):
                assert f"metric_{j}" in metric_entry, f"Missing metric_{j} in entry {i}"
                assert metric_entry[f"metric_{j}"] == i * j
        else:
            # Check single-metric entries
            assert metric_entry["value"] == i, (
                f"Expected value={i}, got {metric_entry['value']}"
            )

        assert metric_entry["step"] == i, (
            f"Expected step={i}, got {metric_entry['step']}"
        )

    print("✓ Successfully handled mixed-size batches")


if __name__ == "__main__":
    test_rapid_bulk_logging()
    test_bulk_logging_with_interruption()
    test_mixed_size_batches()
