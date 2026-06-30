import hashlib
from pathlib import Path
from unittest.mock import Mock

import pytest

from trackio import server
from trackio.exceptions import TrackioAPIError
from trackio.sqlite_storage import SQLiteStorage


def _write_src(tmp_path, name, payload):
    p = tmp_path / name
    p.write_bytes(payload)
    return p


@pytest.fixture
def auth_bypassed(monkeypatch):
    """Monkeypatch `assert_can_write_metrics` to a no-op and return a Mock Request."""
    monkeypatch.setattr(server, "assert_can_write_metrics", lambda req, tok: None)
    return Mock()


@pytest.fixture
def upload_consume_passthrough(monkeypatch):
    """Bypass the temp-file state-machine: `uploaded_file["path"]` IS the path."""
    monkeypatch.setattr(
        server, "consume_uploaded_temp_file", lambda req, fd: Path(fd["path"])
    )
    monkeypatch.setattr(server, "cleanup_uploaded_temp_file", lambda p: None)


def _log_artifact(request, manifest, **overrides):
    kwargs = {
        "request": request,
        "project": "p",
        "name": "m",
        "type": "model",
        "description": None,
        "metadata": None,
        "manifest": manifest,
        "aliases": None,
        "run_name": "r",
        "run_id": "rid",
        "hf_token": None,
    }
    kwargs.update(overrides)
    return server.artifact_log(**kwargs)


def test_check_artifact_blobs_returns_subset_on_disk(auth_bypassed, stage_blob):
    d_a, _ = stage_blob("p", b"alpha")
    d_b, _ = stage_blob("p", b"beta")
    d_absent = "c" * 64
    result = server.check_artifact_blobs(auth_bypassed, "p", [d_a, d_b, d_absent])
    assert set(result["present"]) == {d_a, d_b}


def test_check_artifact_blobs_rejects_invalid_digest(auth_bypassed):
    for bad in ["../secret.txt", "abc", "G" * 64]:
        with pytest.raises(TrackioAPIError, match="Invalid sha256"):
            server.check_artifact_blobs(auth_bypassed, "p", [bad])


def test_bulk_upload_artifact_blob_happy_path(
    temp_dir, tmp_path, auth_bypassed, upload_consume_passthrough
):
    payload = b"weights" * 100
    digest = hashlib.sha256(payload).hexdigest()
    src = _write_src(tmp_path, "blob", payload)

    server.bulk_upload_artifact_blob(
        request=auth_bypassed,
        project="p",
        uploads=[
            {"project": "p", "digest": digest, "uploaded_file": {"path": str(src)}}
        ],
        hf_token=None,
    )
    target = (
        Path(temp_dir) / "artifacts" / "p" / "blobs" / "sha256" / digest[:2] / digest
    )
    assert target.is_file()
    assert target.read_bytes() == payload


def test_bulk_upload_artifact_blob_digest_mismatch(
    temp_dir, tmp_path, auth_bypassed, upload_consume_passthrough
):
    payload = b"actual"
    claimed = hashlib.sha256(b"different").hexdigest()
    src = _write_src(tmp_path, "blob", payload)

    with pytest.raises(TrackioAPIError, match="Digest mismatch"):
        server.bulk_upload_artifact_blob(
            request=auth_bypassed,
            project="p",
            uploads=[
                {
                    "project": "p",
                    "digest": claimed,
                    "uploaded_file": {"path": str(src)},
                }
            ],
            hf_token=None,
        )
    target = (
        Path(temp_dir) / "artifacts" / "p" / "blobs" / "sha256" / claimed[:2] / claimed
    )
    assert not target.exists()
    blobs_dir = Path(temp_dir) / "artifacts" / "p" / "blobs"
    partials = [p for p in blobs_dir.rglob("*.partial.*") if p.is_file()]
    assert partials == []


def test_bulk_upload_artifact_blob_large_payload(
    temp_dir, tmp_path, auth_bypassed, upload_consume_passthrough
):
    payload = b"x" * (4 * 1024 * 1024)
    digest = hashlib.sha256(payload).hexdigest()
    src = _write_src(tmp_path, "blob", payload)

    server.bulk_upload_artifact_blob(
        request=auth_bypassed,
        project="p",
        uploads=[
            {"project": "p", "digest": digest, "uploaded_file": {"path": str(src)}}
        ],
        hf_token=None,
    )
    target = (
        Path(temp_dir) / "artifacts" / "p" / "blobs" / "sha256" / digest[:2] / digest
    )
    assert target.is_file()
    assert target.stat().st_size == len(payload)


def test_bulk_upload_artifact_blob_skips_existing(
    tmp_path, auth_bypassed, upload_consume_passthrough, stage_blob
):
    payload = b"hello"
    digest, target = stage_blob("p", payload)
    original_mtime = target.stat().st_mtime_ns

    src = _write_src(tmp_path, "blob", payload)
    server.bulk_upload_artifact_blob(
        request=auth_bypassed,
        project="p",
        uploads=[
            {"project": "p", "digest": digest, "uploaded_file": {"path": str(src)}}
        ],
        hf_token=None,
    )
    assert target.stat().st_mtime_ns == original_mtime


def test_bulk_upload_artifact_blob_rejects_path_traversal_digest(
    tmp_path, auth_bypassed, upload_consume_passthrough
):
    src = _write_src(tmp_path, "blob", b"x")
    with pytest.raises(TrackioAPIError, match="Invalid sha256"):
        server.bulk_upload_artifact_blob(
            request=auth_bypassed,
            project="p",
            uploads=[
                {
                    "project": "p",
                    "digest": "../../etc/passwd",
                    "uploaded_file": {"path": str(src)},
                }
            ],
            hf_token=None,
        )


def test_artifact_log_happy_path(temp_dir, auth_bypassed, stage_blob):
    payload = b"weights"
    digest, _ = stage_blob("p", payload)

    result = _log_artifact(
        auth_bypassed,
        manifest=[{"path": "w.bin", "digest": digest, "size": len(payload)}],
        name="my-model",
        description="d",
        metadata={"acc": 0.9},
        aliases=["best"],
        run_name="producer",
        run_id="run-id-1",
    )
    assert result["version"] == 0
    assert sorted(result["aliases"]) == ["best", "latest"]
    assert SQLiteStorage.get_artifact_manifest("p", "my-model", "v1") is None
    assert (
        len(SQLiteStorage.get_run_artifacts("p", "producer", "run-id-1")["output"]) == 1
    )
