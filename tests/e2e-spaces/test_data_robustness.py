import secrets
import time

from gradio_client import Client

import trackio
from trackio.sqlite_storage import SQLiteStorage


def _wait_for_client(run, timeout=60):
    """Wait for the Run's background client to connect to the Space."""
    deadline = time.time() + timeout
    while run._client is None:
        if time.time() > deadline:
            raise TimeoutError("Client did not connect within timeout")
        time.sleep(0.1)


def test_data_not_lost_on_transient_network_error(test_space_id, temp_dir):
    """
    When predict() fails once due to a transient network error and then
    recovers, the failed batch should be retried and all data should
    eventually reach the Space.
    """
    project_name = f"test_transient_{secrets.token_urlsafe(8)}"
    run_name = "test_run"

    run = trackio.init(project=project_name, name=run_name, space_id=test_space_id)
    _wait_for_client(run)

    original_predict = run._client.predict
    call_count = [0]

    def wrapped_predict(*args, **kwargs):
        call_count[0] += 1
        if kwargs.get("api_name") == "/bulk_log" and call_count[0] <= 1:
            raise Exception("ReadTimeout: The read operation timed out")
        return original_predict(*args, **kwargs)

    run._client.predict = wrapped_predict

    trackio.log({"loss": 0.5})
    trackio.log({"loss": 0.3})
    time.sleep(5)
    trackio.finish()

    verify_client = Client(test_space_id)
    summary = verify_client.predict(
        project=project_name, run=run_name, api_name="/get_run_summary"
    )
    assert summary["num_logs"] == 2


def test_failed_data_persisted_locally(test_space_id, temp_dir):
    """
    When predict() permanently fails (Space unreachable), data should be
    persisted to the local SQLite database as a fallback buffer so it is
    not lost.
    """
    project_name = f"test_persist_{secrets.token_urlsafe(8)}"
    run_name = "test_run"

    run = trackio.init(project=project_name, name=run_name, space_id=test_space_id)
    _wait_for_client(run)

    original_predict = run._client.predict

    def always_fail_writes(*args, **kwargs):
        if kwargs.get("api_name") in ("/bulk_log", "/bulk_log_system"):
            raise Exception("Connection refused")
        return original_predict(*args, **kwargs)

    run._client.predict = always_fail_writes

    trackio.log({"loss": 0.5})
    trackio.log({"loss": 0.3})
    time.sleep(3)
    trackio.finish()

    local_logs = SQLiteStorage.get_logs(project=project_name, run=run_name)
    assert len(local_logs) >= 2, (
        f"Expected at least 2 logs persisted in local SQLite, got {len(local_logs)}"
    )


def test_data_delivered_after_batch_sender_crash(test_space_id, temp_dir):
    """
    After a network error crashes the batch sender, subsequently-logged
    data should still be delivered to the Space (either by retrying within
    the same thread or by restarting the sender).
    """
    project_name = f"test_crash_{secrets.token_urlsafe(8)}"
    run_name = "test_run"

    run = trackio.init(project=project_name, name=run_name, space_id=test_space_id)
    _wait_for_client(run)

    original_predict = run._client.predict
    call_count = [0]

    def wrapped_predict(*args, **kwargs):
        call_count[0] += 1
        if kwargs.get("api_name") == "/bulk_log" and call_count[0] == 1:
            raise Exception("ReadTimeout: The read operation timed out")
        return original_predict(*args, **kwargs)

    run._client.predict = wrapped_predict

    trackio.log({"loss": 0.5})
    time.sleep(3)

    trackio.log({"loss": 0.3})
    trackio.log({"loss": 0.1})
    time.sleep(5)
    trackio.finish()

    verify_client = Client(test_space_id)
    summary = verify_client.predict(
        project=project_name, run=run_name, api_name="/get_run_summary"
    )
    assert summary["num_logs"] >= 2, (
        f"Expected at least 2 logs on Space after recovery, got {summary['num_logs']}"
    )


def test_local_buffer_flushed_after_recovery(test_space_id, temp_dir):
    """
    When the connection recovers after several failures, data that was
    persisted in the local SQLite fallback buffer should be flushed to the
    Space and cleaned up from the local database.
    """
    project_name = f"test_flush_{secrets.token_urlsafe(8)}"
    run_name = "test_run"

    run = trackio.init(project=project_name, name=run_name, space_id=test_space_id)
    _wait_for_client(run)

    original_predict = run._client.predict
    call_count = [0]

    def wrapped_predict(*args, **kwargs):
        call_count[0] += 1
        if kwargs.get("api_name") == "/bulk_log" and call_count[0] <= 3:
            raise Exception("Connection refused")
        return original_predict(*args, **kwargs)

    run._client.predict = wrapped_predict

    trackio.log({"loss": 0.5, "epoch": 1})
    trackio.log({"loss": 0.3, "epoch": 2})
    time.sleep(2)
    trackio.log({"loss": 0.1, "epoch": 3})
    time.sleep(10)
    trackio.finish()

    verify_client = Client(test_space_id)
    summary = verify_client.predict(
        project=project_name, run=run_name, api_name="/get_run_summary"
    )
    assert summary["num_logs"] == 3, (
        f"Expected all 3 logs on Space after recovery, got {summary['num_logs']}"
    )

    local_logs = SQLiteStorage.get_logs(project=project_name, run=run_name)
    assert len(local_logs) == 0, (
        f"Expected local buffer to be empty after flush, but found {len(local_logs)} rows"
    )
