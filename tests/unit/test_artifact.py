import hashlib
from pathlib import Path

import pytest

import trackio
from trackio.artifact import Artifact
from trackio.cas import HASH_CHUNK_SIZE, blob_path, hash_file, stage_blob_from_chunks
from trackio.sqlite_storage import SQLiteStorage
from trackio.typehints import Sha256Digest


def test_canonical_manifest_digest_is_order_invariant_and_content_sensitive():
    ordered = [
        {"path": "weights.bin", "digest": "deadbeef", "size": 10},
        {"path": "config.json", "digest": "cafef00d", "size": 3},
    ]
    _, dig_ordered, size_ordered = SQLiteStorage._canonical_manifest(ordered)
    _, dig_reversed, size_reversed = SQLiteStorage._canonical_manifest(
        list(reversed(ordered))
    )
    assert dig_ordered == dig_reversed
    assert size_ordered == size_reversed == 13

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
    vid_1, v_1, created_1 = SQLiteStorage.insert_artifact_version(
        "p", aid, manifest, None, None, "run-a"
    )
    vid_2, v_2, created_2 = SQLiteStorage.insert_artifact_version(
        "p", aid, manifest, None, None, "run-b"
    )
    assert vid_1 == vid_2
    assert v_1 == v_2 == 0
    assert created_1 is True
    assert created_2 is False


def _commit_version(manifest, aliases=None, metadata=None, description=None):
    return SQLiteStorage.commit_artifact_version(
        project="p",
        name="m",
        type="model",
        description=description,
        manifest=manifest,
        metadata=metadata,
        aliases=aliases,
        run_name="r",
        run_id=None,
    )


def test_relog_older_content_does_not_regress_latest(temp_dir):
    a = [{"path": "w", "digest": "aaa", "size": 1}]
    b = [{"path": "w", "digest": "bbb", "size": 1}]
    _commit_version(a)
    _commit_version(b)
    _commit_version(a)
    latest = SQLiteStorage.resolve_artifact_version("p", "m", "latest")
    assert latest["version"] == 1


def test_relog_with_alias_tags_existing_version_without_moving_latest(temp_dir):
    a = [{"path": "w", "digest": "aaa", "size": 1}]
    b = [{"path": "w", "digest": "bbb", "size": 1}]
    _commit_version(a)
    _commit_version(b)
    _commit_version(a, aliases=["prod"])
    assert SQLiteStorage.resolve_artifact_version("p", "m", "latest")["version"] == 1
    assert SQLiteStorage.resolve_artifact_version("p", "m", "prod")["version"] == 0


def test_relog_older_content_does_not_regress_moving_alias(temp_dir):
    a = [{"path": "w", "digest": "aaa", "size": 1}]
    b = [{"path": "w", "digest": "bbb", "size": 1}]
    _commit_version(a)
    _commit_version(b, aliases=["prod"])
    _commit_version(a, aliases=["prod"])
    assert SQLiteStorage.resolve_artifact_version("p", "m", "prod")["version"] == 1
    assert SQLiteStorage.resolve_artifact_version("p", "m", "latest")["version"] == 1


def test_relog_newer_content_moves_alias_forward(temp_dir):
    a = [{"path": "w", "digest": "aaa", "size": 1}]
    b = [{"path": "w", "digest": "bbb", "size": 1}]
    _commit_version(a, aliases=["prod"])
    _commit_version(b)
    _commit_version(b, aliases=["prod"])
    assert SQLiteStorage.resolve_artifact_version("p", "m", "prod")["version"] == 1


def test_relog_identical_content_refreshes_metadata(temp_dir):
    a = [{"path": "w", "digest": "aaa", "size": 1}]
    assert _commit_version(a, metadata={"acc": 0.8})["metadata"] == {"acc": 0.8}
    second = _commit_version(a, metadata={"acc": 0.95})
    assert second["version"] == 0
    assert second["metadata"] == {"acc": 0.95}
    refetched = SQLiteStorage.get_artifact_manifest("p", "m", "v0")
    assert refetched["metadata"] == {"acc": 0.95}


def test_relog_without_metadata_keeps_existing(temp_dir):
    a = [{"path": "w", "digest": "aaa", "size": 1}]
    _commit_version(a, metadata={"acc": 0.8})
    _commit_version(a)
    assert SQLiteStorage.get_artifact_manifest("p", "m", "v0")["metadata"] == {
        "acc": 0.8
    }


def test_empty_metadata_normalized_to_absent(temp_dir):
    a = [{"path": "w", "digest": "aaa", "size": 1}]
    assert _commit_version(a, metadata={})["metadata"] is None


def test_relog_empty_metadata_does_not_wipe(temp_dir):
    a = [{"path": "w", "digest": "aaa", "size": 1}]
    _commit_version(a, metadata={"acc": 0.8})
    _commit_version(a, metadata={})
    assert SQLiteStorage.get_artifact_manifest("p", "m", "v0")["metadata"] == {
        "acc": 0.8
    }


def test_relog_refreshes_description(temp_dir):
    a = [{"path": "w", "digest": "aaa", "size": 1}]
    b = [{"path": "w", "digest": "bbb", "size": 1}]
    _commit_version(a, description="first")
    assert SQLiteStorage.get_artifact_manifest("p", "m", "v0")["description"] == "first"
    _commit_version(a, description="via dedup")
    assert (
        SQLiteStorage.get_artifact_manifest("p", "m", "v0")["description"]
        == "via dedup"
    )
    _commit_version(b, description="via new version")
    assert (
        SQLiteStorage.get_artifact_manifest("p", "m", "v1")["description"]
        == "via new version"
    )
    assert (
        SQLiteStorage.get_artifact_manifest("p", "m", "v0")["description"]
        == "via new version"
    )


def test_relog_without_description_keeps_existing(temp_dir):
    a = [{"path": "w", "digest": "aaa", "size": 1}]
    _commit_version(a, description="kept")
    _commit_version(a)
    assert SQLiteStorage.get_artifact_manifest("p", "m", "v0")["description"] == "kept"


def test_commit_artifact_version_is_atomic_on_bad_alias(temp_dir):
    # A reserved-vN alias raises mid-commit; the artifact/version/latest writes
    # that ran before it must roll back, leaving nothing behind.
    with pytest.raises(ValueError, match="reserved for version pointers"):
        SQLiteStorage.commit_artifact_version(
            project="p",
            name="m",
            type="model",
            description=None,
            manifest=[{"path": "w", "digest": "aaa", "size": 1}],
            metadata=None,
            aliases=["v9"],
            run_name="r",
            run_id=None,
        )
    assert SQLiteStorage.resolve_artifact_version("p", "m", "latest") is None
    assert SQLiteStorage.get_run_artifacts("p", "r", None) == {
        "input": [],
        "output": [],
    }
    # The DB is still usable: a subsequent good commit starts cleanly at v0.
    assert _commit_version([{"path": "w", "digest": "aaa", "size": 1}])["version"] == 0


def test_insert_artifact_version_increments(temp_dir):
    aid = SQLiteStorage.create_or_get_artifact("p", "m", "model", None)
    _, v_0, _ = SQLiteStorage.insert_artifact_version(
        "p", aid, [{"path": "a", "digest": "1", "size": 1}], None, None, "r"
    )
    _, v_1, _ = SQLiteStorage.insert_artifact_version(
        "p", aid, [{"path": "a", "digest": "2", "size": 1}], None, None, "r"
    )
    _, v_2, _ = SQLiteStorage.insert_artifact_version(
        "p", aid, [{"path": "a", "digest": "3", "size": 1}], None, None, "r"
    )
    assert (v_0, v_1, v_2) == (0, 1, 2)


def test_reassign_alias_rotates(temp_dir):
    aid = SQLiteStorage.create_or_get_artifact("p", "m", "model", None)
    vid_0, _, _ = SQLiteStorage.insert_artifact_version(
        "p", aid, [{"path": "a", "digest": "1", "size": 1}], None, None, "r"
    )
    vid_1, _, _ = SQLiteStorage.insert_artifact_version(
        "p", aid, [{"path": "a", "digest": "2", "size": 1}], None, None, "r"
    )
    SQLiteStorage.reassign_alias("p", aid, "latest", vid_0)
    SQLiteStorage.reassign_alias("p", aid, "latest", vid_1)
    resolved = SQLiteStorage.resolve_artifact_version("p", "m", "latest")
    assert resolved["version_id"] == vid_1
    assert resolved["version"] == 1


def test_reassign_alias_rejects_version_pointer(temp_dir):
    aid = SQLiteStorage.create_or_get_artifact("p", "m", "model", None)
    vid, _, _ = SQLiteStorage.insert_artifact_version(
        "p", aid, [{"path": "a", "digest": "1", "size": 1}], None, None, "r"
    )
    with pytest.raises(ValueError, match="reserved"):
        SQLiteStorage.reassign_alias("p", aid, "v3", vid)


def test_resolve_artifact_version_spec_grammar(temp_dir):
    aid = SQLiteStorage.create_or_get_artifact("p", "m", "model", None)
    vid_0, _, _ = SQLiteStorage.insert_artifact_version(
        "p", aid, [{"path": "a", "digest": "1", "size": 1}], None, None, "r"
    )
    vid_1, _, _ = SQLiteStorage.insert_artifact_version(
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
    vid, _, _ = SQLiteStorage.insert_artifact_version(
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
    vid, _, _ = SQLiteStorage.insert_artifact_version(
        "p", aid, [{"path": "a", "digest": "1", "size": 1}], None, None, "r"
    )
    with pytest.raises(ValueError, match="direction"):
        SQLiteStorage.insert_run_artifact_link("p", "r", None, vid, "sideways")


def test_get_artifact_manifest(temp_dir):
    aid = SQLiteStorage.create_or_get_artifact("p", "m", "model", None)
    manifest = [
        {"path": "weights.bin", "digest": "ab", "size": 5},
        {"path": "config.json", "digest": "cd", "size": 2},
    ]
    vid, _, _ = SQLiteStorage.insert_artifact_version(
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


def test_hash_file_modern_and_fallback_paths_agree(tmp_path, monkeypatch):
    p = tmp_path / "blob"
    payload = b"x" * (HASH_CHUNK_SIZE + 17) + b"trailing"
    p.write_bytes(payload)

    d_modern, s_modern = hash_file(p)

    monkeypatch.delattr("hashlib.file_digest", raising=False)
    d_fallback, s_fallback = hash_file(p)

    assert d_modern == d_fallback == hashlib.sha256(payload).hexdigest()
    assert s_modern == s_fallback == len(payload)


def test_stage_blob_overwrites_target_that_appears_after_guard(tmp_path):
    """A concurrent writer can create the target between the initial is_file()
    guard and the final rename. The staging must overwrite it atomically
    (os.replace), not raise as os.rename would on Windows."""
    payload = b"shared-content"
    digest = Sha256Digest(hashlib.sha256(payload).hexdigest())
    target = tmp_path / "blob"

    def _chunks():
        target.write_bytes(payload)
        yield payload

    stage_blob_from_chunks(_chunks(), claimed_digest=digest, target_path=target)
    assert target.read_bytes() == payload
    assert not any(p.name.startswith("blob.partial.") for p in tmp_path.iterdir())


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


def test_download_rejects_invalid_digest_in_manifest(temp_dir, tmp_path):
    a = _hydrated_artifact(
        "proj",
        "my-model",
        0,
        [{"path": "w.bin", "digest": "../../etc/passwd", "size": 5}],
    )
    with pytest.raises(ValueError, match="Invalid artifact blob digest"):
        a.download(tmp_path / "dl")
    assert not (tmp_path / "etc" / "passwd").exists()


def test_build_manifest_reads_each_source_once(temp_dir, tmp_path, monkeypatch):
    p = tmp_path / "w.bin"
    p.write_bytes(b"x" * (HASH_CHUNK_SIZE + 7))
    a = Artifact(name="m", type="model")
    a.add_file(p)
    target = p.resolve()

    reads = {"opens": 0}
    real_open = Path.open

    def counting_open(self, *args, **kwargs):
        mode = args[0] if args else kwargs.get("mode", "r")
        if self == target and "b" in mode and "r" in mode:
            reads["opens"] += 1
        return real_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", counting_open)
    manifest = a._build_manifest("proj")

    assert reads["opens"] == 1
    assert manifest[0]["digest"] == hashlib.sha256(p.read_bytes()).hexdigest()
    assert manifest[0]["size"] == HASH_CHUNK_SIZE + 7


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

    explicit = Artifact(name="m", type="model")
    explicit.add_file(p1, name="x")
    explicit.add_file(p2, name="x")
    with pytest.raises(ValueError, match="Duplicate logical path"):
        explicit._build_manifest("p")

    double_add = Artifact(name="m", type="model")
    double_add.add_file(p1)
    double_add.add_file(p1)
    with pytest.raises(ValueError, match="Duplicate logical path"):
        double_add._build_manifest("p")


def test_build_manifest_rejects_prefix_collision(temp_dir, tmp_path):
    p1 = tmp_path / "a"
    p2 = tmp_path / "b"
    p1.write_bytes(b"file")
    p2.write_bytes(b"child")

    file_then_dir = Artifact(name="m", type="model")
    file_then_dir.add_file(p1, name="sub")
    file_then_dir.add_file(p2, name="sub/x")
    with pytest.raises(ValueError, match="collides with"):
        file_then_dir._build_manifest("p")
    assert not blob_path("p", hashlib.sha256(b"file").hexdigest()).is_file()

    dir_then_file = Artifact(name="m", type="model")
    dir_then_file.add_file(p1, name="sub/x")
    dir_then_file.add_file(p2, name="sub")
    with pytest.raises(ValueError, match="collides with"):
        dir_then_file._build_manifest("p")

    deep = Artifact(name="m", type="model")
    deep.add_file(p1, name="a/b")
    deep.add_file(p2, name="a/b/c")
    with pytest.raises(ValueError, match="collides with"):
        deep._build_manifest("p")


def test_build_manifest_allows_sibling_paths(temp_dir, tmp_path):
    p1 = tmp_path / "a"
    p2 = tmp_path / "b"
    p1.write_bytes(b"a")
    p2.write_bytes(b"b")

    art = Artifact(name="m", type="model")
    art.add_file(p1, name="a/b")
    art.add_file(p2, name="a/c")
    manifest = art._build_manifest("p")
    assert {e["path"] for e in manifest} == {"a/b", "a/c"}


def test_assert_manifest_paths_compatible():
    from trackio import cas

    cas.assert_manifest_paths_compatible(["a/b", "a/c", "d"])
    with pytest.raises(ValueError, match="Duplicate logical path"):
        cas.assert_manifest_paths_compatible(["x", "x"])
    with pytest.raises(ValueError, match="collides with"):
        cas.assert_manifest_paths_compatible(["sub", "sub/x"])
    with pytest.raises(ValueError, match="collides with"):
        cas.assert_manifest_paths_compatible(["a/b/c", "a/b"])


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


def test_build_manifest_writes_correct_blob_and_copies_source(temp_dir, tmp_path):
    payload = b"abc"
    p = tmp_path / "x"
    p.write_bytes(payload)
    a = Artifact(name="m", type="model")
    a.add_file(p)
    manifest = a._build_manifest("p")
    assert manifest[0]["path"] == "x"
    assert manifest[0]["size"] == len(payload)
    digest = manifest[0]["digest"]
    assert digest == hashlib.sha256(payload).hexdigest()
    blob = Path(temp_dir) / "artifacts" / "p" / "blobs" / "sha256" / digest[:2] / digest
    assert blob.is_file()
    assert blob.read_bytes() == payload

    p.write_bytes(b"mutated!")
    assert blob.read_bytes() == payload
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


def test_download_default_root_includes_name_and_version(
    temp_dir, tmp_path, monkeypatch
):
    digest, size = _stage_blob(temp_dir, "proj", b"x")
    monkeypatch.chdir(tmp_path)
    for version in (0, 3):
        a = _hydrated_artifact(
            "proj",
            "my-model",
            version,
            [{"path": "w.bin", "digest": Sha256Digest(digest), "size": size}],
        )
        out = a.download()
        assert (
            Path(out).resolve()
            == (tmp_path / "artifacts" / "proj" / f"my-model_v{version}").resolve()
        )
        assert (Path(out) / "w.bin").read_bytes() == b"x"


def test_download_default_root_disambiguates_by_project(
    temp_dir, tmp_path, monkeypatch
):
    digest_a, size_a = _stage_blob(temp_dir, "proj-a", b"a-bytes")
    digest_b, size_b = _stage_blob(temp_dir, "proj-b", b"b-different-bytes")
    monkeypatch.chdir(tmp_path)

    art_a = _hydrated_artifact(
        "proj-a",
        "m",
        0,
        [{"path": "w.bin", "digest": Sha256Digest(digest_a), "size": size_a}],
    )
    art_b = _hydrated_artifact(
        "proj-b",
        "m",
        0,
        [{"path": "w.bin", "digest": Sha256Digest(digest_b), "size": size_b}],
    )

    out_a = art_a.download()
    out_b = art_b.download()

    assert Path(out_a).resolve() != Path(out_b).resolve()
    assert (Path(out_a) / "w.bin").read_bytes() == b"a-bytes"
    assert (Path(out_b) / "w.bin").read_bytes() == b"b-different-bytes"


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


def test_download_refreshes_same_size_in_place_edit(temp_dir, tmp_path):
    import os

    digest, size = _stage_blob(temp_dir, "proj", b"abc")
    a = _hydrated_artifact(
        "proj",
        "my-model",
        0,
        [{"path": "w.bin", "digest": Sha256Digest(digest), "size": size}],
    )
    dl = tmp_path / "dl"
    out = a.download(dl)
    file = Path(out) / "w.bin"
    file.write_bytes(b"XYZ")
    st = file.stat()
    os.utime(file, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))
    a.download(dl)
    assert file.read_bytes() == b"abc"


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


def test_canonical_project_name_collapses_to_db_stem():
    from trackio.utils import canonical_project_name

    assert canonical_project_name("my.model") == "mymodel"
    assert canonical_project_name("mymodel") == "mymodel"
    assert canonical_project_name("bert.base") == "bertbase"
    assert canonical_project_name("...") == "default"
    stem = SQLiteStorage.get_project_db_filename("my.model").removesuffix(".db")
    assert stem == canonical_project_name("my.model")


def test_blob_path_matches_db_canonicalization(temp_dir):
    digest = "a" * 64
    assert blob_path("my.model", digest) == blob_path("mymodel", digest)
    assert "mymodel" in blob_path("my.model", digest).parts
    assert "my.model" not in blob_path("my.model", digest).parts


def test_project_artifacts_dir_canonicalizes(temp_dir):
    from trackio.utils import project_artifacts_dir

    assert project_artifacts_dir("my.model") == project_artifacts_dir("mymodel")
    assert project_artifacts_dir("my.model").name == "mymodel"
    assert blob_path("my.model", "a" * 64).is_relative_to(
        project_artifacts_dir("my.model")
    )


def test_dotted_project_blob_resolves_under_canonical_db(temp_dir, tmp_path):
    weights = _make_file(tmp_path, "weights.bin", b"hello")
    run = trackio.init(project="my.model", name="producer")
    art = Artifact(name="m", type="model")
    art.add_file(weights)
    run.log_artifact(art)
    trackio.finish()

    run2 = trackio.init(project="mymodel", name="consumer")
    fetched = run2.use_artifact("m:latest")
    out = fetched.download(tmp_path / "dl")
    assert (Path(out) / "weights.bin").read_bytes() == b"hello"
    trackio.finish()


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
    assert (
        Path(out).resolve()
        == (tmp_path / "artifacts" / "art-spec-dl" / "m_v0").resolve()
    )
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


def test_module_log_artifact_without_active_run_raises(temp_dir, tmp_path):
    weights = _make_file(tmp_path, "w.bin", b"x")

    def _attempt():
        art = trackio.Artifact(name="m", type="model")
        art.add_file(weights)
        with pytest.raises(RuntimeError, match="Call trackio.init"):
            trackio.log_artifact(art)

    _attempt()
    trackio.init(project="art-mod-postfinish", name="p")
    trackio.finish()
    _attempt()


def test_module_use_artifact_without_active_run_raises(temp_dir, tmp_path):
    with pytest.raises(RuntimeError, match="Call trackio.init"):
        trackio.use_artifact("m:latest")

    run = trackio.init(project="art-mod-use-postfinish", name="p")
    weights = _make_file(tmp_path, "w.bin", b"x")
    art = trackio.Artifact(name="m", type="model")
    art.add_file(weights)
    run.log_artifact(art)
    trackio.finish()
    with pytest.raises(RuntimeError, match="Call trackio.init"):
        trackio.use_artifact("m:latest")


def test_package_exports_artifact_api():
    from trackio import Artifact as TopLevelArtifact

    assert TopLevelArtifact is Artifact
    for name in ("Artifact", "log_artifact", "use_artifact"):
        assert name in trackio.__all__
