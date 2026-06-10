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
    vid_1, v_1, new_1 = SQLiteStorage.insert_artifact_version(
        "p", aid, manifest, None, None, "run-a"
    )
    vid_2, v_2, new_2 = SQLiteStorage.insert_artifact_version(
        "p", aid, manifest, None, None, "run-b"
    )
    assert new_1 is True and new_2 is False
    assert vid_1 == vid_2
    assert v_1 == v_2 == 0


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


def test_list_artifacts_and_versions(temp_dir):
    aid = SQLiteStorage.create_or_get_artifact("p", "m", "model", "weights")
    vid_0, _, _ = SQLiteStorage.insert_artifact_version(
        "p", aid, [{"path": "a", "digest": "1", "size": 11}], {"acc": 0.5}, None, "r0"
    )
    vid_1, _, _ = SQLiteStorage.insert_artifact_version(
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
    SQLiteStorage.enqueue_artifact_blob_upload(
        project="p",
        space_id="sp",
        digest="dead",
        local_blob_path="/tmp/blob",
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


# --- Phase 4 — Artifact class ---

import errno
import hashlib
import os
import shutil
from pathlib import Path

from trackio.artifact import _HASH_CHUNK_SIZE, Artifact, _hash_file
from trackio.typehints import Sha256Digest


def test_hash_file_is_deterministic_and_correct_size(tmp_path):
    p = tmp_path / "x"
    payload = b"hello world"
    p.write_bytes(payload)
    d1, s1 = _hash_file(p)
    d2, s2 = _hash_file(p)
    assert d1 == d2 == hashlib.sha256(payload).hexdigest()
    assert s1 == s2 == len(payload)


def test_hash_file_handles_larger_than_chunk(tmp_path):
    p = tmp_path / "big"
    payload = b"a" * (_HASH_CHUNK_SIZE + 17)
    p.write_bytes(payload)
    d, s = _hash_file(p)
    assert s == len(payload)
    assert d == hashlib.sha256(payload).hexdigest()


def test_hash_file_modern_and_fallback_paths_agree(tmp_path, monkeypatch):
    p = tmp_path / "blob"
    payload = b"x" * (_HASH_CHUNK_SIZE + 17) + b"trailing"
    p.write_bytes(payload)

    d_modern, s_modern = _hash_file(p)

    monkeypatch.delattr("hashlib.file_digest", raising=False)
    d_fallback, s_fallback = _hash_file(p)

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
    with pytest.raises(AttributeError, match="read-only"):
        a.name = "other"


def test_artifact_metadata_defensive_copy():
    md = {"k": 1}
    a = Artifact(name="m", type="model", metadata=md)
    md["k"] = 999
    assert a.metadata == {"k": 1}
    out = a.metadata
    out["k"] = 999
    assert a.metadata == {"k": 1}


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


def test_build_manifest_cross_device_fallback(temp_dir, tmp_path, monkeypatch):
    p = tmp_path / "x"
    p.write_bytes(b"abc")
    calls = {"link": 0, "copy2": 0}
    real_copy2 = shutil.copy2

    def fake_link(src, dst):
        calls["link"] += 1
        raise OSError(errno.EXDEV, "cross-device link not permitted")

    def fake_copy2(src, dst):
        calls["copy2"] += 1
        real_copy2(src, dst)

    monkeypatch.setattr("trackio.artifact.os.link", fake_link)
    monkeypatch.setattr("trackio.artifact.shutil.copy2", fake_copy2)
    a = Artifact(name="m", type="model")
    a.add_file(p)
    manifest = a._build_manifest("p")
    assert calls["link"] == 1
    assert calls["copy2"] == 1
    digest = manifest[0]["digest"]
    blob = Path(temp_dir) / "artifacts" / "p" / "blobs" / "sha256" / digest[:2] / digest
    assert blob.is_file()
    assert blob.read_bytes() == b"abc"


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
        spec="latest",
        description="hydrated",
        metadata={"acc": 0.9},
    )
    assert a.version == 2
    assert a.aliases == ("latest", "best")
    assert a.size == 3
    assert a.manifest_digest == "def"
    assert a.manifest == [{"path": "x", "digest": "abc", "size": 3}]
    assert a.description == "hydrated"
    assert a.metadata == {"acc": 0.9}
    assert a.project == "proj"
    assert a._spec == "latest"
    assert a._logged is True


# --- Phase 5 — Artifact.download() local-only ---


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
    spec: str | None = None,
) -> Artifact:
    a = Artifact(name=name, type="model")
    a._hydrate_from_db(
        project=project,
        version=version,
        aliases=["latest"],
        manifest=entries,
        manifest_digest=Sha256Digest("0" * 64),
        size_bytes=sum(e["size"] for e in entries),
        spec=spec,
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
        spec="latest",
    )
    monkeypatch.chdir(tmp_path)
    out = a.download()
    assert Path(out).resolve() == (tmp_path / "artifacts" / "my-model:latest").resolve()
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
    assert Path(out).resolve() == (tmp_path / "artifacts" / "my-model:v3").resolve()


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


def test_download_cross_device_fallback(temp_dir, tmp_path, monkeypatch):
    digest, size = _stage_blob(temp_dir, "proj", b"abc")
    a = _hydrated_artifact(
        "proj",
        "my-model",
        0,
        [{"path": "w.bin", "digest": Sha256Digest(digest), "size": size}],
    )
    calls = {"link": 0, "copy2": 0}
    real_copy2 = shutil.copy2

    def fake_link(src, dst):
        calls["link"] += 1
        raise OSError(errno.EXDEV, "cross-device")

    def fake_copy2(src, dst):
        calls["copy2"] += 1
        real_copy2(src, dst)

    monkeypatch.setattr("trackio.artifact.os.link", fake_link)
    monkeypatch.setattr("trackio.artifact.shutil.copy2", fake_copy2)

    out = a.download(tmp_path / "dl")
    assert calls["link"] == 1
    assert calls["copy2"] == 1
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


# --- Phase 6 — Run.log_artifact / Run.use_artifact (local mode only) ---

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
    assert logged.version == 0
    assert "latest" in logged.aliases
    assert logged.project == "art-rt"
    trackio.finish()

    run2 = trackio.init(project="art-rt", name="consumer")
    fetched = run2.use_artifact("my-model:latest")
    assert fetched.version == 0
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
    assert logged_a.version == 0
    trackio.finish()

    run_b = trackio.init(project="art-dedup", name="run_b")
    art_b = Artifact(name="m", type="model")
    art_b.add_file(weights)
    logged_b = run_b.log_artifact(art_b)
    assert logged_b.version == 0
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
    assert logged_a.version == 0
    trackio.finish()

    run_b = trackio.init(project="art-rotate", name="r2")
    art_b = Artifact(name="m", type="model")
    art_b.add_file(p2)
    logged_b = run_b.log_artifact(art_b, aliases=["best"])
    assert logged_b.version == 1

    fetched_best = run_b.use_artifact("m:best")
    assert fetched_best.version == 1
    fetched_v0 = run_b.use_artifact("m:v0")
    assert fetched_v0.version == 0
    trackio.finish()


def test_use_artifact_spec_parsing(temp_dir, tmp_path):
    weights = _make_file(tmp_path, "w.bin", b"x")
    run = trackio.init(project="art-spec", name="p")
    art = Artifact(name="m", type="model")
    art.add_file(weights)
    run.log_artifact(art, aliases=["best"])

    assert run.use_artifact("m").version == 0
    assert run.use_artifact("m:latest").version == 0
    assert run.use_artifact("m:best").version == 0
    assert run.use_artifact("m:v0").version == 0
    trackio.finish()


def test_use_artifact_missing_raises(temp_dir):
    run = trackio.init(project="art-missing", name="p")
    with pytest.raises(ValueError, match="not found"):
        run.use_artifact("nonexistent")
    with pytest.raises(ValueError, match="not found"):
        run.use_artifact("nonexistent:v0")
    trackio.finish()


def test_use_artifact_preserves_spec_for_download(temp_dir, tmp_path, monkeypatch):
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
    assert Path(out).resolve() == (tmp_path / "artifacts" / "m:best").resolve()
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


# --- Phase 7 — Module-level re-exports + project-context use_artifact ---


def test_module_log_artifact_inside_run_equivalent_to_run_method(temp_dir, tmp_path):
    weights = _make_file(tmp_path, "w.bin", b"x")
    trackio.init(project="art-mod-log", name="p")
    art = trackio.Artifact(name="m", type="model")
    art.add_file(weights)
    logged = trackio.log_artifact(art, aliases=["best"])
    assert logged is art
    assert logged.version == 0
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
    assert fetched.version == 0
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
