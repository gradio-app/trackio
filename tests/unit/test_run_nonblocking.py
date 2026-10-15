import importlib
import threading

import pytest

from trackio.sqlite_storage import SQLiteStorage

trackio_run = importlib.import_module("trackio.run")


class SlowClient:
    def __init__(self, *, fail_first=False):
        self.fail_first = fail_first
        self.calls = 0
        self.entered = threading.Event()
        self.release = threading.Event()
        self.received = []

    def predict(self, *, api_name, **kwargs):
        if api_name != "/bulk_log":
            return
        self.calls += 1
        if self.fail_first and self.calls == 1:
            raise ConnectionError("Server unavailable")
        self.entered.set()
        if not self.release.wait(5):
            raise TimeoutError("Test did not release the server")
        self.received.extend(kwargs["logs"])


@pytest.fixture
def run_factory(monkeypatch, temp_dir):
    monkeypatch.setattr(trackio_run, "BATCH_SEND_INTERVAL", 0.01)
    monkeypatch.setattr(trackio_run.Run, "_get_username", lambda self: None)
    monkeypatch.setenv("TRACKIO_STORAGE_MODE", "sqlite")
    runs = []

    def create(client):
        run = trackio_run.Run(
            url="http://trackio.invalid",
            project="nonblocking-test",
            client=client,
            name="regression",
            server_base_url="http://trackio.invalid",
            initial_last_step=0,
        )
        runs.append((run, client))
        return run

    yield create

    for run, client in runs:
        client.release.set()
        run.finish()
        run._client_thread.join(timeout=5)
        assert not run._client_thread.is_alive()


def log_while_request_is_blocked(run, client):
    logged = threading.Event()

    def produce():
        run.log({"loss": 0.5}, step=2)
        logged.set()

    producer = threading.Thread(target=produce, daemon=True)
    producer.start()
    try:
        assert logged.wait(1), "Logging waited for the slow server"
    finally:
        client.release.set()
        producer.join(timeout=5)


def test_logging_continues_during_slow_request(run_factory):
    client = SlowClient()
    run = run_factory(client)
    run.log({"loss": 1.0}, step=1)
    assert client.entered.wait(2)
    log_while_request_is_blocked(run, client)
    run.finish()
    assert [entry["metrics"] for entry in client.received] == [
        {"loss": 1.0},
        {"loss": 0.5},
    ]


def test_logging_continues_during_buffered_retry(run_factory):
    client = SlowClient(fail_first=True)
    run = run_factory(client)
    run.log({"loss": 1.0}, step=1)
    assert client.entered.wait(2)
    assert SQLiteStorage.has_pending_data(run.project)
    log_while_request_is_blocked(run, client)
    run.finish()
    assert [entry["metrics"] for entry in client.received] == [
        {"loss": 1.0},
        {"loss": 0.5},
    ]
    assert not SQLiteStorage.has_pending_data(run.project)
