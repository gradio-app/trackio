import time
from unittest.mock import MagicMock

import trackio
import trackio.context_vars as context_vars
import trackio.server as srv
from trackio import Run
from trackio.remote_client import RemoteClient as Client
from trackio.sqlite_storage import SQLiteStorage


class _FakeRequest:
    """Minimal stand-in for starlette.requests.Request used by server endpoints."""

    def __init__(self, write_token: str = "test"):
        self.headers = {"x-trackio-write-token": write_token}
        self.query_params: dict = {}


def _reset_context():
    context_vars.current_run.set(None)
    context_vars.current_project.set(None)
    context_vars.current_server.set(None)
    context_vars.current_space_id.set(None)


def test_local_run_status_writes_directly_to_sqlite(temp_dir):
    """Local mode: SQLiteStorage receives 'running' inline; no remote client involved."""
    run = trackio.init(project="local_status", name="r1")
    assert (
        SQLiteStorage.get_run_status("local_status", "r1", run_id=run.id) == "running"
    )
    trackio.finish()
    assert (
        SQLiteStorage.get_run_status("local_status", "r1", run_id=run.id) == "finished"
    )


def test_remote_run_creates_no_local_stub(temp_dir):
    """Remote-mode init must not pollute the local SQLite with a stub configs row."""
    fake = MagicMock()
    run = Run(
        url="fake_url",
        project="remote_stub_check",
        client=fake,
        name="r1",
        space_id="user/space",
    )
    run.log({"loss": 1.0})
    time.sleep(0.6)
    run.finish()
    time.sleep(0.6)

    db_path = SQLiteStorage.get_project_db_path("remote_stub_check")
    assert not db_path.exists(), (
        f"Remote-mode run should not have created {db_path}; "
        "this is the B1 local-stub-pollution bug."
    )


def test_remote_run_routes_status_via_client(temp_dir):
    """Mock client should record /set_run_status calls for 'running' and 'finished'."""
    fake = MagicMock()
    run = Run(
        url="fake_url",
        project="remote_status_routing",
        client=fake,
        name="r1",
        space_id="user/space",
    )
    run.log({"loss": 1.0})
    time.sleep(0.6)
    run.finish()
    time.sleep(0.6)

    status_calls = [
        call
        for call in fake.predict.call_args_list
        if call.kwargs.get("api_name") == "/set_run_status"
    ]
    statuses = [call.kwargs.get("status") for call in status_calls]
    assert "running" in statuses
    assert "finished" in statuses


def test_bulk_alert_data_field_propagates(temp_dir):
    """Server-side: B2 fix — data field threads through bulk_alert into SQLite."""
    srv.write_token = "test"
    req = _FakeRequest()
    alerts = [
        {
            "project": "alert_data",
            "run": "r1",
            "run_id": "rid-1",
            "title": "NaN!",
            "text": "loss became NaN",
            "level": "error",
            "step": 5,
            "timestamp": "2026-01-01T00:00:00+00:00",
            "alert_id": "aid-1",
            "data": {"reason": "nan_inf", "metric": "loss"},
        }
    ]
    srv.bulk_alert(req, alerts, hf_token=None)

    rows = SQLiteStorage.get_alerts("alert_data")
    assert len(rows) == 1
    assert rows[0]["data"] == {"reason": "nan_inf", "metric": "loss"}


def test_run_status_routes_via_http(temp_dir):
    """HTTP-roundtrip: a remote-mode run should drive the real /set_run_status
    HTTP endpoint, ending up with status='finished' on the (local) server."""
    app, url, _, full_url = trackio.show(block_thread=False, open_browser=False)
    try:
        _reset_context()
        trackio.init(project="http_status", name="r1", server_url=full_url)
        trackio.log({"loss": 1.0})
        trackio.finish()
        time.sleep(2)

        client = Client(url)
        status = client.predict("http_status", "r1", None, api_name="/get_run_status")
        assert status == "finished"
    finally:
        _reset_context()
        app.close()


def test_alert_data_routes_via_http(temp_dir):
    """HTTP-roundtrip: trackio.alert(data={...}) survives JSON serialization through
    the /bulk_alert endpoint and lands in the stored row."""
    app, url, _, full_url = trackio.show(block_thread=False, open_browser=False)
    try:
        _reset_context()
        trackio.init(project="http_alert", name="r1", server_url=full_url)
        trackio.alert(
            "nan!",
            text="lost",
            level=trackio.AlertLevel.ERROR,
            data={"reason": "nan_inf", "metric": "loss"},
        )
        trackio.finish()
        time.sleep(2)

        client = Client(url)
        alerts = client.predict(
            "http_alert", "r1", None, None, None, api_name="/get_alerts"
        )
        assert any((a.get("data") or {}).get("reason") == "nan_inf" for a in alerts)
    finally:
        _reset_context()
        app.close()
