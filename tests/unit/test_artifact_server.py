"""Focused coverage for the artifact endpoints used by the dashboard."""

import hashlib
import sqlite3

from trackio import server
from trackio.sqlite_storage import SQLiteStorage


def _commit(
    *,
    project="p",
    name="m",
    type="model",
    payload=b"weights",
    files=None,
    aliases=None,
    run_name="producer",
    run_id="producer-id",
):
    manifest = files or [
        {
            "path": "weights.bin",
            "digest": hashlib.sha256(payload).hexdigest(),
            "size": len(payload),
        }
    ]
    return SQLiteStorage.commit_artifact_version(
        project=project,
        name=name,
        type=type,
        description=None,
        manifest=manifest,
        metadata=None,
        aliases=aliases,
        run_name=run_name,
        run_id=run_id,
    )


def _insert_metrics_row(project, run_name, run_id):
    db_path = SQLiteStorage.init_db(project)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO metrics (timestamp, run_id, run_name, step, metrics) "
            "VALUES (?, ?, ?, ?, ?)",
            ("2026-01-01T00:00:00+00:00", run_id, run_name, 0, "{}"),
        )


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


def test_list_artifacts_groups_versions_and_aliases(temp_dir):
    _commit(payload=b"model-v0")
    _commit(payload=b"model-v1", aliases=["prod"])
    data_files = [
        {
            "path": "train.csv",
            "digest": hashlib.sha256(b"rows").hexdigest(),
            "size": 4,
        },
        {
            "path": "metadata.json",
            "digest": hashlib.sha256(b"metadata").hexdigest(),
            "size": 8,
        },
    ]
    _commit(name="data", type="dataset", files=data_files)

    artifacts = server.list_artifacts("p")
    assert [artifact["type"] for artifact in artifacts] == ["dataset", "model"]

    by_name = {artifact["name"]: artifact for artifact in artifacts}
    model = by_name["m"]
    assert model["num_versions"] == 2
    assert [version["version"] for version in model["versions"]] == [1, 0]
    assert sorted(model["versions"][0]["aliases"]) == ["latest", "prod"]
    assert model["versions"][1]["aliases"] == []

    data = by_name["data"]
    assert data["versions"][0]["num_files"] == 2
    assert "manifest" not in data["versions"][0]


def test_run_artifacts_and_consumers_expose_lineage(temp_dir):
    artifact = _commit()
    SQLiteStorage.insert_run_artifact_link(
        "p", "consumer", "consumer-id", artifact["version_id"], "input"
    )

    producer = server.get_run_artifacts("p", run="producer", run_id="producer-id")
    assert [item["name"] for item in producer["output"]] == ["m"]
    assert producer["input"] == []

    consumer = server.get_run_artifacts("p", run="consumer", run_id="consumer-id")
    assert [item["name"] for item in consumer["input"]] == ["m"]
    assert (
        server.get_artifact_consumers("p", artifact["version_id"])[0]["run_name"]
        == "consumer"
    )


def test_tab_availability_reflects_artifacts(temp_dir):
    assert server.get_tab_availability("p")["artifacts"] is False
    _commit()
    assert server.get_tab_availability("p")["artifacts"] is True


def test_artifact_only_run_can_be_renamed_and_deleted(temp_dir):
    _commit(run_name="old-name", run_id="run-id")
    assert any(
        record["name"] == "old-name" for record in SQLiteStorage.get_run_records("p")
    )

    SQLiteStorage.rename_run("p", "old-name", "new-name", run_id="run-id")
    names = {record["name"] for record in SQLiteStorage.get_run_records("p")}
    assert "new-name" in names and "old-name" not in names
    assert (
        SQLiteStorage.get_artifact_manifest("p", "m", "latest")["producer_run_name"]
        == "new-name"
    )

    assert SQLiteStorage.delete_run("p", "new-name", run_id="run-id") is True
    assert all(
        record["name"] != "new-name" for record in SQLiteStorage.get_run_records("p")
    )
    assert SQLiteStorage.get_run_artifacts("p", "new-name", "run-id") == {
        "input": [],
        "output": [],
    }


def test_run_records_merge_name_keyed_metrics_with_artifact_links(temp_dir):
    _insert_metrics_row("p", "train", "train")
    _commit(run_name="train", run_id="uuid-1")

    records = [
        record
        for record in SQLiteStorage.get_run_records("p")
        if record["name"] == "train"
    ]
    assert len(records) == 1


def test_run_artifacts_dedupe_legacy_and_modern_links(temp_dir):
    artifact = _commit(run_name="train", run_id=None)
    SQLiteStorage.insert_run_artifact_link(
        "p", "train", "run-id", artifact["version_id"], "output"
    )

    output = SQLiteStorage.get_run_artifacts("p", "train", "run-id")["output"]
    assert len(output) == 1
    assert sum(row["output"] for row in SQLiteStorage.get_run_artifact_counts("p")) == 1


def test_deleting_same_name_run_preserves_unowned_lineage(temp_dir):
    _commit(run_name="train", run_id=None)
    _insert_metrics_row("p", "train", "keep-id")
    _insert_metrics_row("p", "train", "gone-id")

    assert SQLiteStorage.delete_run("p", "train", run_id="gone-id") is True
    output = SQLiteStorage.get_run_artifacts("p", "train", None)["output"]
    assert [artifact["name"] for artifact in output] == ["m"]
    assert (
        SQLiteStorage.get_artifact_manifest("p", "m", "latest")["producer_run_name"]
        == "train"
    )


def test_legacy_metrics_db_resolves_artifact_links_by_name(temp_dir):
    _create_legacy_project_db("p")
    _commit(run_name="legacy-run", run_id="client-uuid")

    records = SQLiteStorage.get_run_records("p")
    assert [record["name"] for record in records] == ["legacy-run"]
    output = SQLiteStorage.get_run_artifacts("p", "legacy-run", records[0]["id"])[
        "output"
    ]
    assert [artifact["name"] for artifact in output] == ["m"]
    assert SQLiteStorage.get_run_artifact_counts("p") == [
        {
            "run_id": None,
            "run_name": "legacy-run",
            "input": 0,
            "output": 1,
        }
    ]
