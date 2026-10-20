import importlib

import huggingface_hub
import pytest

import trackio
from trackio import bump as bump_module
from trackio.bump import BumpError

hub_httpx = importlib.import_module(
    "httpx2" if int(huggingface_hub.__version__.split(".")[0]) >= 2 else "httpx"
)


def test_check_bumpable_refuses_unsafe_versions(monkeypatch):
    monkeypatch.setattr(trackio, "__version__", "0.41.0")
    assert bump_module._check_bumpable("u/s", "0.21.0") == "0.21.0"
    assert bump_module._check_bumpable("u/s", "0.41.0") == "0.41.0"
    with pytest.raises(BumpError, match="older than 0.21.0"):
        bump_module._check_bumpable("u/s", "0.20.0")
    with pytest.raises(BumpError, match="newer than the local"):
        bump_module._check_bumpable("u/s", "0.42.0")
    with pytest.raises(BumpError, match="Could not determine"):
        bump_module._check_bumpable("u/s", None)
    with pytest.raises(BumpError, match="not a final release"):
        bump_module._check_bumpable("u/s", "0.39.0rc1")
    monkeypatch.setattr(trackio, "__version__", "1.0.0rc1")
    with pytest.raises(BumpError, match="not a final"):
        bump_module._check_bumpable("u/s", "1.0.0")


@pytest.mark.parametrize(
    "argv",
    [
        ["trackio", "bump", "u/s"],
        ["trackio", "bump", "--space", "u/s"],
        ["trackio", "--space", "u/s", "bump"],
        ["trackio", "bump", "u/s", "--space", "u/s"],
    ],
)
def test_cli_bump_accepts_positional_or_space_flag(monkeypatch, argv):
    from trackio import cli

    calls = []
    monkeypatch.setattr(cli, "bump", lambda *a, **k: calls.append((a, k)))
    monkeypatch.setattr("sys.argv", argv)
    cli.main()
    assert calls == [(("u/s",), {"new_space_id": None, "new_bucket_id": None})]


def test_wait_for_stage_retries_hub_transport_errors(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import Mock

    monkeypatch.setattr(bump_module.time, "sleep", lambda _: None)
    api = Mock()
    api.get_space_runtime.side_effect = [
        hub_httpx.ConnectError("temporary connection failure"),
        SimpleNamespace(stage="RUNNING"),
    ]
    bump_module._wait_for_stage("username/trackio", frozenset({"RUNNING"}), 30, api)
    assert api.get_space_runtime.call_count == 2
