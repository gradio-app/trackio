import pytest

from trackio.sqlite_storage import SQLiteStorage


def test_canonical_manifest_is_order_invariant():
    a = [
        {"path": "weights.bin", "digest": "deadbeef", "size": 10},
        {"path": "config.json", "digest": "cafef00d", "size": 3},
    ]
    b = list(reversed(a))
    _, dig_a, size_a = SQLiteStorage._canonical_manifest(a)
    _, dig_b, size_b = SQLiteStorage._canonical_manifest(b)
    assert dig_a == dig_b
    assert size_a == size_b == 13


def test_canonical_manifest_digest_changes_with_content():
    a = [{"path": "f", "digest": "aa", "size": 1}]
    b = [{"path": "f", "digest": "bb", "size": 1}]
    _, dig_a, _ = SQLiteStorage._canonical_manifest(a)
    _, dig_b, _ = SQLiteStorage._canonical_manifest(b)
    assert dig_a != dig_b


def test_create_or_get_artifact_returns_same_id(temp_dir):
    a = SQLiteStorage.create_or_get_artifact("p", "m", "model", "first")
    b = SQLiteStorage.create_or_get_artifact("p", "m", "model", "ignored")
    assert a == b


def test_create_or_get_artifact_rejects_type_change(temp_dir):
    SQLiteStorage.create_or_get_artifact("p", "m", "model", None)
    with pytest.raises(ValueError, match="already exists with type"):
        SQLiteStorage.create_or_get_artifact("p", "m", "dataset", None)


def test_insert_artifact_version_dedupes(temp_dir):
    aid = SQLiteStorage.create_or_get_artifact("p", "m", "model", None)
    manifest = [{"path": "w.bin", "digest": "abc", "size": 5}]
    vid_1, v_1 = SQLiteStorage.insert_artifact_version(
        "p", aid, manifest, None, None, "run-a"
    )
    vid_2, v_2 = SQLiteStorage.insert_artifact_version(
        "p", aid, manifest, None, None, "run-b"
    )
    assert vid_1 == vid_2
    assert v_1 == v_2 == 0


def test_insert_artifact_version_increments(temp_dir):
    aid = SQLiteStorage.create_or_get_artifact("p", "m", "model", None)
    _, v_0 = SQLiteStorage.insert_artifact_version(
        "p", aid, [{"path": "a", "digest": "1", "size": 1}], None, None, "r"
    )
    _, v_1 = SQLiteStorage.insert_artifact_version(
        "p", aid, [{"path": "a", "digest": "2", "size": 1}], None, None, "r"
    )
    _, v_2 = SQLiteStorage.insert_artifact_version(
        "p", aid, [{"path": "a", "digest": "3", "size": 1}], None, None, "r"
    )
    assert (v_0, v_1, v_2) == (0, 1, 2)


def test_reassign_alias_rotates(temp_dir):
    aid = SQLiteStorage.create_or_get_artifact("p", "m", "model", None)
    vid_0, _ = SQLiteStorage.insert_artifact_version(
        "p", aid, [{"path": "a", "digest": "1", "size": 1}], None, None, "r"
    )
    vid_1, _ = SQLiteStorage.insert_artifact_version(
        "p", aid, [{"path": "a", "digest": "2", "size": 1}], None, None, "r"
    )
    SQLiteStorage.reassign_alias("p", aid, "latest", vid_0)
    SQLiteStorage.reassign_alias("p", aid, "latest", vid_1)
    resolved = SQLiteStorage.resolve_artifact_version("p", "m", "latest")
    assert resolved["version_id"] == vid_1
    assert resolved["version"] == 1


def test_reassign_alias_rejects_version_pointer(temp_dir):
    aid = SQLiteStorage.create_or_get_artifact("p", "m", "model", None)
    vid, _ = SQLiteStorage.insert_artifact_version(
        "p", aid, [{"path": "a", "digest": "1", "size": 1}], None, None, "r"
    )
    with pytest.raises(ValueError, match="reserved"):
        SQLiteStorage.reassign_alias("p", aid, "v3", vid)


def test_resolve_artifact_version_spec_grammar(temp_dir):
    aid = SQLiteStorage.create_or_get_artifact("p", "m", "model", None)
    vid_0, _ = SQLiteStorage.insert_artifact_version(
        "p", aid, [{"path": "a", "digest": "1", "size": 1}], None, None, "r"
    )
    vid_1, _ = SQLiteStorage.insert_artifact_version(
        "p", aid, [{"path": "a", "digest": "2", "size": 1}], None, None, "r"
    )
    SQLiteStorage.reassign_alias("p", aid, "best", vid_0)
    SQLiteStorage.reassign_alias("p", aid, "latest", vid_1)

    assert SQLiteStorage.resolve_artifact_version("p", "m", None)["version_id"] == vid_1
    assert (
        SQLiteStorage.resolve_artifact_version("p", "m", "latest")["version_id"]
        == vid_1
    )
    assert (
        SQLiteStorage.resolve_artifact_version("p", "m", "best")["version_id"] == vid_0
    )
    assert SQLiteStorage.resolve_artifact_version("p", "m", "v0")["version_id"] == vid_0
    assert SQLiteStorage.resolve_artifact_version("p", "m", "v1")["version_id"] == vid_1
    assert SQLiteStorage.resolve_artifact_version("p", "m", "v99") is None
    assert SQLiteStorage.resolve_artifact_version("p", "m", "no-such-alias") is None
    assert SQLiteStorage.resolve_artifact_version("p", "missing", "latest") is None


def test_insert_run_artifact_link_and_get(temp_dir):
    aid = SQLiteStorage.create_or_get_artifact("p", "m", "model", None)
    vid, _ = SQLiteStorage.insert_artifact_version(
        "p", aid, [{"path": "a", "digest": "1", "size": 7}], None, None, "producer"
    )
    SQLiteStorage.insert_run_artifact_link("p", "producer", None, vid, "output")
    SQLiteStorage.insert_run_artifact_link("p", "consumer", None, vid, "input")

    producer_arts = SQLiteStorage.get_run_artifacts("p", "producer", None)
    assert len(producer_arts["output"]) == 1
    assert producer_arts["output"][0]["name"] == "m"
    assert producer_arts["output"][0]["size_bytes"] == 7
    assert producer_arts["input"] == []

    consumer_arts = SQLiteStorage.get_run_artifacts("p", "consumer", None)
    assert consumer_arts["output"] == []
    assert len(consumer_arts["input"]) == 1


def test_insert_run_artifact_link_rejects_bad_direction(temp_dir):
    aid = SQLiteStorage.create_or_get_artifact("p", "m", "model", None)
    vid, _ = SQLiteStorage.insert_artifact_version(
        "p", aid, [{"path": "a", "digest": "1", "size": 1}], None, None, "r"
    )
    with pytest.raises(ValueError, match="direction"):
        SQLiteStorage.insert_run_artifact_link("p", "r", None, vid, "sideways")


def test_list_artifacts_and_versions(temp_dir):
    aid = SQLiteStorage.create_or_get_artifact("p", "m", "model", "weights")
    vid_0, _ = SQLiteStorage.insert_artifact_version(
        "p", aid, [{"path": "a", "digest": "1", "size": 11}], {"acc": 0.5}, None, "r0"
    )
    vid_1, _ = SQLiteStorage.insert_artifact_version(
        "p", aid, [{"path": "a", "digest": "2", "size": 22}], {"acc": 0.9}, None, "r1"
    )
    SQLiteStorage.reassign_alias("p", aid, "latest", vid_1)
    SQLiteStorage.reassign_alias("p", aid, "best", vid_1)
    SQLiteStorage.reassign_alias("p", aid, "stable", vid_0)

    arts = SQLiteStorage.list_artifacts("p")
    assert len(arts) == 1
    art = arts[0]
    assert art["name"] == "m"
    assert art["type"] == "model"
    assert art["description"] == "weights"
    assert art["version_count"] == 2
    assert art["latest_version"] == 1
    assert art["latest_size"] == 22
    assert sorted(art["latest_aliases"]) == ["best", "latest"]

    versions = SQLiteStorage.list_artifact_versions("p", "m")
    assert [v["version"] for v in versions] == [1, 0]
    v_latest = versions[0]
    assert v_latest["size_bytes"] == 22
    assert v_latest["metadata"] == {"acc": 0.9}
    assert sorted(v_latest["aliases"]) == ["best", "latest"]
    v_old = versions[1]
    assert v_old["aliases"] == ["stable"]


def test_get_artifact_manifest(temp_dir):
    aid = SQLiteStorage.create_or_get_artifact("p", "m", "model", None)
    manifest = [
        {"path": "weights.bin", "digest": "ab", "size": 5},
        {"path": "config.json", "digest": "cd", "size": 2},
    ]
    vid, _ = SQLiteStorage.insert_artifact_version(
        "p", aid, manifest, {"k": 1}, None, "producer"
    )
    SQLiteStorage.reassign_alias("p", aid, "latest", vid)
    SQLiteStorage.reassign_alias("p", aid, "best", vid)

    m_by_alias = SQLiteStorage.get_artifact_manifest("p", "m", "latest")
    m_by_version = SQLiteStorage.get_artifact_manifest("p", "m", "v0")
    m_by_none = SQLiteStorage.get_artifact_manifest("p", "m", None)
    assert m_by_alias is not None
    assert m_by_alias["version_id"] == vid
    assert m_by_version["version_id"] == vid
    assert m_by_none["version_id"] == vid
    assert m_by_alias["manifest"] == sorted(manifest, key=lambda e: e["path"])
    assert m_by_alias["metadata"] == {"k": 1}
    assert sorted(m_by_alias["aliases"]) == ["best", "latest"]

    assert SQLiteStorage.get_artifact_manifest("p", "missing", "latest") is None


def test_enqueue_artifact_blob_upload_writes_kind_and_digest(temp_dir):
    SQLiteStorage.init_db("p")
    SQLiteStorage.enqueue_artifact_blob_uploads(
        project="p",
        space_id="sp",
        blobs=[("dead", "/tmp/blob")],
        run_name="r",
        run_id=None,
    )
    import sqlite3

    db = SQLiteStorage.get_project_db_path("p")
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT kind, digest, file_path, step FROM pending_uploads"
    ).fetchall()
    conn.close()
    assert len(rows) == 1
    assert rows[0]["kind"] == "artifact_blob"
    assert rows[0]["digest"] == "dead"
    assert rows[0]["file_path"] == "/tmp/blob"
    assert rows[0]["step"] is None


def test_list_artifact_blobs_present(temp_dir, monkeypatch):
    from pathlib import Path

    from trackio import utils as trackio_utils

    base = Path(temp_dir) / "artifacts" / "p" / "blobs" / "sha256"
    monkeypatch.setattr(trackio_utils, "ARTIFACTS_DIR", Path(temp_dir) / "artifacts")
    d1 = "a" * 64
    d2 = "1" * 64
    d_absent = "f" * 64
    (base / d1[:2]).mkdir(parents=True)
    (base / d1[:2] / d1).write_bytes(b"x")
    (base / d2[:2]).mkdir(parents=True)
    (base / d2[:2] / d2).write_bytes(b"x")

    present = SQLiteStorage.list_artifact_blobs_present("p", [d1, d2, d_absent])
    assert present == {d1, d2}
    assert SQLiteStorage.list_artifact_blobs_present("p", []) == set()


def test_list_artifact_blobs_present_rejects_path_traversal(temp_dir, monkeypatch):
    from pathlib import Path

    from trackio import utils as trackio_utils

    monkeypatch.setattr(trackio_utils, "ARTIFACTS_DIR", Path(temp_dir) / "artifacts")
    sensitive = Path(temp_dir) / "secret.txt"
    sensitive.write_text("SECRET")

    bad_digests = ["../secret.txt", "../../etc/passwd", "ab", "", "g" * 64, "A" * 64]
    present = SQLiteStorage.list_artifact_blobs_present("p", bad_digests)
    assert present == set()


# --- Artifact class ---

import hashlib
from pathlib import Path

from trackio.artifact import Artifact
from trackio.cas import HASH_CHUNK_SIZE, hash_file
from trackio.typehints import Sha256Digest


def test_hash_file_is_deterministic_and_correct_size(tmp_path):
    p = tmp_path / "x"
    payload = b"hello world"
    p.write_bytes(payload)
    d1, s1 = hash_file(p)
    d2, s2 = hash_file(p)
    assert d1 == d2 == hashlib.sha256(payload).hexdigest()
    assert s1 == s2 == len(payload)


def test_hash_file_modern_and_fallback_paths_agree(tmp_path, monkeypatch):
    p = tmp_path / "blob"
    payload = b"x" * (HASH_CHUNK_SIZE + 17) + b"trailing"
    p.write_bytes(payload)

    d_modern, s_modern = hash_file(p)

    monkeypatch.delattr("hashlib.file_digest", raising=False)
    d_fallback, s_fallback = hash_file(p)

    assert d_modern == d_fallback == hashlib.sha256(payload).hexdigest()
    assert s_modern == s_fallback == len(payload)


def test_artifact_rejects_invalid_name():
    with pytest.raises(ValueError, match="must match"):
        Artifact(name="bad name", type="model")
    with pytest.raises(ValueError, match="must match"):
        Artifact(name="", type="model")


def test_artifact_constructor_exposes_attrs():
    a = Artifact(name="my-model", type="model", description="d", metadata={"k": 1})
    assert a.name == "my-model"
    assert a.type == "model"
    assert a.description == "d"
    assert a.metadata == {"k": 1}
    assert a.version is None
    assert a.aliases == ()
    assert a.size is None
    assert a.manifest is None
    assert a.manifest_digest is None


def test_artifact_name_is_readonly():
    a = Artifact(name="m", type="model")
    with pytest.raises(AttributeError):
        a.name = "other"


def test_artifact_metadata_copied_at_init_then_live():
    md = {"k": 1}
    a = Artifact(name="m", type="model", metadata=md)
    md["k"] = 999
    assert a.metadata == {"k": 1}
    a.metadata["k"] = 2
    assert a.metadata == {"k": 2}
    a.metadata = {"fresh": True}
    assert a.metadata == {"fresh": True}
    a.description = "now mutable"
    assert a.description == "now mutable"


def test_add_file_records_pending(tmp_path):
    p = tmp_path / "weights.bin"
    p.write_bytes(b"x")
    a = Artifact(name="m", type="model")
    a.add_file(p)
    assert a._pending_files == [(p.resolve(), "weights.bin")]
    a.add_file(p, name="logical.bin")
    assert a._pending_files[1] == (p.resolve(), "logical.bin")


def test_add_file_rejects_nonexistent(tmp_path):
    a = Artifact(name="m", type="model")
    with pytest.raises(ValueError, match="Not a regular file"):
        a.add_file(tmp_path / "missing")


def test_add_dir_skips_symlinks(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.txt").write_bytes(b"a")
    (src / "link").symlink_to(src / "a.txt")
    a = Artifact(name="m", type="model")
    a.add_dir(src)
    paths = sorted(logical for _, logical in a._pending_files)
    assert paths == ["a.txt"]


def test_add_dir_with_prefix(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.txt").write_bytes(b"a")
    (src / "sub").mkdir()
    (src / "sub" / "b.txt").write_bytes(b"b")
    a = Artifact(name="m", type="model")
    a.add_dir(src, name="weights")
    logicals = sorted(logical for _, logical in a._pending_files)
    assert logicals == ["weights/a.txt", "weights/sub/b.txt"]


def test_add_file_rejects_traversal_names(tmp_path):
    p = tmp_path / "x"
    p.write_bytes(b"abc")
    a = Artifact(name="m", type="model")
    for bad in ("../escape", "/abs/path", "a/../b", "a//b", ".", "C:evil", "a\\b"):
        with pytest.raises(ValueError, match="Invalid artifact path"):
            a.add_file(p, name=bad)


def test_add_dir_rejects_traversal_prefix(tmp_path):
    d = tmp_path / "d"
    d.mkdir()
    (d / "f").write_bytes(b"abc")
    a = Artifact(name="m", type="model")
    for bad in ("../up", "/abs"):
        with pytest.raises(ValueError, match="Invalid artifact path"):
            a.add_dir(d, name=bad)


def test_download_rejects_traversal_paths_in_manifest(temp_dir, tmp_path):
    digest, size = _stage_blob(temp_dir, "proj", b"evil")
    a = _hydrated_artifact(
        "proj",
        "my-model",
        0,
        [{"path": "../outside.bin", "digest": Sha256Digest(digest), "size": size}],
    )
    dl = tmp_path / "dl"
    with pytest.raises(ValueError, match="Invalid artifact path"):
        a.download(dl)
    assert not (tmp_path / "outside.bin").exists()


def test_download_rejects_absolute_paths_in_manifest(temp_dir, tmp_path):
    digest, size = _stage_blob(temp_dir, "proj", b"evil")
    target = tmp_path / "planted.bin"
    a = _hydrated_artifact(
        "proj",
        "my-model",
        0,
        [{"path": str(target), "digest": Sha256Digest(digest), "size": size}],
    )
    with pytest.raises(ValueError, match="Invalid artifact path"):
        a.download(tmp_path / "dl")
    assert not target.exists()


def test_build_manifest_writes_blob_with_correct_digest(temp_dir, tmp_path):
    payload = b"hello"
    p = tmp_path / "w.bin"
    p.write_bytes(payload)
    a = Artifact(name="m", type="model")
    a.add_file(p)
    manifest = a._build_manifest("proj")
    assert manifest[0]["path"] == "w.bin"
    assert manifest[0]["size"] == len(payload)
    expected_digest = hashlib.sha256(payload).hexdigest()
    assert manifest[0]["digest"] == expected_digest
    blob = (
        Path(temp_dir)
        / "artifacts"
        / "proj"
        / "blobs"
        / "sha256"
        / expected_digest[:2]
        / expected_digest
    )
    assert blob.is_file()
    assert blob.read_bytes() == payload


def test_build_manifest_dedupes_blob_files(temp_dir, tmp_path):
    p1 = tmp_path / "a"
    p2 = tmp_path / "b"
    p1.write_bytes(b"same")
    p2.write_bytes(b"same")
    a = Artifact(name="m", type="model")
    a.add_file(p1)
    a.add_file(p2)
    a._build_manifest("p")
    blobs_dir = Path(temp_dir) / "artifacts" / "p" / "blobs" / "sha256"
    blob_files = [p for p in blobs_dir.rglob("*") if p.is_file()]
    assert len(blob_files) == 1


def test_build_manifest_rejects_duplicate_logical_path(temp_dir, tmp_path):
    p1 = tmp_path / "a"
    p2 = tmp_path / "b"
    p1.write_bytes(b"a")
    p2.write_bytes(b"b")
    a = Artifact(name="m", type="model")
    a.add_file(p1, name="x")
    a.add_file(p2, name="x")
    with pytest.raises(ValueError, match="Duplicate logical path"):
        a._build_manifest("p")


def test_build_manifest_rejects_double_add_of_same_file(temp_dir, tmp_path):
    p = tmp_path / "w.bin"
    p.write_bytes(b"x")
    a = Artifact(name="m", type="model")
    a.add_file(p)
    a.add_file(p)
    with pytest.raises(ValueError, match="Duplicate logical path"):
        a._build_manifest("p")


def test_build_manifest_rejects_empty(temp_dir):
    a = Artifact(name="m", type="model")
    with pytest.raises(ValueError, match="no files"):
        a._build_manifest("p")


def test_add_file_after_logged_raises(temp_dir, tmp_path):
    a = Artifact(name="m", type="model")
    a._logged = True
    with pytest.raises(RuntimeError, match="already been logged"):
        a.add_file(tmp_path / "x")
    with pytest.raises(RuntimeError, match="already been logged"):
        a.add_dir(tmp_path)


def test_build_manifest_copies_so_source_mutation_does_not_corrupt_blob(
    temp_dir, tmp_path
):
    p = tmp_path / "x"
    p.write_bytes(b"abc")
    a = Artifact(name="m", type="model")
    a.add_file(p)
    manifest = a._build_manifest("p")
    digest = manifest[0]["digest"]
    blob = Path(temp_dir) / "artifacts" / "p" / "blobs" / "sha256" / digest[:2] / digest
    assert blob.is_file()
    assert blob.read_bytes() == b"abc"

    p.write_bytes(b"mutated!")
    assert blob.read_bytes() == b"abc"
    assert hashlib.sha256(blob.read_bytes()).hexdigest() == digest


def test_hydrate_from_db_populates_readonly_attrs():
    a = Artifact(name="m", type="model")
    a._hydrate_from_db(
        project="proj",
        version=2,
        aliases=["latest", "best"],
        manifest=[
            {"path": "x", "digest": Sha256Digest("abc"), "size": 3},
        ],
        manifest_digest=Sha256Digest("def"),
        size_bytes=3,
        description="hydrated",
        metadata={"acc": 0.9},
    )
    assert a.version == "v2"
    assert a.aliases == ("latest", "best")
    assert a.size == 3
    assert a.manifest_digest == "def"
    assert a.manifest == [{"path": "x", "digest": "abc", "size": 3}]
    assert a.description == "hydrated"
    assert a.metadata == {"acc": 0.9}
    assert a.project == "proj"
    assert a._logged is True


# --- Artifact.download() local materialization ---


def _stage_blob(temp_dir: str, project: str, payload: bytes) -> tuple[str, int]:
    digest = hashlib.sha256(payload).hexdigest()
    blob = (
        Path(temp_dir)
        / "artifacts"
        / project
        / "blobs"
        / "sha256"
        / digest[:2]
        / digest
    )
    blob.parent.mkdir(parents=True, exist_ok=True)
    blob.write_bytes(payload)
    return digest, len(payload)


def _hydrated_artifact(
    project: str,
    name: str,
    version: int,
    entries: list,
) -> Artifact:
    a = Artifact(name=name, type="model")
    a._hydrate_from_db(
        project=project,
        version=version,
        aliases=["latest"],
        manifest=entries,
        manifest_digest=Sha256Digest("0" * 64),
        size_bytes=sum(e["size"] for e in entries),
    )
    return a


def test_download_materializes_files(temp_dir, tmp_path):
    digest_a, size_a = _stage_blob(temp_dir, "proj", b"alpha")
    digest_b, size_b = _stage_blob(temp_dir, "proj", b"beta")
    a = _hydrated_artifact(
        "proj",
        "my-model",
        0,
        [
            {"path": "weights.bin", "digest": Sha256Digest(digest_a), "size": size_a},
            {
                "path": "sub/config.json",
                "digest": Sha256Digest(digest_b),
                "size": size_b,
            },
        ],
    )
    out = a.download(tmp_path / "dl")
    assert (Path(out) / "weights.bin").read_bytes() == b"alpha"
    assert (Path(out) / "sub" / "config.json").read_bytes() == b"beta"


def test_download_default_root_convention(temp_dir, tmp_path, monkeypatch):
    digest, size = _stage_blob(temp_dir, "proj", b"x")
    a = _hydrated_artifact(
        "proj",
        "my-model",
        0,
        [{"path": "w.bin", "digest": Sha256Digest(digest), "size": size}],
    )
    monkeypatch.chdir(tmp_path)
    out = a.download()
    assert Path(out).resolve() == (tmp_path / "artifacts" / "my-model_v0").resolve()
    assert (Path(out) / "w.bin").read_bytes() == b"x"


def test_download_default_spec_uses_version(temp_dir, tmp_path, monkeypatch):
    digest, size = _stage_blob(temp_dir, "proj", b"x")
    a = _hydrated_artifact(
        "proj",
        "my-model",
        3,
        [{"path": "w.bin", "digest": Sha256Digest(digest), "size": size}],
    )
    monkeypatch.chdir(tmp_path)
    out = a.download()
    assert Path(out).resolve() == (tmp_path / "artifacts" / "my-model_v3").resolve()


def test_download_is_idempotent(temp_dir, tmp_path):
    digest, size = _stage_blob(temp_dir, "proj", b"x")
    a = _hydrated_artifact(
        "proj",
        "my-model",
        0,
        [{"path": "w.bin", "digest": Sha256Digest(digest), "size": size}],
    )
    out1 = a.download(tmp_path / "dl")
    file = Path(out1) / "w.bin"
    first_mtime_ns = file.stat().st_mtime_ns
    out2 = a.download(tmp_path / "dl")
    assert out2 == out1
    assert file.stat().st_mtime_ns == first_mtime_ns


def test_download_missing_blob_raises(temp_dir, tmp_path):
    a = _hydrated_artifact(
        "proj",
        "my-model",
        0,
        [{"path": "w.bin", "digest": Sha256Digest("a" * 64), "size": 5}],
    )
    with pytest.raises(FileNotFoundError, match="not available locally or remotely"):
        a.download(tmp_path / "dl")


def test_download_on_unlogged_artifact_raises():
    a = Artifact(name="m", type="model")
    with pytest.raises(RuntimeError, match="not been logged"):
        a.download()


def test_download_refreshes_stale_file_with_different_size(temp_dir, tmp_path):
    digest, size = _stage_blob(temp_dir, "proj", b"abc")
    a = _hydrated_artifact(
        "proj",
        "my-model",
        0,
        [{"path": "w.bin", "digest": Sha256Digest(digest), "size": size}],
    )
    dl = tmp_path / "dl"
    dl.mkdir()
    (dl / "w.bin").write_bytes(b"stale-old-content")
    out = a.download(dl)
    assert (Path(out) / "w.bin").read_bytes() == b"abc"


def test_download_shared_digest_materializes_to_distinct_paths(temp_dir, tmp_path):
    digest, size = _stage_blob(temp_dir, "proj", b"same")
    a = _hydrated_artifact(
        "proj",
        "my-model",
        0,
        [
            {"path": "a.bin", "digest": Sha256Digest(digest), "size": size},
            {"path": "b.bin", "digest": Sha256Digest(digest), "size": size},
        ],
    )
    out = a.download(tmp_path / "dl")
    assert (Path(out) / "a.bin").read_bytes() == b"same"
    assert (Path(out) / "b.bin").read_bytes() == b"same"


# --- Run.log_artifact / Run.use_artifact (local mode) ---

import trackio


def _make_file(tmp_path, name, payload):
    p = tmp_path / name
    p.write_bytes(payload)
    return p


def test_run_log_artifact_round_trip(temp_dir, tmp_path):
    weights = _make_file(tmp_path, "weights.bin", b"hello")
    run = trackio.init(project="art-rt", name="producer")
    art = Artifact(name="my-model", type="model")
    art.add_file(weights)
    logged = run.log_artifact(art)
    assert logged is art
    assert logged.version == "v0"
    assert "latest" in logged.aliases
    assert logged.project == "art-rt"
    trackio.finish()

    run2 = trackio.init(project="art-rt", name="consumer")
    fetched = run2.use_artifact("my-model:latest")
    assert fetched.version == "v0"
    assert fetched.name == "my-model"
    assert fetched.type == "model"
    out = fetched.download(tmp_path / "dl")
    assert (Path(out) / "weights.bin").read_bytes() == b"hello"
    trackio.finish()

    lineage_p = SQLiteStorage.get_run_artifacts("art-rt", "producer", None)
    assert len(lineage_p["output"]) == 1
    assert lineage_p["output"][0]["name"] == "my-model"
    assert lineage_p["input"] == []

    lineage_c = SQLiteStorage.get_run_artifacts("art-rt", "consumer", None)
    assert lineage_c["output"] == []
    assert len(lineage_c["input"]) == 1


def test_log_artifact_with_user_aliases(temp_dir, tmp_path):
    weights = _make_file(tmp_path, "w.bin", b"x")
    run = trackio.init(project="art-aliases", name="p")
    art = Artifact(name="m", type="model")
    art.add_file(weights)
    logged = run.log_artifact(art, aliases=["best", "stable"])
    assert sorted(logged.aliases) == ["best", "latest", "stable"]
    trackio.finish()


def test_log_artifact_rejects_version_alias(temp_dir, tmp_path):
    weights = _make_file(tmp_path, "w.bin", b"x")
    run = trackio.init(project="art-vN", name="p")
    art = Artifact(name="m", type="model")
    art.add_file(weights)
    with pytest.raises(ValueError, match="reserved"):
        run.log_artifact(art, aliases=["v3"])
    blobs_dir = Path(temp_dir) / "artifacts" / "art-vN" / "blobs"
    has_blobs = blobs_dir.exists() and any(p.is_file() for p in blobs_dir.rglob("*"))
    assert not has_blobs
    trackio.finish()


def test_relog_same_bytes_dedupes_but_rotates_aliases(temp_dir, tmp_path):
    weights = _make_file(tmp_path, "w.bin", b"x")
    run_a = trackio.init(project="art-dedup", name="run_a")
    art_a = Artifact(name="m", type="model")
    art_a.add_file(weights)
    logged_a = run_a.log_artifact(art_a, aliases=["best"])
    assert logged_a.version == "v0"
    trackio.finish()

    run_b = trackio.init(project="art-dedup", name="run_b")
    art_b = Artifact(name="m", type="model")
    art_b.add_file(weights)
    logged_b = run_b.log_artifact(art_b)
    assert logged_b.version == "v0"
    assert "latest" in logged_b.aliases
    assert "best" in logged_b.aliases
    trackio.finish()

    lineage_a = SQLiteStorage.get_run_artifacts("art-dedup", "run_a", None)
    lineage_b = SQLiteStorage.get_run_artifacts("art-dedup", "run_b", None)
    assert len(lineage_a["output"]) == 1
    assert len(lineage_b["output"]) == 1
    assert lineage_a["output"][0]["version_id"] == lineage_b["output"][0]["version_id"]


def test_aliases_rotate_on_new_version(temp_dir, tmp_path):
    p1 = _make_file(tmp_path, "v1.bin", b"v1")
    p2 = _make_file(tmp_path, "v2.bin", b"v2")

    run_a = trackio.init(project="art-rotate", name="r")
    art_a = Artifact(name="m", type="model")
    art_a.add_file(p1)
    logged_a = run_a.log_artifact(art_a, aliases=["best"])
    assert logged_a.version == "v0"
    trackio.finish()

    run_b = trackio.init(project="art-rotate", name="r2")
    art_b = Artifact(name="m", type="model")
    art_b.add_file(p2)
    logged_b = run_b.log_artifact(art_b, aliases=["best"])
    assert logged_b.version == "v1"

    fetched_best = run_b.use_artifact("m:best")
    assert fetched_best.version == "v1"
    fetched_v0 = run_b.use_artifact("m:v0")
    assert fetched_v0.version == "v0"
    trackio.finish()


def test_use_artifact_spec_parsing(temp_dir, tmp_path):
    weights = _make_file(tmp_path, "w.bin", b"x")
    run = trackio.init(project="art-spec", name="p")
    art = Artifact(name="m", type="model")
    art.add_file(weights)
    run.log_artifact(art, aliases=["best"])

    assert run.use_artifact("m").version == "v0"
    assert run.use_artifact("m:latest").version == "v0"
    assert run.use_artifact("m:best").version == "v0"
    assert run.use_artifact("m:v0").version == "v0"
    trackio.finish()


def test_use_artifact_missing_raises(temp_dir):
    run = trackio.init(project="art-missing", name="p")
    with pytest.raises(ValueError, match="not found"):
        run.use_artifact("nonexistent")
    with pytest.raises(ValueError, match="not found"):
        run.use_artifact("nonexistent:v0")
    trackio.finish()


def test_use_artifact_download_dir_named_by_resolved_version(
    temp_dir, tmp_path, monkeypatch
):
    weights = _make_file(tmp_path, "w.bin", b"x")
    run = trackio.init(project="art-spec-dl", name="p")
    art = Artifact(name="m", type="model")
    art.add_file(weights)
    run.log_artifact(art, aliases=["best"])
    trackio.finish()

    run2 = trackio.init(project="art-spec-dl", name="c")
    fetched = run2.use_artifact("m:best")
    monkeypatch.chdir(tmp_path)
    out = fetched.download()
    assert Path(out).resolve() == (tmp_path / "artifacts" / "m_v0").resolve()
    trackio.finish()


def test_use_artifact_latest_download_does_not_serve_stale_files(
    temp_dir, tmp_path, monkeypatch
):
    weights = _make_file(tmp_path, "w.bin", b"version-zero")
    run = trackio.init(project="art-latest-dl", name="p")
    art = Artifact(name="m", type="model")
    art.add_file(weights)
    run.log_artifact(art)

    monkeypatch.chdir(tmp_path)
    out0 = run.use_artifact("m:latest").download()
    assert (Path(out0) / "w.bin").read_bytes() == b"version-zero"

    weights.write_bytes(b"version-one!")
    art2 = Artifact(name="m", type="model")
    art2.add_file(weights)
    run.log_artifact(art2)

    out1 = run.use_artifact("m:latest").download()
    assert out1 != out0
    assert (Path(out1) / "w.bin").read_bytes() == b"version-one!"
    trackio.finish()


def test_relog_already_logged_artifact_raises(temp_dir, tmp_path):
    weights = _make_file(tmp_path, "w.bin", b"x")
    run = trackio.init(project="art-relog", name="p")
    art = Artifact(name="m", type="model")
    art.add_file(weights)
    run.log_artifact(art)
    with pytest.raises(RuntimeError, match="already been logged"):
        run.log_artifact(art)
    trackio.finish()


def test_log_artifact_accepts_file_path(temp_dir, tmp_path):
    weights = _make_file(tmp_path, "w.bin", b"x")
    run = trackio.init(project="art-path", name="p")
    logged = run.log_artifact(str(weights), name="weights", type="model")
    assert logged.name == "weights"
    assert logged.type == "model"
    assert logged.version == "v0"
    assert [e["path"] for e in logged.manifest] == ["w.bin"]
    trackio.finish()


def test_log_artifact_accepts_dir_path_with_defaults(temp_dir, tmp_path):
    d = tmp_path / "bundle"
    d.mkdir()
    (d / "a.txt").write_bytes(b"a")
    (d / "b.txt").write_bytes(b"b")
    run = trackio.init(project="art-path-dir", name="p")
    logged = run.log_artifact(d)
    assert logged.name == f"run-{run.id}-bundle"
    assert logged.type == "unspecified"
    assert sorted(e["path"] for e in logged.manifest) == ["a.txt", "b.txt"]
    trackio.finish()


def test_log_artifact_rejects_name_with_artifact_instance(temp_dir, tmp_path):
    weights = _make_file(tmp_path, "w.bin", b"x")
    run = trackio.init(project="art-badargs", name="p")
    art = Artifact(name="m", type="model")
    art.add_file(weights)
    with pytest.raises(ValueError, match="only be passed when logging a path"):
        run.log_artifact(art, name="other")
    trackio.finish()


def test_use_artifact_type_check(temp_dir, tmp_path):
    weights = _make_file(tmp_path, "w.bin", b"x")
    run = trackio.init(project="art-type", name="p")
    art = Artifact(name="m", type="model")
    art.add_file(weights)
    run.log_artifact(art)
    assert run.use_artifact("m", type="model").version == "v0"
    with pytest.raises(ValueError, match="has type 'model'"):
        run.use_artifact("m", type="dataset")
    trackio.finish()


def test_use_artifact_accepts_artifact_instance(temp_dir, tmp_path):
    weights = _make_file(tmp_path, "w.bin", b"x")
    run = trackio.init(project="art-inst", name="p")
    art = Artifact(name="m", type="model")
    art.add_file(weights)
    logged = run.log_artifact(art)
    fetched = run.use_artifact(logged)
    assert fetched.version == "v0"
    assert fetched.name == "m"
    unlogged = Artifact(name="m2", type="model")
    with pytest.raises(ValueError, match="already been logged"):
        run.use_artifact(unlogged)
    trackio.finish()


def test_wait_digest_and_qualified_name(temp_dir, tmp_path):
    weights = _make_file(tmp_path, "w.bin", b"x")
    run = trackio.init(project="art-compat", name="p")
    art = Artifact(name="m", type="model")
    with pytest.raises(RuntimeError, match="Cannot wait"):
        art.wait()
    with pytest.raises(RuntimeError, match="no qualified name"):
        art.qualified_name
    art.add_file(weights)
    logged = run.log_artifact(art).wait()
    assert logged is art
    assert logged.digest == logged.manifest_digest
    assert logged.qualified_name == "art-compat/m:v0"
    assert run.use_artifact(f"m:{logged.version}").version == "v0"
    trackio.finish()


def test_metadata_mutation_before_log_is_persisted(temp_dir, tmp_path):
    weights = _make_file(tmp_path, "w.bin", b"x")
    run = trackio.init(project="art-md", name="p")
    art = Artifact(name="m", type="model")
    art.add_file(weights)
    art.metadata["acc"] = 0.9
    run.log_artifact(art)
    fetched = run.use_artifact("m")
    assert fetched.metadata == {"acc": 0.9}
    trackio.finish()


# --- module-level re-exports ---


def test_module_log_artifact_inside_run_equivalent_to_run_method(temp_dir, tmp_path):
    weights = _make_file(tmp_path, "w.bin", b"x")
    trackio.init(project="art-mod-log", name="p")
    art = trackio.Artifact(name="m", type="model")
    art.add_file(weights)
    logged = trackio.log_artifact(art, aliases=["best"])
    assert logged is art
    assert logged.version == "v0"
    assert "latest" in logged.aliases and "best" in logged.aliases
    trackio.finish()

    lineage = SQLiteStorage.get_run_artifacts("art-mod-log", "p", None)
    assert len(lineage["output"]) == 1


def test_module_use_artifact_inside_run_records_lineage(temp_dir, tmp_path):
    weights = _make_file(tmp_path, "w.bin", b"x")
    run = trackio.init(project="art-mod-use", name="p")
    art = trackio.Artifact(name="m", type="model")
    art.add_file(weights)
    run.log_artifact(art)
    trackio.finish()

    trackio.init(project="art-mod-use", name="c")
    fetched = trackio.use_artifact("m:latest")
    assert fetched.version == "v0"
    trackio.finish()

    lineage_c = SQLiteStorage.get_run_artifacts("art-mod-use", "c", None)
    assert len(lineage_c["input"]) == 1


def test_module_log_artifact_without_run_raises(temp_dir, tmp_path):
    weights = _make_file(tmp_path, "w.bin", b"x")
    art = trackio.Artifact(name="m", type="model")
    art.add_file(weights)
    with pytest.raises(RuntimeError, match="Call trackio.init"):
        trackio.log_artifact(art)


def test_module_log_artifact_after_finish_raises(temp_dir, tmp_path):
    weights = _make_file(tmp_path, "w.bin", b"x")
    trackio.init(project="art-mod-postfinish", name="p")
    trackio.finish()
    art = trackio.Artifact(name="m", type="model")
    art.add_file(weights)
    with pytest.raises(RuntimeError, match="Call trackio.init"):
        trackio.log_artifact(art)


def test_module_use_artifact_after_finish_raises(temp_dir, tmp_path):
    weights = _make_file(tmp_path, "w.bin", b"x")
    run = trackio.init(project="art-mod-use-postfinish", name="p")
    art = trackio.Artifact(name="m", type="model")
    art.add_file(weights)
    run.log_artifact(art)
    trackio.finish()
    with pytest.raises(RuntimeError, match="Call trackio.init"):
        trackio.use_artifact("m:latest")


def test_module_use_artifact_without_run_raises(temp_dir):
    with pytest.raises(RuntimeError, match="Call trackio.init"):
        trackio.use_artifact("m:latest")


def test_artifact_class_importable_from_package_root():
    from trackio import Artifact as TopLevelArtifact

    assert TopLevelArtifact is Artifact


def test_all_includes_new_exports():
    for name in ("Artifact", "log_artifact", "use_artifact"):
        assert name in trackio.__all__


def test_get_run_records_surfaces_producer_only_runs(temp_dir, tmp_path):
    weights = _make_file(tmp_path, "w.bin", b"data")

    metrics_run = trackio.init(project="art-runvis", name="metrics-run")
    metrics_run.log({"loss": 1.0})
    trackio.finish()

    producer = trackio.init(project="art-runvis", name="producer-run")
    art = Artifact(name="m", type="model")
    art.add_file(weights)
    producer.log_artifact(art)
    trackio.finish()

    consumer = trackio.init(project="art-runvis", name="consumer-run")
    consumer.use_artifact("m:latest")
    trackio.finish()

    names = {r["name"] for r in SQLiteStorage.get_run_records("art-runvis")}
    assert "metrics-run" in names
    assert "producer-run" in names
    assert "consumer-run" not in names


def test_get_run_records_does_not_duplicate_metric_and_producer_run(temp_dir, tmp_path):
    weights = _make_file(tmp_path, "w.bin", b"x")
    run = trackio.init(project="art-runvis2", name="both")
    run.log({"loss": 0.5})
    art = Artifact(name="m", type="model")
    art.add_file(weights)
    run.log_artifact(art)
    trackio.finish()

    matching = [
        r for r in SQLiteStorage.get_run_records("art-runvis2") if r["name"] == "both"
    ]
    assert len(matching) == 1
