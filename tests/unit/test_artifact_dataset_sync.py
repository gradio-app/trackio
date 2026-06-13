"""Dataset-mode sync coverage for artifacts.

Dataset-backed Spaces persist data by exporting the SQLite DB to parquet and
rebuilding it from parquet on restart; the `.db` file itself is never
committed. These tests pin that artifact metadata survives that round-trip and
that `load_from_dataset` pulls artifact blobs back.
"""

import os
from pathlib import Path

from trackio.dummy_commit_scheduler import DummyCommitScheduler
from trackio.sqlite_storage import SQLiteStorage


def _build_sample_artifacts(project):
    model_id = SQLiteStorage.create_or_get_artifact(
        project, "model", "model", "a model"
    )
    v0_id, _ = SQLiteStorage.insert_artifact_version(
        project,
        model_id,
        [{"path": "w.bin", "digest": "a" * 64, "size": 5}],
        {"epoch": 1},
        "rid-train",
        "train",
    )
    SQLiteStorage.reassign_alias(project, model_id, "latest", v0_id)
    SQLiteStorage.insert_run_artifact_link(
        project, "train", "rid-train", v0_id, "output"
    )
    v1_id, _ = SQLiteStorage.insert_artifact_version(
        project,
        model_id,
        [{"path": "w.bin", "digest": "b" * 64, "size": 7}],
        {"epoch": 2},
        "rid-train",
        "train",
    )
    SQLiteStorage.reassign_alias(project, model_id, "latest", v1_id)
    SQLiteStorage.reassign_alias(project, model_id, "best", v1_id)
    SQLiteStorage.insert_run_artifact_link(
        project, "train", "rid-train", v1_id, "output"
    )
    SQLiteStorage.insert_run_artifact_link(project, "eval", "rid-eval", v1_id, "input")

    data_id = SQLiteStorage.create_or_get_artifact(project, "data", "dataset", None)
    d0_id, _ = SQLiteStorage.insert_artifact_version(
        project,
        data_id,
        [{"path": "d.csv", "digest": "c" * 64, "size": 3}],
        None,
        "rid-prep",
        "prep",
    )
    SQLiteStorage.reassign_alias(project, data_id, "latest", d0_id)
    SQLiteStorage.insert_run_artifact_link(project, "prep", "rid-prep", d0_id, "output")


def _snapshot(project):
    """Capture every artifact's per-version manifest record plus run lineage,
    so a parquet round-trip can be checked for exact equality. Versions are
    walked v0, v1, ... until absent; alias lists are sorted to stay
    order-insensitive."""
    snap = {"versions": {}, "manifests": {}, "lineage": {}}
    for name in ("data", "model"):
        latest = SQLiteStorage.get_artifact_manifest(project, name, None)
        if latest is None:
            continue
        latest["aliases"] = sorted(latest["aliases"])
        snap["manifests"][name] = latest
        versions = []
        v = 0
        while (
            record := SQLiteStorage.get_artifact_manifest(project, name, f"v{v}")
        ) is not None:
            record["aliases"] = sorted(record["aliases"])
            versions.append(record)
            v += 1
        snap["versions"][name] = versions
    for run_name, run_id in (
        ("train", "rid-train"),
        ("eval", "rid-eval"),
        ("prep", "rid-prep"),
    ):
        snap["lineage"][run_name] = SQLiteStorage.get_run_artifacts(
            project, run_name, run_id
        )
    return snap


def test_artifact_metadata_survives_parquet_roundtrip(temp_dir):
    SQLiteStorage.init_db("proj")
    SQLiteStorage.log(project="proj", run="train", metrics={"loss": 0.1})
    _build_sample_artifacts("proj")

    before = _snapshot("proj")
    assert set(before["manifests"]) == {"data", "model"}
    assert before["manifests"]["model"]["version"] == 1
    assert "best" in before["manifests"]["model"]["aliases"]
    assert len(before["lineage"]["train"]["output"]) == 2
    assert len(before["lineage"]["eval"]["input"]) == 1

    SQLiteStorage._dataset_import_attempted = True
    SQLiteStorage.export_to_parquet()

    db_path = SQLiteStorage.get_project_db_path("proj")
    for table in SQLiteStorage._ARTIFACT_PARQUET_TABLES:
        assert (Path(temp_dir) / f"{db_path.stem}_{table}.parquet").exists()

    os.unlink(db_path)
    SQLiteStorage.import_from_parquet()

    assert _snapshot("proj") == before


def test_artifact_only_project_survives_roundtrip(temp_dir):
    """A project with artifacts but no metrics has no metrics parquet, yet must
    still be rebuilt from its artifact parquet files."""
    aid = SQLiteStorage.create_or_get_artifact("artonly", "m", "model", None)
    vid, _ = SQLiteStorage.insert_artifact_version(
        "artonly", aid, [{"path": "a", "digest": "d" * 64, "size": 1}], None, None, "r"
    )
    SQLiteStorage.reassign_alias("artonly", aid, "latest", vid)

    SQLiteStorage._dataset_import_attempted = True
    SQLiteStorage.export_to_parquet()

    db_path = SQLiteStorage.get_project_db_path("artonly")
    os.unlink(db_path)
    SQLiteStorage.import_from_parquet()

    assert "artonly" in SQLiteStorage.get_projects()
    record = SQLiteStorage.get_artifact_manifest("artonly", "m", None)
    assert record is not None
    assert record["version"] == 0


def test_load_from_dataset_downloads_artifact_blobs(temp_dir, monkeypatch):
    from trackio import sqlite_storage as _ss

    monkeypatch.setenv("TRACKIO_DATASET_ID", "user/ds")
    monkeypatch.setenv("SPACE_REPO_NAME", "user/space")
    monkeypatch.delenv("TRACKIO_BUCKET_ID", raising=False)
    monkeypatch.setattr(_ss.SQLiteStorage, "_dataset_import_attempted", False)
    monkeypatch.setattr(
        _ss.SQLiteStorage, "get_scheduler", staticmethod(lambda: DummyCommitScheduler())
    )
    monkeypatch.setattr(
        _ss.SQLiteStorage, "import_from_parquet", staticmethod(lambda: None)
    )

    repo_files = [
        "proj.parquet",
        "proj_artifact_versions.parquet",
        "media/proj/run/img.png",
        "artifacts/proj/blobs/sha256/aa/" + "a" * 64,
        "proj.db",
        "README.md",
    ]

    class _FakeApi:
        def list_repo_files(self, repo_id, repo_type=None):
            return repo_files

    requested = []

    def _fake_download(dataset_id, file, repo_type=None, local_dir=None):
        requested.append(file)
        dest = Path(local_dir) / file
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"x")
        return str(dest)

    monkeypatch.setattr(_ss.hf, "HfApi", lambda: _FakeApi())
    monkeypatch.setattr(_ss.hf, "hf_hub_download", _fake_download)

    _ss.SQLiteStorage.load_from_dataset()

    assert "artifacts/proj/blobs/sha256/aa/" + "a" * 64 in requested
    assert "media/proj/run/img.png" in requested
    assert "proj.parquet" in requested
    assert "proj_artifact_versions.parquet" in requested
    assert "proj.db" not in requested
    assert "README.md" not in requested


def test_artifact_parquet_tables_match_schema(temp_dir):
    """Guard against silent schema drift: _ARTIFACT_PARQUET_TABLES must list
    every column of each artifact table, in order. A column added to the
    CREATE TABLE without updating this dict would otherwise be silently
    dropped on every dataset export/import round-trip."""
    import sqlite3

    SQLiteStorage.init_db("schemacheck")
    db_path = SQLiteStorage.get_project_db_path("schemacheck")
    conn = sqlite3.connect(str(db_path))
    try:
        for table, columns in SQLiteStorage._ARTIFACT_PARQUET_TABLES.items():
            actual = [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]
            assert actual == columns, f"{table}: parquet {columns} != schema {actual}"
    finally:
        conn.close()
