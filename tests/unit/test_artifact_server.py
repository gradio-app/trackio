import hashlib
import re
from pathlib import Path
from unittest.mock import MagicMock, Mock

import pytest

from trackio import server
from trackio.exceptions import TrackioAPIError
from trackio.sqlite_storage import SQLiteStorage
from trackio.utils import canonical_project_name


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


def test_artifact_log_validates_digests_before_writing(temp_dir, auth_bypassed):
    bogus_digest = "0" * 64
    with pytest.raises(TrackioAPIError, match="not on server"):
        _log_artifact(
            auth_bypassed,
            manifest=[{"path": "x", "digest": bogus_digest, "size": 1}],
            name="my-model",
        )
    assert SQLiteStorage.get_artifact_manifest("p", "my-model", None) is None


@pytest.mark.parametrize(
    "manifest, kwargs, match",
    [
        (
            [{"path": "x", "digest": "../secret", "size": 1}],
            {"name": "my-model"},
            "Invalid sha256",
        ),
        ("VALID", {"name": "bad name!"}, "must match"),
        ("VALID", {"type": ""}, "type must be a non-empty string"),
        ([], {}, "non-empty list"),
        ([], {"project": 123}, "Invalid project"),
    ],
)
def test_artifact_log_rejects_invalid_input(
    auth_bypassed, stage_blob, manifest, kwargs, match
):
    if manifest == "VALID":
        payload = b"payload"
        digest, _ = stage_blob("p", payload)
        manifest = [{"path": "w.bin", "digest": digest, "size": len(payload)}]
    with pytest.raises(TrackioAPIError, match=match):
        _log_artifact(auth_bypassed, manifest, **kwargs)


def test_artifact_log_rejects_traversal_manifest_paths(auth_bypassed, stage_blob):
    payload = b"payload"
    digest, _ = stage_blob("p", payload)
    for bad in ("../escape", "/abs/path", "a/../b"):
        with pytest.raises(TrackioAPIError, match="Invalid artifact path"):
            _log_artifact(
                auth_bypassed,
                [{"path": bad, "digest": digest, "size": len(payload)}],
            )


def test_artifact_log_rejects_prefix_collision_manifest(auth_bypassed, stage_blob):
    file_payload = b"file-payload"
    child_payload = b"child-payload"
    d1, _ = stage_blob("p", file_payload)
    d2, _ = stage_blob("p", child_payload)
    with pytest.raises(TrackioAPIError, match="collides with"):
        _log_artifact(
            auth_bypassed,
            manifest=[
                {"path": "sub", "digest": d1, "size": len(file_payload)},
                {"path": "sub/x", "digest": d2, "size": len(child_payload)},
            ],
        )


def test_artifact_log_rejects_invalid_manifest_entries(auth_bypassed, stage_blob):
    digest, _ = stage_blob("p", b"payload")

    def _log(manifest):
        _log_artifact(auth_bypassed, manifest)

    for bad in (
        [{"path": "w.bin", "digest": digest}],
        [{"path": "w.bin", "digest": digest, "size": -1}],
        [{"path": "w.bin", "digest": digest, "size": "5"}],
    ):
        with pytest.raises(TrackioAPIError, match="invalid size"):
            _log(bad)

    with pytest.raises(TrackioAPIError, match="Invalid artifact manifest entry"):
        _log(["not-a-dict"])


def test_artifact_log_rejects_bad_aliases(auth_bypassed, stage_blob):
    payload = b"payload"
    digest, _ = stage_blob("p", payload)
    manifest = [{"path": "w.bin", "digest": digest, "size": len(payload)}]
    with pytest.raises(TrackioAPIError, match="must be a list"):
        _log_artifact(auth_bypassed, manifest, aliases="prod")
    with pytest.raises(TrackioAPIError, match="non-empty string"):
        _log_artifact(auth_bypassed, manifest, aliases=[""])
    with pytest.raises(TrackioAPIError, match="reserved for version pointers"):
        _log_artifact(auth_bypassed, manifest, aliases=["v3"])


def test_artifact_endpoints_accept_names_init_and_log_accept(auth_bypassed, stage_blob):
    project = "my experiment"
    canonical = canonical_project_name(project)
    assert canonical == "myexperiment"
    assert SQLiteStorage.get_project_db_filename(project) == f"{canonical}.db"

    payload = b"weights"
    digest, _ = stage_blob(canonical, payload)

    assert server.check_artifact_blobs(auth_bypassed, project, [digest])["present"] == [
        digest
    ]

    _log_artifact(
        auth_bypassed,
        manifest=[{"path": "w.bin", "digest": digest, "size": len(payload)}],
        project=project,
        run_name="train",
    )

    assert server.get_artifact_manifest(project, "m", "latest") is not None
    assert server.get_artifact_manifest(canonical, "m", "latest") is not None


def test_file_route_never_serves_artifact_blobs(stage_blob):
    """Artifact blobs must only be reachable through the authenticated
    /artifact_blob route, never the generic unauthenticated /file route -- even
    if the artifacts directory is mistakenly listed as an allowed file root."""
    from starlette.testclient import TestClient

    from trackio import utils
    from trackio.asgi_app import create_trackio_starlette_app

    _, blob = stage_blob("p", b"secret-model-weights")
    app = create_trackio_starlette_app(
        [], {}, allowed_file_roots=[utils.MEDIA_DIR, utils.ARTIFACTS_DIR]
    )
    client = TestClient(app)

    resp = client.get("/file", params={"path": str(blob)})
    assert resp.status_code == 404
    assert b"secret-model-weights" not in resp.content


def test_get_artifact_manifest_shape(auth_bypassed, stage_blob):
    payload = b"x"
    digest, _ = stage_blob("p", payload)
    _log_artifact(
        auth_bypassed,
        manifest=[{"path": "x", "digest": digest, "size": len(payload)}],
        aliases=["best"],
    )

    record = server.get_artifact_manifest("p", "m", "latest")
    assert record is not None
    assert record["version"] == 0
    assert sorted(record["aliases"]) == ["best", "latest"]
    assert record["manifest"][0]["digest"] == digest
    assert "version_id" in record


def test_get_artifact_manifest_returns_none_on_miss(temp_dir):
    assert server.get_artifact_manifest("p", "missing", "latest") is None


def test_log_artifact_use_inserts_input_lineage(temp_dir, auth_bypassed, stage_blob):
    payload = b"x"
    digest, _ = stage_blob("p", payload)
    result = _log_artifact(
        auth_bypassed,
        manifest=[{"path": "x", "digest": digest, "size": len(payload)}],
        run_name="producer",
        run_id="prod-id",
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


def test_validate_project_name_neutralizes_unsafe_input():
    for raw in [
        "../etc",
        "a/b",
        ".",
        "..",
        "a\\b",
        "proj\n",
        "a\x00b",
        "my experiment",
    ]:
        result = server._validate_project_name(raw)
        assert result == canonical_project_name(raw)
        assert re.fullmatch(r"[A-Za-z0-9_-]+", result)
    assert server._validate_project_name("my-proj_1") == "my-proj_1"


def test_validate_project_name_strips_dots_to_db_stem():
    """Dotted names collapse to the same stem get_project_db_filename uses, so a
    project's artifacts and metrics resolve to one on-disk identity."""
    for raw in ["my.model", "bert.base", "exp.v2", "a.b.c"]:
        expected = canonical_project_name(raw)
        assert server._validate_project_name(raw) == expected
        assert SQLiteStorage.get_project_db_filename(raw) == f"{expected}.db"


def test_validate_project_name_rejects_non_string():
    for bad in [None, 123, ["p"], b"p"]:
        with pytest.raises(TrackioAPIError, match="Invalid project"):
            server._validate_project_name(bad)


def test_artifact_blob_endpoint_serves_blob(temp_dir, monkeypatch, stage_blob):
    """Smoke test the asgi handler directly (no real HTTP)."""
    import asyncio

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
def test_artifact_blob_endpoint_rejects_invalid_input(
    temp_dir, monkeypatch, path_params
):
    import asyncio

    from trackio.asgi_app import artifact_blob_handler

    monkeypatch.setattr(server, "assert_can_stage_upload", lambda request: None)

    request = MagicMock()
    request.path_params = path_params
    response = asyncio.run(artifact_blob_handler(request))
    assert response.status_code == 404


def test_artifact_blob_endpoint_404_when_missing(temp_dir, monkeypatch):
    import asyncio

    from trackio.asgi_app import artifact_blob_handler

    monkeypatch.setattr(server, "assert_can_stage_upload", lambda request: None)

    request = MagicMock()
    request.path_params = {"project": "p", "digest": "f" * 64}
    response = asyncio.run(artifact_blob_handler(request))
    assert response.status_code == 404
