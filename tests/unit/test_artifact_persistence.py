import os
from pathlib import Path

from trackio.sqlite_storage import SQLiteStorage


def _build_sample_artifacts(project):
    model_id = SQLiteStorage.create_or_get_artifact(
        project, "model", "model", "a model"
    )
    v0_id, _, _ = SQLiteStorage.insert_artifact_version(
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
    v1_id, _, _ = SQLiteStorage.insert_artifact_version(
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
    d0_id, _, _ = SQLiteStorage.insert_artifact_version(
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
