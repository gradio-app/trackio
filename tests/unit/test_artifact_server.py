"""Server-side endpoints for the artifact round-trip path.

Read endpoints (no auth) are called directly. Write endpoints take a
Request and call `assert_can_write_metrics`; tests use `Mock()` for the
Request and monkeypatch the auth check (matches the existing trackio
pattern in `test_token_auth.py`).
"""

import hashlib
import re
import sqlite3
from pathlib import Path
from unittest.mock import Mock

import pytest

import trackio
from trackio import cas, server, utils
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


def test_artifact_log_rejects_invalid_digest_format(temp_dir, auth_bypassed):
    with pytest.raises(TrackioAPIError, match="Invalid sha256"):
        _log_artifact(
            auth_bypassed,
            manifest=[{"path": "x", "digest": "../secret", "size": 1}],
            name="my-model",
        )


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


def test_artifact_log_rejects_invalid_name(auth_bypassed, stage_blob):
    payload = b"payload"
    digest, _ = stage_blob("p", payload)
    with pytest.raises(TrackioAPIError, match="must match"):
        _log_artifact(
            auth_bypassed,
            manifest=[{"path": "w.bin", "digest": digest, "size": len(payload)}],
            name="bad name!",
        )


def test_artifact_log_rejects_empty_type(auth_bypassed, stage_blob):
    payload = b"payload"
    digest, _ = stage_blob("p", payload)
    with pytest.raises(TrackioAPIError, match="type must be a non-empty string"):
        _log_artifact(
            auth_bypassed,
            manifest=[{"path": "w.bin", "digest": digest, "size": len(payload)}],
            type="",
        )


def test_artifact_log_rejects_empty_manifest(temp_dir, auth_bypassed):
    with pytest.raises(TrackioAPIError, match="non-empty list"):
        _log_artifact(auth_bypassed, [])


def test_artifact_log_rejects_non_string_project(temp_dir, auth_bypassed):
    with pytest.raises(TrackioAPIError, match="Invalid project"):
        _log_artifact(auth_bypassed, [], project=123)


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


def test_list_artifacts_groups_versions_and_aliases(
    temp_dir, auth_bypassed, stage_blob
):
    d_v0, _ = stage_blob("p", b"model-v0")
    _log_artifact(
        auth_bypassed,
        manifest=[{"path": "w.bin", "digest": d_v0, "size": 8}],
        name="m",
        type="model",
    )
    d_v1, _ = stage_blob("p", b"model-v1-bigger")
    _log_artifact(
        auth_bypassed,
        manifest=[{"path": "w.bin", "digest": d_v1, "size": 15}],
        name="m",
        type="model",
        aliases=["prod"],
    )
    d_data, _ = stage_blob("p", b"rows")
    _log_artifact(
        auth_bypassed,
        manifest=[
            {"path": "train.csv", "digest": d_data, "size": 4},
            {"path": "meta.json", "digest": d_v0, "size": 8},
        ],
        name="data",
        type="dataset",
    )

    arts = server.list_artifacts("p")
    assert [a["type"] for a in arts] == ["dataset", "model"]
    by_name = {a["name"]: a for a in arts}

    model = by_name["m"]
    assert model["num_versions"] == 2
    assert model["latest_version"] == 1
    assert [v["version"] for v in model["versions"]] == [1, 0]
    assert sorted(model["versions"][0]["aliases"]) == ["latest", "prod"]
    assert model["versions"][1]["aliases"] == []
    assert model["versions"][0]["num_files"] == 1

    data = by_name["data"]
    assert data["num_versions"] == 1
    assert data["versions"][0]["num_files"] == 2
    assert "manifest" not in data["versions"][0]


def test_list_artifacts_empty_project_returns_empty(temp_dir):
    assert server.list_artifacts("no-such-project") == []


def test_get_tab_availability_reflects_artifacts(temp_dir, auth_bypassed, stage_blob):
    assert server.get_tab_availability("p")["artifacts"] is False
    digest, _ = stage_blob("p", b"x")
    _log_artifact(
        auth_bypassed,
        manifest=[{"path": "x", "digest": digest, "size": 1}],
    )
    assert server.get_tab_availability("p")["artifacts"] is True


def test_get_run_artifacts_endpoint_returns_inputs_and_outputs(
    temp_dir, auth_bypassed, stage_blob
):
    digest, _ = stage_blob("p", b"w")
    result = _log_artifact(
        auth_bypassed,
        manifest=[{"path": "w.bin", "digest": digest, "size": 1}],
        name="m",
        type="model",
        run_name="producer",
        run_id="prod-id",
    )

    prod = server.get_run_artifacts("p", run="producer", run_id="prod-id")
    assert [a["name"] for a in prod["output"]] == ["m"]
    assert prod["input"] == []

    server.log_artifact_use(
        request=auth_bypassed,
        project="p",
        version_id=result["version_id"],
        run_name="consumer",
        run_id="cons-id",
        hf_token=None,
    )
    cons = server.get_run_artifacts("p", run="consumer", run_id="cons-id")
    assert [a["name"] for a in cons["input"]] == ["m"]
    assert cons["output"] == []


def test_get_run_artifacts_endpoint_empty_on_miss(temp_dir):
    assert server.get_run_artifacts("p", run="nope", run_id=None) == {
        "input": [],
        "output": [],
    }


def test_get_artifact_consumers_endpoint(temp_dir, auth_bypassed, stage_blob):
    digest, _ = stage_blob("p", b"w")
    result = _log_artifact(
        auth_bypassed,
        manifest=[{"path": "w.bin", "digest": digest, "size": 1}],
        name="m",
        run_name="producer",
        run_id="prod-id",
    )
    version_id = result["version_id"]

    assert server.get_artifact_consumers("p", version_id) == []

    for run_name, run_id in [("consumer-a", "a-id"), ("consumer-b", "b-id")]:
        server.log_artifact_use(
            request=auth_bypassed,
            project="p",
            version_id=version_id,
            run_name=run_name,
            run_id=run_id,
            hf_token=None,
        )

    consumers = server.get_artifact_consumers("p", version_id)
    assert sorted(c["run_name"] for c in consumers) == ["consumer-a", "consumer-b"]


def test_get_artifact_consumers_empty_on_miss(temp_dir):
    assert server.get_artifact_consumers("p", 999) == []


def test_run_records_include_artifact_only_runs(temp_dir, auth_bypassed, stage_blob):
    digest, _ = stage_blob("p", b"w")
    _log_artifact(
        auth_bypassed,
        manifest=[{"path": "w.bin", "digest": digest, "size": 1}],
        name="m",
        run_name="artifact-only",
        run_id="ao-id",
    )
    records = SQLiteStorage.get_run_records("p")
    assert any(r["name"] == "artifact-only" and r["id"] == "ao-id" for r in records)


def test_delete_run_clears_artifact_links_no_resurrection(
    temp_dir, auth_bypassed, stage_blob
):
    digest, _ = stage_blob("p", b"w")
    _log_artifact(
        auth_bypassed,
        manifest=[{"path": "w.bin", "digest": digest, "size": 1}],
        name="m",
        run_name="producer",
        run_id="prod-id",
    )
    assert any(r["name"] == "producer" for r in SQLiteStorage.get_run_records("p"))

    assert SQLiteStorage.delete_run("p", "producer", run_id="prod-id") is True

    assert all(r["name"] != "producer" for r in SQLiteStorage.get_run_records("p"))
    assert SQLiteStorage.get_run_artifacts("p", "producer", "prod-id") == {
        "input": [],
        "output": [],
    }


def test_rename_run_updates_artifact_links_and_producer(
    temp_dir, auth_bypassed, stage_blob
):
    digest, _ = stage_blob("p", b"w")
    _log_artifact(
        auth_bypassed,
        manifest=[{"path": "w.bin", "digest": digest, "size": 1}],
        name="m",
        run_name="old-name",
        run_id="r-id",
    )

    SQLiteStorage.rename_run("p", "old-name", "new-name", run_id="r-id")

    names = {r["name"] for r in SQLiteStorage.get_run_records("p")}
    assert "new-name" in names and "old-name" not in names

    out = SQLiteStorage.get_run_artifacts("p", "new-name", "r-id")["output"]
    assert [a["name"] for a in out] == ["m"]
    assert (
        SQLiteStorage.get_artifact_manifest("p", "m", "latest")["producer_run_name"]
        == "new-name"
    )


def _insert_metrics_row(project, run_name, run_id):
    db_path = SQLiteStorage.init_db(project)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO metrics (timestamp, run_id, run_name, step, metrics) "
            "VALUES (?, ?, ?, ?, ?)",
            ("2026-01-01T00:00:00+00:00", run_id, run_name, 0, "{}"),
        )
        conn.commit()


def _create_legacy_project_db(project):
    db_path = SQLiteStorage.get_project_db_path(project)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE metrics (id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "timestamp TEXT, run_name TEXT, step INTEGER, metrics TEXT)"
        )
        conn.execute(
            "INSERT INTO metrics (timestamp, run_name, step, metrics) "
            "VALUES ('2026-01-01T00:00:00+00:00', 'legacy-run', 0, '{}')"
        )
        conn.commit()


def test_run_records_single_entry_for_name_keyed_metrics(
    temp_dir, auth_bypassed, stage_blob
):
    _insert_metrics_row("p", "train", "train")
    digest, _ = stage_blob("p", b"w")
    _log_artifact(
        auth_bypassed,
        manifest=[{"path": "w.bin", "digest": digest, "size": 1}],
        name="m",
        run_name="train",
        run_id="uuid-1",
    )
    records = [r for r in SQLiteStorage.get_run_records("p") if r["name"] == "train"]
    assert len(records) == 1


def test_run_artifacts_dedupe_legacy_and_modern_link_rows(
    temp_dir, auth_bypassed, stage_blob
):
    digest, _ = stage_blob("p", b"w")
    manifest = [{"path": "w.bin", "digest": digest, "size": 1}]
    _log_artifact(auth_bypassed, manifest=manifest, name="m", run_name="r", run_id=None)
    _log_artifact(
        auth_bypassed, manifest=manifest, name="m", run_name="r", run_id="rid"
    )
    out = SQLiteStorage.get_run_artifacts("p", "r", "rid")["output"]
    assert len(out) == 1
    counts = SQLiteStorage.get_run_artifact_counts("p")
    assert sum(c["output"] for c in counts) == 1


def test_delete_artifact_only_run_without_run_id(temp_dir, auth_bypassed, stage_blob):
    digest, _ = stage_blob("p", b"w")
    _log_artifact(
        auth_bypassed,
        manifest=[{"path": "w.bin", "digest": digest, "size": 1}],
        name="m",
        run_name="ao",
        run_id=None,
    )
    records = SQLiteStorage.get_run_records("p")
    assert any(r["name"] == "ao" and r["id"] is None for r in records)

    assert SQLiteStorage.delete_run("p", "ao") is True

    assert all(r["name"] != "ao" for r in SQLiteStorage.get_run_records("p"))
    assert SQLiteStorage.get_run_artifacts("p", "ao", None) == {
        "input": [],
        "output": [],
    }


def test_rename_artifact_only_run_without_run_id(temp_dir, auth_bypassed, stage_blob):
    digest, _ = stage_blob("p", b"w")
    _log_artifact(
        auth_bypassed,
        manifest=[{"path": "w.bin", "digest": digest, "size": 1}],
        name="m",
        run_name="ao",
        run_id=None,
    )

    SQLiteStorage.rename_run("p", "ao", "ao-renamed")

    names = {r["name"] for r in SQLiteStorage.get_run_records("p")}
    assert "ao-renamed" in names and "ao" not in names
    out = SQLiteStorage.get_run_artifacts("p", "ao-renamed", None)["output"]
    assert [a["name"] for a in out] == ["m"]


def test_delete_run_preserves_same_name_run_lineage(
    temp_dir, auth_bypassed, stage_blob
):
    digest, _ = stage_blob("p", b"w")
    _log_artifact(
        auth_bypassed,
        manifest=[{"path": "w.bin", "digest": digest, "size": 1}],
        name="m",
        run_name="train",
        run_id=None,
    )
    _insert_metrics_row("p", "train", "keep-id")
    _insert_metrics_row("p", "train", "gone-id")

    assert SQLiteStorage.delete_run("p", "train", run_id="gone-id") is True

    out = SQLiteStorage.get_run_artifacts("p", "train", None)["output"]
    assert [a["name"] for a in out] == ["m"]
    assert (
        SQLiteStorage.get_artifact_manifest("p", "m", "latest")["producer_run_name"]
        == "train"
    )


def test_legacy_metrics_db_artifact_links_resolved_by_name(
    temp_dir, auth_bypassed, stage_blob
):
    _create_legacy_project_db("p")
    digest, _ = stage_blob("p", b"w")
    _log_artifact(
        auth_bypassed,
        manifest=[{"path": "w.bin", "digest": digest, "size": 1}],
        name="m",
        run_name="legacy-run",
        run_id="client-uuid",
    )

    records = SQLiteStorage.get_run_records("p")
    assert [r["name"] for r in records] == ["legacy-run"]

    out = SQLiteStorage.get_run_artifacts("p", "legacy-run", records[0]["id"])
    assert [a["name"] for a in out["output"]] == ["m"]

    counts = SQLiteStorage.get_run_artifact_counts("p")
    assert counts == [
        {"run_id": None, "run_name": "legacy-run", "input": 0, "output": 1}
    ]


def test_static_frontend_blob_url_matches_cas_layout(temp_dir):
    digest = "ab" + "0" * 62
    rel = cas.blob_path("p", digest).relative_to(utils.project_artifacts_dir("p"))
    assert rel.as_posix() == f"blobs/sha256/{digest[:2]}/{digest}"

    js_path = (
        Path(trackio.__file__).parent / "frontend" / "src" / "lib" / "staticApi.js"
    )
    if not js_path.exists():
        pytest.skip("frontend sources not present in this install")
    assert (
        "artifacts/blobs/sha256/${digest.slice(0, 2)}/${digest}" in js_path.read_text()
    )
