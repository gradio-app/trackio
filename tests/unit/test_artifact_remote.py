"""Run remote-mode `log_artifact` / `use_artifact` + sender routing.

Unit-level tests with a mocked `self._client`. The full producer→Space→consumer
round-trip via a real RemoteClient is covered by `test_artifact_remote_e2e.py`.
"""

import hashlib
import threading
from unittest.mock import MagicMock

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


# --- log_artifact remote flow ---


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
    assert logged.version == 0
    assert "latest" in logged.aliases
    assert "best" in logged.aliases
    assert logged.project == "rp"
    assert logged._remote_source == {
        "space_id": "user/space",
        "server_base_url": None,
    }
    run._client = None
    trackio.finish()


# --- use_artifact remote flow ---


def test_remote_use_artifact_sequence(temp_dir, monkeypatch):
    run, client, _ = _make_remote_run(monkeypatch, name="consumer")
    art = run.use_artifact("m:latest")

    call_names = [c.kwargs.get("api_name") for c in client.predict.call_args_list]
    assert call_names == ["/get_artifact_manifest", "/log_artifact_use"]

    log_use_call = client.predict.call_args_list[1]
    assert log_use_call.kwargs["version_id"] == 7
    assert log_use_call.kwargs["run_name"] == "consumer"

    assert art.version == 0
    assert art._remote_source == {
        "space_id": "user/space",
        "server_base_url": None,
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
    assert art.version == 0
    run._client = None
    trackio.finish()


# --- sender kind routing ---


def test_sender_routes_artifact_blob_kind_to_correct_endpoint(temp_dir, tmp_path):
    blob_path = tmp_path / "blob.bin"
    blob_path.write_bytes(b"x")

    SQLiteStorage.enqueue_artifact_blob_upload(
        project="p",
        space_id="sp",
        digest="a" * 64,
        local_blob_path=str(blob_path),
        run_name="r",
        run_id="rid",
    )

    buffered = SQLiteStorage.get_pending_uploads("p")
    assert buffered is not None
    assert buffered["uploads"][0]["kind"] == "artifact_blob"
    assert buffered["uploads"][0]["digest"] == "a" * 64


def test_sender_routes_media_kind_to_correct_endpoint(temp_dir, tmp_path):
    media_path = tmp_path / "img.png"
    media_path.write_bytes(b"png-bytes")

    SQLiteStorage.add_pending_upload(
        project="p",
        space_id="sp",
        run_id="rid",
        run_name="r",
        step=0,
        file_path=str(media_path),
        relative_path="img.png",
    )
    buffered = SQLiteStorage.get_pending_uploads("p")
    assert buffered is not None
    assert buffered["uploads"][0]["kind"] == "media"


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
    SQLiteStorage.enqueue_artifact_blob_upload(
        project="p",
        space_id="sp",
        digest="b" * 64,
        local_blob_path=str(blob),
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


# --- lineage idempotency ---


def test_lineage_unique_index_prevents_duplicates(temp_dir):
    aid = SQLiteStorage.create_or_get_artifact("p", "m", "model", None)
    vid, _, _ = SQLiteStorage.insert_artifact_version(
        "p", aid, [{"path": "a", "digest": "1", "size": 1}], None, None, "r"
    )
    SQLiteStorage.insert_run_artifact_link("p", "r", "rid-1", vid, "input")
    SQLiteStorage.insert_run_artifact_link("p", "r", "rid-1", vid, "input")
    lineage = SQLiteStorage.get_run_artifacts("p", "r", "rid-1")
    assert len(lineage["input"]) == 1


# --- _wait_for_client_ready ---


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
