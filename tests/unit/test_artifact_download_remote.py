"""Phase 12 — remote fallback for Artifact.download().

Tests the consumer-side fetch when a blob is missing locally. Mocks `httpx`
at the artifact module level so we don't need a real server.
"""

import hashlib
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import trackio
from trackio import artifact as artifact_mod
from trackio.artifact import Artifact
from trackio.typehints import Sha256Digest


def _stage_blob_on_disk(temp_dir, project, payload):
    """Helper: place a blob in the local CAS as if produced by Phase 4."""
    digest = hashlib.sha256(payload).hexdigest()
    base = Path(temp_dir) / "artifacts" / project / "blobs" / "sha256"
    blob = base / digest[:2] / digest
    blob.parent.mkdir(parents=True, exist_ok=True)
    blob.write_bytes(payload)
    return digest, len(payload)


def _hydrated_remote_artifact(project, name, version, entries, remote_source):
    a = Artifact(name=name, type="model")
    a._hydrate_from_db(
        project=project,
        version=version,
        aliases=["latest"],
        manifest=entries,
        manifest_digest=Sha256Digest("0" * 64),
        size_bytes=sum(e["size"] for e in entries),
    )
    a._remote_source = remote_source
    return a


class _FakeStreamResponse:
    """Mimics the context manager returned by httpx.stream()."""

    def __init__(self, status_code: int, body: bytes = b""):
        self.status_code = status_code
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def iter_bytes(self, chunk_size: int = 64 * 1024):
        # Yield in two chunks so we exercise the multi-chunk loop.
        mid = len(self._body) // 2
        if mid:
            yield self._body[:mid]
        yield self._body[mid:]


@pytest.fixture
def fake_httpx(monkeypatch):
    """Replace httpx.stream with a controllable factory.

    Returns a dict the test populates: `{(url): _FakeStreamResponse(...)}`.
    """
    routes: dict[str, _FakeStreamResponse] = {}

    def _stream(method, url, **kwargs):
        if method != "GET":
            raise AssertionError(f"unexpected method: {method}")
        if url not in routes:
            return _FakeStreamResponse(404)
        return routes[url]

    import httpx

    monkeypatch.setattr(httpx, "stream", _stream)
    return routes


# --- Phase 12 tests ---


def test_download_fetches_missing_blob_from_remote(temp_dir, tmp_path, fake_httpx):
    payload = b"weights"
    digest = hashlib.sha256(payload).hexdigest()
    # NOTE: blob NOT placed in local CAS — must come from remote.
    art = _hydrated_remote_artifact(
        "p",
        "m",
        0,
        [{"path": "w.bin", "digest": Sha256Digest(digest), "size": len(payload)}],
        {"space_id": "user/space", "server_base_url": None},
    )
    fake_httpx[f"https://user-space.hf.space/artifact_blob/p/{digest}"] = (
        _FakeStreamResponse(200, payload)
    )

    out = art.download(tmp_path / "dl")
    assert (Path(out) / "w.bin").read_bytes() == payload

    cas = Path(temp_dir) / "artifacts" / "p" / "blobs" / "sha256" / digest[:2] / digest
    assert cas.is_file()
    assert cas.read_bytes() == payload


def test_download_with_all_blobs_local_does_not_hit_network(
    temp_dir, tmp_path, fake_httpx
):
    payload = b"already-here"
    digest, size = _stage_blob_on_disk(temp_dir, "p", payload)
    art = _hydrated_remote_artifact(
        "p",
        "m",
        0,
        [{"path": "w.bin", "digest": Sha256Digest(digest), "size": size}],
        {"space_id": "user/space", "server_base_url": None},
    )
    # fake_httpx has no routes — if the code tries to fetch, it gets 404.
    out = art.download(tmp_path / "dl")
    assert (Path(out) / "w.bin").read_bytes() == payload


def test_download_404_raises_file_not_found(temp_dir, tmp_path, fake_httpx):
    digest = "a" * 64
    art = _hydrated_remote_artifact(
        "p",
        "m",
        0,
        [{"path": "w.bin", "digest": Sha256Digest(digest), "size": 5}],
        {"space_id": "user/space", "server_base_url": None},
    )
    # No route registered → fake server returns 404.
    with pytest.raises(FileNotFoundError, match="not available on remote"):
        art.download(tmp_path / "dl")


def test_download_digest_mismatch_raises_runtime_error(temp_dir, tmp_path, fake_httpx):
    claimed = hashlib.sha256(b"expected").hexdigest()
    art = _hydrated_remote_artifact(
        "p",
        "m",
        0,
        [{"path": "w.bin", "digest": Sha256Digest(claimed), "size": 1}],
        {"space_id": "user/space", "server_base_url": None},
    )
    fake_httpx[f"https://user-space.hf.space/artifact_blob/p/{claimed}"] = (
        _FakeStreamResponse(200, b"tampered")
    )

    with pytest.raises(ValueError, match="Digest mismatch"):
        art.download(tmp_path / "dl")

    target = (
        Path(temp_dir) / "artifacts" / "p" / "blobs" / "sha256" / claimed[:2] / claimed
    )
    assert not target.exists()


def test_download_without_remote_source_keeps_phase5_error(temp_dir, tmp_path):
    """Regression for Phase 5: no _remote_source → original FileNotFoundError."""
    art = Artifact(name="m", type="model")
    art._hydrate_from_db(
        project="p",
        version=0,
        aliases=[],
        manifest=[{"path": "w.bin", "digest": Sha256Digest("a" * 64), "size": 1}],
        manifest_digest=Sha256Digest("0" * 64),
        size_bytes=1,
    )
    # _remote_source intentionally left None.
    with pytest.raises(FileNotFoundError, match="not available locally or remotely"):
        art.download(tmp_path / "dl")


def test_download_with_server_base_url_resolves_correctly(
    temp_dir, tmp_path, fake_httpx
):
    payload = b"x"
    digest = hashlib.sha256(payload).hexdigest()
    art = _hydrated_remote_artifact(
        "p",
        "m",
        0,
        [{"path": "w.bin", "digest": Sha256Digest(digest), "size": 1}],
        {"space_id": None, "server_base_url": "https://my-server.example/"},
    )
    fake_httpx[f"https://my-server.example/artifact_blob/p/{digest}"] = (
        _FakeStreamResponse(200, payload)
    )

    out = art.download(tmp_path / "dl")
    assert (Path(out) / "w.bin").read_bytes() == payload


def test_artifact_blob_endpoint_serves_blob(temp_dir, monkeypatch):
    """Smoke test the asgi handler directly (no real HTTP)."""
    import asyncio

    from trackio.asgi_app import artifact_blob_handler

    payload = b"server-side-bytes"
    digest, _ = _stage_blob_on_disk(temp_dir, "p", payload)

    request = MagicMock()
    request.path_params = {"project": "p", "digest": digest}

    response = asyncio.run(artifact_blob_handler(request))
    assert response.status_code == 200
    # FileResponse holds the path internally
    assert Path(response.path).read_bytes() == payload


def test_artifact_blob_endpoint_rejects_path_traversal_digest(temp_dir):
    import asyncio

    from trackio.asgi_app import artifact_blob_handler

    request = MagicMock()
    request.path_params = {"project": "p", "digest": "../../etc/passwd"}
    response = asyncio.run(artifact_blob_handler(request))
    assert response.status_code == 404


def test_artifact_blob_endpoint_rejects_invalid_project(temp_dir):
    import asyncio

    from trackio.asgi_app import artifact_blob_handler

    request = MagicMock()
    request.path_params = {"project": "../etc", "digest": "a" * 64}
    response = asyncio.run(artifact_blob_handler(request))
    assert response.status_code == 404


def test_artifact_blob_endpoint_404_when_missing(temp_dir):
    import asyncio

    from trackio.asgi_app import artifact_blob_handler

    request = MagicMock()
    request.path_params = {"project": "p", "digest": "f" * 64}
    response = asyncio.run(artifact_blob_handler(request))
    assert response.status_code == 404
