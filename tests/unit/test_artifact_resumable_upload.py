"""End-to-end coverage for bounded, restart-safe artifact uploads."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from starlette.testclient import TestClient

from trackio import cas, utils
from trackio.asgi_app import create_trackio_starlette_app
from trackio.exceptions import TrackioAPIError
from trackio.remote_client import _TrackioHTTPClient
from trackio.resumable_uploads import expire_sessions


def _digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _init(client: TestClient, *, digest: str, size: int, key: str = "client-key-00000001"):
    response = client.post(
        "/api/artifact-upload/resumable-project",
        json={"digest": digest, "size_bytes": size, "idempotency_key": key},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _put(client: TestClient, upload_id: str, index: int, payload: bytes):
    return client.put(
        f"/api/artifact-upload/resumable-project/{upload_id}/chunks/{index}",
        content=payload,
        headers={"x-trackio-chunk-sha256": _digest(payload)},
    )


def test_resumable_upload_streams_out_of_order_and_survives_app_restart(temp_dir):
    first = b"a" * (8 * 1024 * 1024)
    last = b"tail"
    payload = first + last
    app = create_trackio_starlette_app([], {})
    client = TestClient(app)

    capabilities = client.get("/api/artifact-upload/capabilities")
    assert capabilities.status_code == 200
    assert capabilities.json() == {
        "resumable": True,
        "compatibility_max_bytes": 32 * 1024 * 1024,
        "chunk_size_bytes": 8 * 1024 * 1024,
    }

    session = _init(client, digest=_digest(payload), size=len(payload))
    upload_id = session["upload_id"]
    assert session["chunk_count"] == 2

    response = _put(client, upload_id, 1, last)
    assert response.status_code == 200
    assert response.json()["already_present"] is False

    incomplete = client.post(
        f"/api/artifact-upload/resumable-project/{upload_id}"
    )
    assert incomplete.status_code == 409
    assert "missing chunks: [0]" in incomplete.json()["error"]

    restarted_client = TestClient(create_trackio_starlette_app([], {}))
    status = restarted_client.get(
        f"/api/artifact-upload/resumable-project/{upload_id}"
    )
    assert status.status_code == 200
    assert status.json()["acknowledged_chunks"] == [1]

    response = _put(restarted_client, upload_id, 0, first)
    assert response.status_code == 200
    duplicate = _put(restarted_client, upload_id, 0, first)
    assert duplicate.status_code == 200
    assert duplicate.json()["already_present"] is True

    completed = restarted_client.post(
        f"/api/artifact-upload/resumable-project/{upload_id}"
    )
    assert completed.status_code == 200
    assert completed.json() == {
        "digest": _digest(payload),
        "size_bytes": len(payload),
        "already_present": False,
    }
    assert cas.blob_path("resumable-project", _digest(payload)).read_bytes() == payload

    retried = restarted_client.post(
        f"/api/artifact-upload/resumable-project/{upload_id}"
    )
    assert retried.status_code == 200
    assert retried.json()["already_present"] is True


def test_resumable_upload_rejects_corrupt_chunk_without_acknowledging_it(temp_dir):
    payload = b"expected"
    client = TestClient(create_trackio_starlette_app([], {}))
    session = _init(client, digest=_digest(payload), size=len(payload))
    upload_id = session["upload_id"]

    response = client.put(
        f"/api/artifact-upload/resumable-project/{upload_id}/chunks/0",
        content=payload,
        headers={"x-trackio-chunk-sha256": _digest(b"different")},
    )

    assert response.status_code == 409
    assert "digest mismatch" in response.json()["error"].lower()
    status = client.get(f"/api/artifact-upload/resumable-project/{upload_id}")
    assert status.json()["acknowledged_chunks"] == []
    assert not cas.blob_path("resumable-project", _digest(payload)).exists()


def test_resumable_upload_init_is_idempotent_and_rejects_key_reuse(temp_dir):
    client = TestClient(create_trackio_starlette_app([], {}))
    payload = b"weights"

    first = _init(client, digest=_digest(payload), size=len(payload))
    second = _init(client, digest=_digest(payload), size=len(payload))
    assert second["upload_id"] == first["upload_id"]

    conflict = client.post(
        "/api/artifact-upload/resumable-project",
        json={
            "digest": _digest(b"other"),
            "size_bytes": len(b"other"),
            "idempotency_key": "client-key-00000001",
        },
    )
    assert conflict.status_code == 409
    assert "different artifact blob" in conflict.json()["error"]


def test_resumable_upload_authorizes_every_mutating_and_status_route(temp_dir):
    def authorize(request):
        if request.headers.get("x-trackio-write-token") != "test-token":
            raise TrackioAPIError("Unauthorized")

    client = TestClient(
        create_trackio_starlette_app([], {}, upload_authorizer=authorize)
    )
    payload = b"weights"
    init_url = "/api/artifact-upload/resumable-project"

    assert client.post(
        init_url,
        json={
            "digest": _digest(payload),
            "size_bytes": len(payload),
            "idempotency_key": "client-key-00000001",
        },
    ).status_code == 401
    session = client.post(
        init_url,
        headers={"x-trackio-write-token": "test-token"},
        json={
            "digest": _digest(payload),
            "size_bytes": len(payload),
            "idempotency_key": "client-key-00000001",
        },
    ).json()
    status_url = f"{init_url}/{session['upload_id']}"
    assert client.get(status_url).status_code == 401
    assert client.post(status_url).status_code == 401
    assert client.delete(status_url).status_code == 401


def test_resumable_upload_abort_removes_incomplete_session(temp_dir):
    client = TestClient(create_trackio_starlette_app([], {}))
    payload = b"weights"
    session = _init(client, digest=_digest(payload), size=len(payload))
    status_url = (
        f"/api/artifact-upload/resumable-project/{session['upload_id']}"
    )

    response = client.delete(status_url)

    assert response.status_code == 200
    assert response.json() == {"aborted": True}
    assert client.get(status_url).status_code == 404


def test_resumable_upload_completes_empty_blob(temp_dir):
    client = TestClient(create_trackio_starlette_app([], {}))
    payload = b""
    session = _init(
        client,
        digest=_digest(payload),
        size=0,
        key="client-key-empty-0001",
    )

    completed = client.post(
        f"/api/artifact-upload/resumable-project/{session['upload_id']}"
    )

    assert completed.status_code == 200
    assert completed.json()["size_bytes"] == 0
    assert cas.blob_path("resumable-project", _digest(payload)).read_bytes() == b""


def test_expiry_is_dry_run_by_default_and_never_removes_completed_blob(temp_dir):
    client = TestClient(create_trackio_starlette_app([], {}))
    abandoned_payload = b"abandoned"
    abandoned = _init(
        client,
        digest=_digest(abandoned_payload),
        size=len(abandoned_payload),
        key="client-key-expiry-0001",
    )
    assert _put(client, abandoned["upload_id"], 0, abandoned_payload).status_code == 200

    completed_payload = b"retained"
    completed = _init(
        client,
        digest=_digest(completed_payload),
        size=len(completed_payload),
        key="client-key-expiry-0002",
    )
    assert _put(client, completed["upload_id"], 0, completed_payload).status_code == 200
    assert client.post(
        f"/api/artifact-upload/resumable-project/{completed['upload_id']}"
    ).status_code == 200

    metadata = (
        utils.project_artifacts_dir("resumable-project")
        / "uploads"
        / abandoned["upload_id"]
        / "session.json"
    )
    payload = json.loads(metadata.read_text())
    payload["updated_at"] = (datetime.now(UTC) - timedelta(days=2)).isoformat()
    metadata.write_text(json.dumps(payload))
    cutoff = datetime.now(UTC) - timedelta(days=1)

    dry_run = expire_sessions(
        project="resumable-project",
        older_than=cutoff,
    )
    assert dry_run["dry_run"] is True
    assert dry_run["session_count"] == 1
    assert dry_run["reclaimable_bytes"] > 0
    assert metadata.exists()

    deleted = expire_sessions(
        project="resumable-project",
        older_than=cutoff,
        dry_run=False,
    )
    assert deleted["session_count"] == 1
    assert not metadata.exists()
    assert cas.blob_path(
        "resumable-project",
        _digest(completed_payload),
    ).read_bytes() == completed_payload


def test_large_blob_fails_closed_against_legacy_server(tmp_path, monkeypatch):
    def no_capabilities(url, **kwargs):
        request = httpx.Request("GET", str(url))
        return httpx.Response(404, request=request)

    monkeypatch.setattr(httpx, "get", no_capabilities)
    client = _TrackioHTTPClient("http://legacy.example")
    small = tmp_path / "small.bin"
    small.write_bytes(b"small")
    large = tmp_path / "large.bin"
    with large.open("wb") as handle:
        handle.truncate(32 * 1024 * 1024 + 1)

    assert client.upload_artifact_blob("project", "a" * 64, small) is False
    with pytest.raises(RuntimeError, match="does not support resumable"):
        client.upload_artifact_blob("project", "a" * 64, large)
