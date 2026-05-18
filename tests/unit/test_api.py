from unittest.mock import patch

import pytest

import trackio
import trackio.context_vars as context_vars
from trackio.api import Api, Run
from trackio.remote_client import RemoteClient


class _FakeRemoteClient:
    """Stand-in for RemoteClient. Returns canned responses keyed by api_name."""

    def __init__(self, *_args, **_kwargs):
        self.calls = []
        self._responses = {
            "/get_runs_for_project": [
                {
                    "id": "rid-1",
                    "name": "run1",
                    "created_at": "2026-01-01",
                    "finished_at": None,
                },
            ],
            "/get_run_status": "finished",
            "/get_run_summary": {"config": {"lr": 0.01}},
            "/get_final_metrics_for_run": {
                "loss": {"value": 0.5, "step": 9},
                "acc": {"value": 0.9, "step": 9},
            },
            "/get_metrics_for_run": ["loss", "acc"],
            "/get_logs": [{"step": 0, "loss": 1.0}, {"step": 1, "loss": 0.5}],
            "/get_metric_values": [
                {"step": 0, "value": 1.0},
                {"step": 1, "value": 0.5},
            ],
            "/get_alerts": [{"title": "NaN!", "level": "error", "alert_id": "a-1"}],
        }

    def predict(self, *args, api_name, **kwargs):
        self.calls.append((api_name, args, kwargs))
        return self._responses.get(api_name)


def _reset_context():
    context_vars.current_run.set(None)
    context_vars.current_project.set(None)
    context_vars.current_server.set(None)
    context_vars.current_space_id.set(None)


def test_remote_api_runs_and_run_methods(temp_dir):
    """Every Run read method dispatches through the client to the right endpoint."""
    with patch("trackio.api.RemoteClient", _FakeRemoteClient):
        api = Api(space="fake/space", hf_token="tok")
        assert isinstance(api._client, _FakeRemoteClient)

        runs = api.runs("proj")
        assert len(runs) == 1
        run = runs[0]
        assert run.name == "run1"
        assert run.id == "rid-1"

        assert run.status == "finished"
        assert run.config == {"lr": 0.01}
        assert run.final_metrics() == {"loss": 0.5, "acc": 0.9}
        assert run.metrics() == ["loss", "acc"]
        assert run.history() == [{"step": 0, "loss": 1.0}, {"step": 1, "loss": 0.5}]
        assert run.history(metric="loss") == [
            {"step": 0, "value": 1.0},
            {"step": 1, "value": 0.5},
        ]
        assert run.alerts() == [{"title": "NaN!", "level": "error", "alert_id": "a-1"}]

        endpoints_hit = [c[0] for c in api._client.calls]
        for expected in [
            "/get_runs_for_project",
            "/get_run_status",
            "/get_run_summary",
            "/get_final_metrics_for_run",
            "/get_metrics_for_run",
            "/get_logs",
            "/get_metric_values",
            "/get_alerts",
        ]:
            assert expected in endpoints_hit, f"{expected} was not exercised"


def test_remote_api_alerts(temp_dir):
    """Api.alerts() goes through the client when remote."""
    with patch("trackio.api.RemoteClient", _FakeRemoteClient):
        api = Api(space="fake/space")
        alerts = api.alerts("proj")
        assert alerts == [{"title": "NaN!", "level": "error", "alert_id": "a-1"}]


def test_remote_run_write_ops_raise(temp_dir):
    """delete / move / rename are not supported on remote runs."""
    fake = _FakeRemoteClient()
    run = Run("proj", "r1", run_id="rid-1", _client=fake)
    for method, args in (("delete", ()), ("move", ("new",)), ("rename", ("new",))):
        with pytest.raises(NotImplementedError, match="remote"):
            getattr(run, method)(*args)


def test_local_api_remains_unchanged(temp_dir):
    """Api() with no args still uses SQLiteStorage directly — no client instantiated."""
    trackio.init(project="local_api", name="r1")
    trackio.log({"loss": 0.5}, step=0)
    trackio.finish()

    api = Api()
    assert api._client is None
    runs = list(api.runs("local_api"))
    assert len(runs) == 1
    run = runs[0]
    assert run.name == "r1"
    assert run.status == "finished"
    fm = run.final_metrics()
    assert abs(fm["loss"] - 0.5) < 1e-6


def test_remote_api_http_roundtrip(temp_dir):
    """End-to-end: spin up a local dashboard, seed a project locally, then read it back
    through Api(space=url) which exercises the actual HTTP transport and every new
    server endpoint added in Batch E."""
    trackio.init(project="http_api", name="r1", config={"lr": 0.01})
    for step in range(3):
        trackio.log({"loss": 1.0 - step * 0.3, "acc": step * 0.2}, step=step)
    trackio.alert("done", text="ok", level=trackio.AlertLevel.INFO)
    trackio.finish()

    app, url, _, _ = trackio.show(block_thread=False, open_browser=False)
    try:
        _reset_context()
        api = Api(space=url)
        assert isinstance(api._client, RemoteClient)

        runs = api.runs("http_api")
        assert len(runs) == 1
        run = runs[0]
        assert run.name == "r1"
        assert run.status == "finished"
        assert run.config is not None
        assert run.config.get("lr") == 0.01

        assert sorted(run.metrics()) == ["acc", "loss"]

        fm = run.final_metrics()
        assert abs(fm["loss"] - (1.0 - 2 * 0.3)) < 1e-6
        assert abs(fm["acc"] - (2 * 0.2)) < 1e-6

        full = run.history()
        assert len(full) == 3

        loss_history = run.history(metric="loss")
        assert len(loss_history) == 3
        assert all("value" in entry for entry in loss_history)

        alerts = run.alerts()
        assert any(a.get("title") == "done" for a in alerts)
    finally:
        _reset_context()
        app.close()
