"""Server-side endpoints for the artifact round-trip path.

Read endpoints (no auth) are called directly. Write endpoints take a
Request and call `assert_can_write_metrics`; tests use `Mock()` for the
Request and monkeypatch the auth check (matches the existing trackio
pattern in `test_token_auth.py`).
"""

import hashlib
from pathlib import Path
from unittest.mock import Mock

import pytest

from trackio import server
from trackio.exceptions import TrackioAPIError
from trackio.sqlite_storage import SQLiteStorage


def _stage(temp_dir, project, payload):
    digest = hashlib.sha256(payload).hexdigest()
    base = Path(temp_dir) / "artifacts" / project / "blobs" / "sha256"
    blob = base / digest[:2] / digest
    blob.parent.mkdir(parents=True, exist_ok=True)
    blob.write_bytes(payload)
    return digest, len(payload)


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


# --- /check_artifact_blobs (no-auth read) ---


def test_check_artifact_blobs_returns_subset_on_disk(temp_dir):
    d_a, _ = _stage(temp_dir, "p", b"alpha")
    d_b, _ = _stage(temp_dir, "p", b"beta")
    d_absent = "c" * 64
    result = server.check_artifact_blobs("p", [d_a, d_b, d_absent])
    assert set(result["present"]) == {d_a, d_b}


def test_check_artifact_blobs_rejects_invalid_digest():
    for bad in ["../secret.txt", "abc", "G" * 64]:
        with pytest.raises(TrackioAPIError, match="Invalid sha256"):
            server.check_artifact_blobs("p", [bad])


def test_check_artifact_blobs_rejects_invalid_project():
    with pytest.raises(TrackioAPIError, match="Invalid project"):
        server.check_artifact_blobs("../etc", [])


# --- /bulk_upload_artifact_blob (write) ---


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


def test_bulk_upload_artifact_blob_size_cap_when_opted_in(
    temp_dir, tmp_path, monkeypatch, auth_bypassed, upload_consume_passthrough
):
    monkeypatch.setattr(server.utils, "ARTIFACT_BLOB_MAX_BYTES", 4)
    payload = b"too-big-for-cap"
    digest = hashlib.sha256(payload).hexdigest()
    src = _write_src(tmp_path, "blob", payload)

    with pytest.raises(TrackioAPIError, match="exceeds"):
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
    assert not target.exists()


def test_bulk_upload_artifact_blob_no_cap_by_default(
    temp_dir, tmp_path, monkeypatch, auth_bypassed, upload_consume_passthrough
):
    monkeypatch.setattr(server.utils, "ARTIFACT_BLOB_MAX_BYTES", None)
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
    temp_dir, tmp_path, auth_bypassed, upload_consume_passthrough
):
    payload = b"hello"
    digest, _ = _stage(temp_dir, "p", payload)
    target = (
        Path(temp_dir) / "artifacts" / "p" / "blobs" / "sha256" / digest[:2] / digest
    )
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


# --- /artifact_log (write) ---


def test_artifact_log_happy_path(temp_dir, auth_bypassed):
    payload = b"weights"
    digest, size = _stage(temp_dir, "p", payload)

    result = server.artifact_log(
        request=auth_bypassed,
        project="p",
        name="my-model",
        type="model",
        description="d",
        metadata={"acc": 0.9},
        manifest=[{"path": "w.bin", "digest": digest, "size": size}],
        aliases=["best"],
        run_name="producer",
        run_id="run-id-1",
        hf_token=None,
    )
    assert result["version"] == 0
    assert sorted(result["aliases"]) == ["best", "latest"]
    assert SQLiteStorage.get_artifact_manifest("p", "my-model", "v1") is None
    assert (
        len(SQLiteStorage.get_run_artifacts("p", "producer", "run-id-1")["output"]) == 1
    )


def test_artifact_log_validates_digests_before_writing(temp_dir, auth_bypassed):
    bogus_digest = "0" * 64
    with pytest.raises(TrackioAPIError, match="not on server"):
        server.artifact_log(
            request=auth_bypassed,
            project="p",
            name="my-model",
            type="model",
            description=None,
            metadata=None,
            manifest=[{"path": "x", "digest": bogus_digest, "size": 1}],
            aliases=None,
            run_name="r",
            run_id="rid",
            hf_token=None,
        )
    assert SQLiteStorage.get_artifact_manifest("p", "my-model", None) is None


def test_artifact_log_rejects_invalid_digest_format(temp_dir, auth_bypassed):
    with pytest.raises(TrackioAPIError, match="Invalid sha256"):
        server.artifact_log(
            request=auth_bypassed,
            project="p",
            name="my-model",
            type="model",
            description=None,
            metadata=None,
            manifest=[{"path": "x", "digest": "../secret", "size": 1}],
            aliases=None,
            run_name="r",
            run_id="rid",
            hf_token=None,
        )


def test_artifact_log_rejects_traversal_manifest_paths(temp_dir, auth_bypassed):
    digest, size = _stage(temp_dir, "p", b"payload")
    for bad in ("../escape", "/abs/path", "a/../b"):
        with pytest.raises(TrackioAPIError, match="Invalid artifact path"):
            server.artifact_log(
                auth_bypassed,
                project="p",
                name="m",
                type="model",
                description=None,
                metadata=None,
                manifest=[{"path": bad, "digest": digest, "size": size}],
                aliases=None,
                run_name="r",
                run_id="rid",
                hf_token=None,
            )


def test_artifact_log_rejects_invalid_project(temp_dir, auth_bypassed):
    with pytest.raises(TrackioAPIError, match="Invalid project"):
        server.artifact_log(
            request=auth_bypassed,
            project="../etc",
            name="m",
            type="model",
            description=None,
            metadata=None,
            manifest=[],
            aliases=None,
            run_name="r",
            run_id="rid",
            hf_token=None,
        )


# --- /get_artifact_manifest (no-auth read) ---


def test_get_artifact_manifest_shape(temp_dir, auth_bypassed):
    payload = b"x"
    digest, size = _stage(temp_dir, "p", payload)
    server.artifact_log(
        request=auth_bypassed,
        project="p",
        name="m",
        type="model",
        description=None,
        metadata=None,
        manifest=[{"path": "x", "digest": digest, "size": size}],
        aliases=["best"],
        run_name="r",
        run_id="rid",
        hf_token=None,
    )

    record = server.get_artifact_manifest("p", "m", "latest")
    assert record is not None
    assert record["version"] == 0
    assert sorted(record["aliases"]) == ["best", "latest"]
    assert record["manifest"][0]["digest"] == digest
    assert "version_id" in record


def test_get_artifact_manifest_returns_none_on_miss(temp_dir):
    assert server.get_artifact_manifest("p", "missing", "latest") is None


def test_get_artifact_manifest_rejects_invalid_project():
    with pytest.raises(TrackioAPIError, match="Invalid project"):
        server.get_artifact_manifest("../etc", "m", "latest")


# --- /log_artifact_use (write) ---


def test_log_artifact_use_inserts_input_lineage(temp_dir, auth_bypassed):
    payload = b"x"
    digest, size = _stage(temp_dir, "p", payload)
    result = server.artifact_log(
        request=auth_bypassed,
        project="p",
        name="m",
        type="model",
        description=None,
        metadata=None,
        manifest=[{"path": "x", "digest": digest, "size": size}],
        aliases=None,
        run_name="producer",
        run_id="prod-id",
        hf_token=None,
    )
    record = server.get_artifact_manifest("p", "m", f"v{result['version']}")
    version_id = record["version_id"]

    server.log_artifact_use(
        request=auth_bypassed,
        project="p",
        version_id=version_id,
        run_name="consumer",
        run_id="cons-id",
        hf_token=None,
    )
    lineage = SQLiteStorage.get_run_artifacts("p", "consumer", "cons-id")
    assert len(lineage["input"]) == 1
    assert lineage["input"][0]["version_id"] == version_id


# --- helpers ---


def test_validate_project_name_rejects_traversal():
    for bad in ["../etc", "a/b", ""]:
        with pytest.raises(TrackioAPIError, match="Invalid project"):
            server._validate_project_name(bad)
    assert server._validate_project_name("my-proj_1") == "my-proj_1"
