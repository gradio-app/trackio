import hashlib
import threading
from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest

import trackio
from trackio.artifact import Artifact
from trackio.cas import (
    HASH_CHUNK_SIZE,
    blob_path,
    hash_file,
    stage_blob_from_chunks,
    validate_aliases,
)
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


def test_validate_aliases_accepts_list_of_names():
    assert validate_aliases(None) == []
    assert validate_aliases([]) == []
    assert validate_aliases(["prod", "best-1", "v_2.0"]) == ["prod", "best-1", "v_2.0"]


@pytest.mark.parametrize(
    "aliases, match",
    [
        ("prod", "must be a list"),
        ([""], "non-empty string"),
        (["has space"], "must match"),
        (["v3"], "reserved for version pointers"),
        (["prod\n"], "must match"),
    ],
)
def test_validate_aliases_rejects(aliases, match):
    with pytest.raises(ValueError, match=match):
        validate_aliases(aliases)


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


def test_insert_run_artifact_link_keeps_distinct_null_run_names(temp_dir):
    aid = SQLiteStorage.create_or_get_artifact("p", "m", "model", None)
    vid, _, _ = SQLiteStorage.insert_artifact_version(
        "p", aid, [{"path": "a", "digest": "1", "size": 7}], None, None, "producer"
    )
    SQLiteStorage.insert_run_artifact_link("p", "consumerA", None, vid, "input")
    SQLiteStorage.insert_run_artifact_link("p", "consumerB", None, vid, "input")

    assert len(SQLiteStorage.get_run_artifacts("p", "consumerA", None)["input"]) == 1
    assert len(SQLiteStorage.get_run_artifacts("p", "consumerB", None)["input"]) == 1


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
