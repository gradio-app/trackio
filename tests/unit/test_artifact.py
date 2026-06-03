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
    (base / "ab").mkdir(parents=True)
    (base / "ab" / "abcdef").write_bytes(b"x")
    (base / "12").mkdir(parents=True)
    (base / "12" / "123456").write_bytes(b"x")

    present = SQLiteStorage.list_artifact_blobs_present(
        "p", ["abcdef", "123456", "deadbeef"]
    )
    assert present == {"abcdef", "123456"}
    assert SQLiteStorage.list_artifact_blobs_present("p", []) == set()
