import importlib
import threading
from collections import defaultdict
from unittest.mock import Mock

import pytest

trackio_run = importlib.import_module("trackio.run")
storage = importlib.import_module("trackio.sqlite_storage")


class SlowClient:
    def __init__(self, api_name, *, block_call=1, fail_call=None):
        self.api_name = api_name
        self.block_call = block_call
        self.fail_call = fail_call
        self.calls = 0
        self.entered = threading.Event()
        self.release = threading.Event()
        self.received = defaultdict(list)

    def predict(self, *, api_name, **kwargs):
        if api_name == self.api_name:
            self.calls += 1
            if self.calls == self.block_call:
                self.entered.set()
                if not self.release.wait(10):
                    raise TimeoutError("Test did not release the slow server")
            if self.calls == self.fail_call:
                raise ConnectionError("Simulated unavailable server")
        self.received[api_name].extend(
            kwargs.get("logs", kwargs.get("uploads", kwargs.get("alerts", [])))
        )


@pytest.fixture
def run_factory(monkeypatch, temp_dir):
    monkeypatch.setattr(trackio_run, "BATCH_SEND_INTERVAL", 0.01)
    monkeypatch.setattr(trackio_run.Run, "_get_username", lambda self: None)
    monkeypatch.setenv("TRACKIO_STORAGE_MODE", "sqlite")
    monkeypatch.delenv("TRACKIO_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("TRACKIO_WEBHOOK_MIN_LEVEL", raising=False)
    runs = []

    def create(client, *, bucket_id=None):
        run = trackio_run.Run(
            url="http://trackio.invalid",
            project="nonblocking-test",
            client=client,
            name="regression",
            server_base_url=None if bucket_id else "http://trackio.invalid",
            space_id="user/space" if bucket_id else None,
            bucket_id=bucket_id,
            initial_last_step=0,
            config={"test": True},
        )
        runs.append((run, client))
        return run

    yield create

    for run, client in runs:
        client.release.set()
        run._stop_flag.set()
        run._client_thread.join(timeout=5)
        assert not run._client_thread.is_alive()


def enqueue(run, api_name, upload, step):
    {
        "/bulk_log": lambda: run.log({"loss": 1 / step}, step=step),
        "/bulk_log_system": lambda: run.log_system({"cpu": step}),
        "/bulk_upload_media": lambda: run._queue_upload(upload, step),
        "/bulk_alert": lambda: run.alert("Test alert", step=step),
    }[api_name]()


APIS = ("/bulk_log", "/bulk_log_system", "/bulk_upload_media", "/bulk_alert")


@pytest.mark.parametrize("slow_api", APIS)
def test_logging_continues_during_slow_upload(run_factory, tmp_path, slow_api):
    client = SlowClient(slow_api)
    run = run_factory(client)
    upload = tmp_path / "media.txt"
    upload.write_text("test media")
    enqueue(run, slow_api, upload, 1)
    assert client.entered.wait(2)
    logged = threading.Event()

    def produce():
        for api_name in APIS:
            enqueue(run, api_name, upload, 2)
        logged.set()

    producer = threading.Thread(target=produce, daemon=True)
    producer.start()
    try:
        assert logged.wait(1), "Logging waited for the slow server"
        assert not client.release.is_set()
    finally:
        client.release.set()
        producer.join(timeout=5)
        run.finish()

    for api_name in APIS:
        assert len(client.received[api_name]) == (2 if api_name == slow_api else 1)
    metrics = client.received["/bulk_log"]
    assert metrics[-1]["metrics"] == {"loss": 0.5}
    assert metrics[0]["config"]["test"] is True
    assert all(entry["run_id"] == run.id for entry in metrics)
    assert len({entry["log_id"] for entry in metrics}) == len(metrics)


def test_logging_continues_during_buffered_retry(run_factory):
    client = SlowClient("/bulk_log", block_call=2, fail_call=1)
    run = run_factory(client)
    run.log({"loss": 1.0}, step=1)
    assert client.entered.wait(2)
    pending = storage.SQLiteStorage.get_pending_logs(run.project)
    assert pending is not None
    logged = threading.Event()

    def produce():
        run.log({"loss": 0.5}, step=2)
        logged.set()

    producer = threading.Thread(target=produce, daemon=True)
    producer.start()
    try:
        assert logged.wait(1), "Logging waited for a buffered retry"
    finally:
        client.release.set()
        producer.join(timeout=5)
        run.finish()

    assert [entry["step"] for entry in client.received["/bulk_log"]] == [1, 2]
    assert not storage.SQLiteStorage.has_pending_data(run.project)


def assert_recoverable_batches(run, slow_api):
    logs = storage.SQLiteStorage.get_logs(run.project, run.name)
    assert [entry["step"] for entry in logs] == (
        [1, 2] if slow_api == "/bulk_log" else [2]
    )
    assert logs[-1]["loss"] == 0.5
    assert storage.SQLiteStorage.get_run_config(run.project, run.name)["test"] is True

    system_logs = storage.SQLiteStorage.get_system_logs(run.project, run.name)
    assert sorted(entry["cpu"] for entry in system_logs) == (
        [1, 2] if slow_api == "/bulk_log_system" else [2]
    )

    uploads = storage.SQLiteStorage.get_pending_uploads(run.project)
    assert uploads is not None
    assert sorted(entry["step"] for entry in uploads["uploads"]) == (
        [1, 2] if slow_api == "/bulk_upload_media" else [2]
    )

    alerts = storage.SQLiteStorage.get_alerts(run.project)
    assert sorted(entry["step"] for entry in alerts) == (
        [1, 2] if slow_api == "/bulk_alert" else [2]
    )


@pytest.mark.parametrize("slow_api", APIS)
@pytest.mark.parametrize("storage_mode", ["sqlite", "jsonl"])
@pytest.mark.parametrize("late_failure", [False, True])
def test_finish_preserves_inflight_and_queued_batches(
    run_factory, monkeypatch, tmp_path, slow_api, storage_mode, late_failure
):
    monkeypatch.setenv("TRACKIO_STORAGE_MODE", storage_mode)
    bucket_write = Mock(side_effect=AssertionError("Shutdown must save locally"))
    monkeypatch.setattr(
        trackio_run.fragments.FragmentWriter, "write_to_bucket", bucket_write
    )
    monkeypatch.setattr(
        trackio_run.fragments, "upload_media_files_to_bucket", bucket_write
    )
    monkeypatch.setattr(trackio_run.Run, "_drain_pending_to_bucket", bucket_write)
    client = SlowClient(slow_api, fail_call=1 if late_failure else None)
    run = run_factory(client, bucket_id="user/bucket")
    upload = tmp_path / "media.txt"
    upload.write_text("test media")
    enqueue(run, slow_api, upload, 1)
    assert client.entered.wait(2)
    for api_name in APIS:
        enqueue(run, api_name, upload, 2)
    actual_join = run._client_thread.join
    join_timeouts = []

    def short_join(timeout=None):
        join_timeouts.append(timeout)
        actual_join(timeout=0.01)

    monkeypatch.setattr(run._client_thread, "join", short_join)
    finished = threading.Event()

    def finish():
        run.finish()
        finished.set()

    finisher = threading.Thread(target=finish, daemon=True)
    finisher.start()
    try:
        assert finished.wait(1), "finish() blocked outside its bounded join"
        assert join_timeouts == [30]
        assert not client.release.is_set()
        run.finish()
        assert join_timeouts == [30]
        bucket_write.assert_not_called()
        if storage_mode == "jsonl":
            assert trackio_run.fragments.import_inbox_dir() == (
                3 if slow_api == "/bulk_upload_media" else 4
            )
        assert_recoverable_batches(run, slow_api)
    finally:
        client.release.set()
        finisher.join(timeout=5)
        actual_join(timeout=5)

    assert not run._client_thread.is_alive()
    run.finish()
    assert join_timeouts == [30]
    bucket_write.assert_not_called()
    assert_recoverable_batches(run, slow_api)
