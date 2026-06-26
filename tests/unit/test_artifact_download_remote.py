import hashlib
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from trackio.artifact import Artifact
from trackio.typehints import Sha256Digest


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


def test_download_fetches_missing_blob_from_remote(temp_dir, tmp_path, fake_httpx):
    payload = b"weights"
    digest = hashlib.sha256(payload).hexdigest()
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


def test_download_builds_remote_url_with_canonical_project(
    temp_dir, tmp_path, fake_httpx
):
    payload = b"weights"
    digest = hashlib.sha256(payload).hexdigest()
    art = _hydrated_remote_artifact(
        "a/b",
        "m",
        0,
        [{"path": "w.bin", "digest": Sha256Digest(digest), "size": len(payload)}],
        {"space_id": "user/space", "server_base_url": None},
    )
    fake_httpx[f"https://user-space.hf.space/artifact_blob/ab/{digest}"] = (
        _FakeStreamResponse(200, payload)
    )

    out = art.download(tmp_path / "dl")
    assert (Path(out) / "w.bin").read_bytes() == payload

    cas = Path(temp_dir) / "artifacts" / "ab" / "blobs" / "sha256" / digest[:2] / digest
    assert cas.is_file()


def test_download_with_all_blobs_local_does_not_hit_network(
    temp_dir, tmp_path, fake_httpx, stage_blob
):
    payload = b"already-here"
    digest, _ = stage_blob("p", payload)
    art = _hydrated_remote_artifact(
        "p",
        "m",
        0,
        [{"path": "w.bin", "digest": Sha256Digest(digest), "size": len(payload)}],
        {"space_id": "user/space", "server_base_url": None},
    )
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


def test_download_without_remote_source_raises_file_not_found(temp_dir, tmp_path):
    """No `_remote_source` → original local-only `FileNotFoundError`."""
    art = Artifact(name="m", type="model")
    art._hydrate_from_db(
        project="p",
        version=0,
        aliases=[],
        manifest=[{"path": "w.bin", "digest": Sha256Digest("a" * 64), "size": 1}],
        manifest_digest=Sha256Digest("0" * 64),
        size_bytes=1,
    )
    with pytest.raises(FileNotFoundError, match="not available locally or remotely"):
        art.download(tmp_path / "dl")


def _capture_stream_headers(monkeypatch, payload):
    """Patch httpx.stream to record the url and headers it was called with."""
    captured: dict = {}

    def _stream(method, url, **kwargs):
        captured["url"] = url
        captured["headers"] = dict(kwargs.get("headers") or {})
        return _FakeStreamResponse(200, payload)

    import httpx

    monkeypatch.setattr(httpx, "stream", _stream)
    return captured


def test_download_sends_hf_auth_header_for_space(temp_dir, tmp_path, monkeypatch):
    """A Space-backed artifact authenticates the blob fetch with the HF token,
    so blobs on a private Space are reachable."""
    payload = b"private-weights"
    digest = hashlib.sha256(payload).hexdigest()
    art = _hydrated_remote_artifact(
        "p",
        "m",
        0,
        [{"path": "w.bin", "digest": Sha256Digest(digest), "size": len(payload)}],
        {"space_id": "user/space", "server_base_url": None, "write_token": None},
    )
    monkeypatch.setattr("trackio.artifact.get_token", lambda: "hf_faketoken")
    captured = _capture_stream_headers(monkeypatch, payload)

    out = art.download(tmp_path / "dl")
    assert (Path(out) / "w.bin").read_bytes() == payload
    assert "Bearer hf_faketoken" in captured["headers"].values()


def test_download_sends_write_token_for_self_hosted(temp_dir, tmp_path, monkeypatch):
    """A self-hosted artifact authenticates the blob fetch with the write token
    and resolves the blob URL against the configured server base URL."""
    payload = b"weights"
    digest = hashlib.sha256(payload).hexdigest()
    art = _hydrated_remote_artifact(
        "p",
        "m",
        0,
        [{"path": "w.bin", "digest": Sha256Digest(digest), "size": len(payload)}],
        {
            "space_id": None,
            "server_base_url": "https://my-server.example/",
            "write_token": "wt-secret",
        },
    )
    captured = _capture_stream_headers(monkeypatch, payload)

    out = art.download(tmp_path / "dl")
    assert (Path(out) / "w.bin").read_bytes() == payload
    assert captured["url"] == f"https://my-server.example/artifact_blob/p/{digest}"
    assert captured["headers"].get("x-trackio-write-token") == "wt-secret"


def test_artifact_blob_endpoint_serves_blob(temp_dir, monkeypatch, stage_blob):
    """Smoke test the asgi handler directly (no real HTTP)."""
    import asyncio

    from trackio import server
    from trackio.asgi_app import artifact_blob_handler

    payload = b"server-side-bytes"
    digest, _ = stage_blob("p", payload)
    monkeypatch.setattr(server, "assert_can_stage_upload", lambda request: None)

    request = MagicMock()
    request.path_params = {"project": "p", "digest": digest}

    response = asyncio.run(artifact_blob_handler(request))
    assert response.status_code == 200
    assert Path(response.path).read_bytes() == payload


def test_artifact_blob_endpoint_requires_auth(temp_dir, stage_blob):
    import asyncio

    from trackio.asgi_app import artifact_blob_handler

    payload = b"server-side-bytes"
    digest, _ = stage_blob("p", payload)

    request = MagicMock()
    request.path_params = {"project": "p", "digest": digest}
    request.headers = {}
    request.query_params = {}

    response = asyncio.run(artifact_blob_handler(request))
    assert response.status_code == 403


@pytest.mark.parametrize(
    "path_params",
    [
        {"project": "p", "digest": "../../etc/passwd"},
        {"project": "../etc", "digest": "a" * 64},
    ],
)
def test_artifact_blob_endpoint_rejects_invalid_input(temp_dir, monkeypatch, path_params):
    import asyncio

    from trackio import server
    from trackio.asgi_app import artifact_blob_handler

    monkeypatch.setattr(server, "assert_can_stage_upload", lambda request: None)

    request = MagicMock()
    request.path_params = path_params
    response = asyncio.run(artifact_blob_handler(request))
    assert response.status_code == 404


def test_artifact_blob_endpoint_404_when_missing(temp_dir, monkeypatch):
    import asyncio

    from trackio import server
    from trackio.asgi_app import artifact_blob_handler

    monkeypatch.setattr(server, "assert_can_stage_upload", lambda request: None)

    request = MagicMock()
    request.path_params = {"project": "p", "digest": "f" * 64}
    response = asyncio.run(artifact_blob_handler(request))
    assert response.status_code == 404
