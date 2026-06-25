"""Run remote-mode `log_artifact` / `use_artifact` + sender routing.

Unit-level tests with a mocked `self._client`. The full producer→Space→consumer
round-trip via a real RemoteClient is covered by `test_artifact_remote_e2e.py`.
"""

import hashlib
import threading
from unittest.mock import MagicMock

import httpx
import pytest

import trackio
from trackio.artifact import Artifact
from trackio.sqlite_storage import SQLiteStorage


def _payload_digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _make_remote_run(monkeypatch, project="rp", name="producer", existing_blobs=()):
    """Construct a Run in local mode then flip to remote with a mocked _client.

    Sidesteps trackio.init's HF auth dance — we don't want a real Space
    connection in unit tests.
    """
    monkeypatch.delenv("TRACKIO_SPACE_ID", raising=False)
    monkeypatch.delenv("TRACKIO_SERVER_URL", raising=False)
    run = trackio.init(project=project, name=name)
    run._is_local = False
    run._space_id = "user/space"
    run._server_base_url = None
    run._remote_storage_key = "user/space"

    mock_client = MagicMock()
    present = list(existing_blobs)

    def _predict(api_name, **kwargs):
        if api_name == "/check_artifact_blobs":
            return {"present": [d for d in kwargs["digests"] if d in present]}
        if api_name == "/bulk_upload_artifact_blob":
            for entry in kwargs["uploads"]:
                present.append(entry["digest"])
            return None
        if api_name == "/bulk_upload_media":
            return None
        if api_name == "/artifact_log":
            return {
                "version": 0,
                "aliases": ["latest"] + list(kwargs.get("aliases") or []),
                "manifest": kwargs["manifest"],
                "manifest_digest": "x" * 64,
                "size_bytes": sum(e["size"] for e in kwargs["manifest"]),
                "name": kwargs["name"],
                "type": kwargs["type"],
                "description": kwargs.get("description"),
                "metadata": kwargs.get("metadata"),
                "version_id": 1,
            }
        if api_name == "/get_artifact_manifest":
            return {
                "version": 0,
                "aliases": ["latest"],
                "manifest": [{"path": "w.bin", "digest": "a" * 64, "size": 1}],
                "manifest_digest": "y" * 64,
                "size_bytes": 1,
                "name": kwargs["name"],
                "type": "model",
                "description": None,
                "metadata": None,
                "version_id": 7,
            }
        if api_name == "/log_artifact_use":
            return None
        raise AssertionError(f"unexpected api_name: {api_name}")

    mock_client.predict.side_effect = _predict
    run._client = mock_client
    return run, mock_client, present


def _write(tmp_path, name, payload):
    p = tmp_path / name
    p.write_bytes(payload)
    return p


def test_remote_log_artifact_calls_endpoints_in_order(temp_dir, tmp_path, monkeypatch):
    weights = _write(tmp_path, "w.bin", b"data")
    run, client, _ = _make_remote_run(monkeypatch)
    art = Artifact(name="m", type="model")
    art.add_file(weights)
    run.log_artifact(art, aliases=["best"])

    call_names = [c.kwargs.get("api_name") for c in client.predict.call_args_list]
    assert call_names == [
        "/check_artifact_blobs",
        "/bulk_upload_artifact_blob",
        "/artifact_log",
    ]
    run._client = None
    trackio.finish()


def test_remote_log_artifact_skips_upload_for_present_blobs(
    temp_dir, tmp_path, monkeypatch
):
    weights = _write(tmp_path, "w.bin", b"present")
    digest = _payload_digest(b"present")
    run, client, _ = _make_remote_run(monkeypatch, existing_blobs=[digest])
    art = Artifact(name="m", type="model")
    art.add_file(weights)
    run.log_artifact(art)

    call_names = [c.kwargs.get("api_name") for c in client.predict.call_args_list]
    assert "/bulk_upload_artifact_blob" not in call_names
    assert call_names == ["/check_artifact_blobs", "/artifact_log"]
    run._client = None
    trackio.finish()


def test_remote_log_artifact_hydrates_returned_artifact(
    temp_dir, tmp_path, monkeypatch
):
    weights = _write(tmp_path, "w.bin", b"data")
    run, _client, _ = _make_remote_run(monkeypatch)
    art = Artifact(name="m", type="model")
    art.add_file(weights)
    logged = run.log_artifact(art, aliases=["best"])

    assert logged is art
    assert logged.version == "v0"
    assert "latest" in logged.aliases
    assert "best" in logged.aliases
    assert logged.project == "rp"
    assert logged._remote_source == {
        "space_id": "user/space",
        "server_base_url": None,
        "write_token": None,
    }
    run._client = None
    trackio.finish()


def _inject_artifact_log_failures(client, errors):
    """Make the next len(errors) /artifact_log calls raise errors[i], in order."""
    base = client.predict.side_effect
    state = {"i": 0}

    def _wrapped(api_name, **kwargs):
        if api_name == "/artifact_log" and state["i"] < len(errors):
            err = errors[state["i"]]
            state["i"] += 1
            raise err
        return base(api_name, **kwargs)

    client.predict.side_effect = _wrapped


def _artifact_log_call_count(client):
    return sum(
        c.kwargs.get("api_name") == "/artifact_log"
        for c in client.predict.call_args_list
    )


def test_is_transient_remote_error_classifies_errors():
    from trackio.remote_client import is_transient_remote_error

    req = httpx.Request("POST", "http://x/api/artifact_log")
    err_503 = httpx.HTTPStatusError(
        "503", request=req, response=httpx.Response(503, request=req)
    )
    err_400 = httpx.HTTPStatusError(
        "400", request=req, response=httpx.Response(400, request=req)
    )
    assert is_transient_remote_error(err_503) is True
    assert is_transient_remote_error(err_400) is False
    assert is_transient_remote_error(httpx.ConnectError("x")) is True
    assert is_transient_remote_error(ConnectionError("x")) is True
    assert is_transient_remote_error(RuntimeError("x")) is False


def test_remote_log_artifact_retries_transient_artifact_log(
    temp_dir, tmp_path, monkeypatch
):
    monkeypatch.setattr("trackio.run.time.sleep", lambda *_a, **_k: None)
    weights = _write(tmp_path, "w.bin", b"data")
    run, client, _ = _make_remote_run(monkeypatch)
    _inject_artifact_log_failures(
        client, [httpx.ConnectError("boom"), httpx.ConnectError("boom")]
    )
    art = Artifact(name="m", type="model")
    art.add_file(weights)
    logged = run.log_artifact(art)

    assert logged.version == "v0"
    assert _artifact_log_call_count(client) == 3
    upload_calls = sum(
        c.kwargs.get("api_name") == "/bulk_upload_artifact_blob"
        for c in client.predict.call_args_list
    )
    assert upload_calls == 1
    run._client = None
    trackio.finish()


def test_remote_log_artifact_does_not_retry_permanent_error(
    temp_dir, tmp_path, monkeypatch
):
    monkeypatch.setattr("trackio.run.time.sleep", lambda *_a, **_k: None)
    weights = _write(tmp_path, "w.bin", b"data")
    run, client, _ = _make_remote_run(monkeypatch)
    _inject_artifact_log_failures(client, [RuntimeError("Invalid project name")] * 5)
    art = Artifact(name="m", type="model")
    art.add_file(weights)
    with pytest.raises(RuntimeError, match="Invalid project name"):
        run.log_artifact(art)
    assert _artifact_log_call_count(client) == 1
    run._client = None
    trackio.finish()


def test_remote_log_artifact_reraises_after_exhausting_retries(
    temp_dir, tmp_path, monkeypatch
):
    monkeypatch.setattr("trackio.run.time.sleep", lambda *_a, **_k: None)
    weights = _write(tmp_path, "w.bin", b"data")
    run, client, _ = _make_remote_run(monkeypatch)
    _inject_artifact_log_failures(client, [httpx.ConnectError("down")] * 10)
    art = Artifact(name="m", type="model")
    art.add_file(weights)
    with pytest.raises(httpx.ConnectError):
        run.log_artifact(art)
    assert _artifact_log_call_count(client) == 4
    run._client = None
    trackio.finish()


def test_remote_use_artifact_sequence(temp_dir, monkeypatch):
    run, client, _ = _make_remote_run(monkeypatch, name="consumer")
    art = run.use_artifact("m:latest")

    call_names = [c.kwargs.get("api_name") for c in client.predict.call_args_list]
    assert call_names == ["/get_artifact_manifest", "/log_artifact_use"]

    log_use_call = client.predict.call_args_list[1]
    assert log_use_call.kwargs["version_id"] == 7
    assert log_use_call.kwargs["run_name"] == "consumer"

    assert art.version == "v0"
    assert art._remote_source == {
        "space_id": "user/space",
        "server_base_url": None,
        "write_token": None,
    }
    run._client = None
    trackio.finish()


def test_remote_use_artifact_not_found_raises(temp_dir, monkeypatch):
    run, client, _ = _make_remote_run(monkeypatch)
    client.predict.side_effect = lambda api_name, **kw: (
        None if api_name == "/get_artifact_manifest" else None
    )
    with pytest.raises(ValueError, match="not found"):
        run.use_artifact("missing:latest")
    run._client = None
    trackio.finish()


def test_remote_use_artifact_lineage_failure_is_nonfatal(temp_dir, monkeypatch):
    run, client, _ = _make_remote_run(monkeypatch)
    original = client.predict.side_effect

    def _side_effect(api_name, **kw):
        if api_name == "/log_artifact_use":
            raise RuntimeError("network down")
        return original(api_name, **kw)

    client.predict.side_effect = _side_effect
    art = run.use_artifact("m:latest")
    assert art.version == "v0"
    run._client = None
    trackio.finish()


def test_artifact_rpcs_hold_client_lock(temp_dir, tmp_path, monkeypatch):
    weights = _write(tmp_path, "w.bin", b"data")
    run, client, _ = _make_remote_run(monkeypatch)

    base = client.predict.side_effect
    locked_during = {}

    def _checking_predict(api_name, **kwargs):
        acquired = run._client_lock.acquire(blocking=False)
        if acquired:
            run._client_lock.release()
        locked_during[api_name] = not acquired
        return base(api_name, **kwargs)

    client.predict.side_effect = _checking_predict

    art = Artifact(name="m", type="model")
    art.add_file(weights)
    run.log_artifact(art)
    run.use_artifact("m:latest")

    for api in (
        "/check_artifact_blobs",
        "/artifact_log",
        "/get_artifact_manifest",
        "/log_artifact_use",
    ):
        assert locked_during.get(api) is True, f"{api} called without _client_lock held"

    run._client = None
    trackio.finish()


def test_send_pending_uploads_routes_both_kinds(temp_dir, tmp_path, monkeypatch):
    media = tmp_path / "img.png"
    media.write_bytes(b"img")
    blob = tmp_path / "blob.bin"
    blob.write_bytes(b"weights")

    SQLiteStorage.add_pending_upload(
        project="p",
        space_id="sp",
        run_id="rid",
        run_name="r",
        step=0,
        file_path=str(media),
        relative_path="img.png",
    )
    SQLiteStorage.enqueue_artifact_blob_uploads(
        project="p",
        space_id="sp",
        blobs=[("b" * 64, str(blob))],
        run_name="r",
        run_id="rid",
    )

    run, client, _ = _make_remote_run(monkeypatch, project="p", name="r")
    buffered = SQLiteStorage.get_pending_uploads("p")
    run._send_pending_uploads_to_server(buffered)

    api_calls = [c.kwargs.get("api_name") for c in client.predict.call_args_list]
    assert "/bulk_upload_media" in api_calls
    assert "/bulk_upload_artifact_blob" in api_calls
    run._client = None
    trackio.finish()


def test_send_pending_uploads_partial_failure_keeps_unsent_rows(
    temp_dir, tmp_path, monkeypatch
):
    media = tmp_path / "img.png"
    media.write_bytes(b"img")
    blob = tmp_path / "blob.bin"
    blob.write_bytes(b"weights")

    SQLiteStorage.add_pending_upload(
        project="p",
        space_id="sp",
        run_id="rid",
        run_name="r",
        step=0,
        file_path=str(media),
        relative_path="img.png",
    )
    SQLiteStorage.enqueue_artifact_blob_uploads(
        project="p",
        space_id="sp",
        blobs=[("b" * 64, str(blob))],
        run_name="r",
        run_id="rid",
    )

    run, client, _ = _make_remote_run(monkeypatch, project="p", name="r")

    def _failing_predict(api_name, **kwargs):
        if api_name == "/bulk_upload_artifact_blob":
            raise RuntimeError("network down")
        return None

    client.predict.side_effect = _failing_predict
    buffered = SQLiteStorage.get_pending_uploads("p")
    with pytest.raises(RuntimeError, match="network down"):
        run._send_pending_uploads_to_server(buffered)

    remaining = SQLiteStorage.get_pending_uploads("p")
    assert remaining is not None
    kinds = [u["kind"] for u in remaining["uploads"]]
    assert kinds == ["artifact_blob"]
    run._client = None
    trackio.finish()


def test_send_pending_uploads_drops_missing_files_with_warning(
    temp_dir, tmp_path, monkeypatch
):
    SQLiteStorage.enqueue_artifact_blob_uploads(
        project="p",
        space_id="sp",
        blobs=[("c" * 64, str(tmp_path / "vanished.bin"))],
        run_name="r",
        run_id="rid",
    )

    run, client, _ = _make_remote_run(monkeypatch, project="p", name="r")
    buffered = SQLiteStorage.get_pending_uploads("p")
    with pytest.warns(UserWarning, match="no longer exist"):
        run._send_pending_uploads_to_server(buffered)

    assert client.predict.call_count == 0
    assert SQLiteStorage.get_pending_uploads("p") is None
    run._client = None
    trackio.finish()


def test_lineage_unique_index_prevents_duplicates(temp_dir):
    aid = SQLiteStorage.create_or_get_artifact("p", "m", "model", None)
    vid, _, _ = SQLiteStorage.insert_artifact_version(
        "p", aid, [{"path": "a", "digest": "1", "size": 1}], None, None, "r"
    )
    SQLiteStorage.insert_run_artifact_link("p", "r", "rid-1", vid, "input")
    SQLiteStorage.insert_run_artifact_link("p", "r", "rid-1", vid, "input")
    lineage = SQLiteStorage.get_run_artifacts("p", "r", "rid-1")
    assert len(lineage["input"]) == 1


def test_wait_for_client_ready_returns_when_set(temp_dir, monkeypatch):
    run = trackio.init(project="rp-wait", name="p")
    run._is_local = False
    run._client = None

    def _set_later():
        import time as _time

        _time.sleep(0.2)
        run._client = MagicMock()

    threading.Thread(target=_set_later, daemon=True).start()
    run._wait_for_client_ready(timeout=2.0)
    assert run._client is not None
    run._client = None
    trackio.finish()


def test_wait_for_client_ready_times_out(temp_dir, monkeypatch):
    run = trackio.init(project="rp-timeout", name="p")
    run._is_local = False
    run._client = None
    with pytest.raises(RuntimeError, match="not ready"):
        run._wait_for_client_ready(timeout=0.3)
    trackio.finish()
