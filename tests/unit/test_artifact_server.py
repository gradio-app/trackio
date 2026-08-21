"""Focused coverage for the artifact endpoints used by the dashboard."""

import hashlib
import json
import sqlite3
import threading
from pathlib import Path

import trackio.sqlite_storage
from trackio import server
from trackio.sqlite_storage import SQLiteStorage

GOLDEN_LINEAGE_PATH = (
    Path(__file__).resolve().parents[2]
    / "trackio"
    / "frontend"
    / "src"
    / "lib"
    / "__fixtures__"
    / "lineage_golden.json"
)


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
    conn = sqlite3.connect(db_path)
    try:
        with conn:
            conn.execute(
                "INSERT INTO metrics (timestamp, run_id, run_name, step, metrics) "
                "VALUES (?, ?, ?, ?, ?)",
                ("2026-01-01T00:00:00+00:00", run_id, run_name, 0, "{}"),
            )
    finally:
        conn.close()


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


def _seed_golden_lineage(project="p"):
    fixture = json.loads(GOLDEN_LINEAGE_PATH.read_text())
    db_path = SQLiteStorage.init_db(project)
    with sqlite3.connect(db_path) as conn:
        for run in fixture["runs"]:
            conn.execute(
                "INSERT INTO metrics (timestamp, run_id, run_name, step, metrics) "
                "VALUES (?, ?, ?, ?, ?)",
                (run["created_at"], run["id"], run["name"], 0, "{}"),
            )
        for artifact in fixture["artifacts"]:
            conn.execute(
                "INSERT INTO artifacts (id, name, type, description, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    artifact["id"],
                    artifact["name"],
                    artifact["type"],
                    artifact["description"],
                    artifact["created_at"],
                ),
            )
        for version in fixture["artifact_versions"]:
            conn.execute(
                "INSERT INTO artifact_versions (id, artifact_id, version, "
                "manifest_digest, manifest, metadata, size_bytes, "
                "producer_run_id, producer_run_name, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    version["id"],
                    version["artifact_id"],
                    version["version"],
                    version["manifest_digest"],
                    json.dumps(version["manifest"]),
                    version["metadata"],
                    version["size_bytes"],
                    version["producer_run_id"],
                    version["producer_run_name"],
                    version["created_at"],
                ),
            )
        for alias in fixture["artifact_aliases"]:
            conn.execute(
                "INSERT INTO artifact_aliases (artifact_id, alias, "
                "artifact_version_id) VALUES (?, ?, ?)",
                (
                    alias["artifact_id"],
                    alias["alias"],
                    alias["artifact_version_id"],
                ),
            )
        for link in fixture["run_artifact_links"]:
            conn.execute(
                "INSERT INTO run_artifact_links (id, run_id, run_name, "
                "artifact_version_id, direction, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    link["id"],
                    link["run_id"],
                    link["run_name"],
                    link["artifact_version_id"],
                    link["direction"],
                    link["created_at"],
                ),
            )
    return fixture


def test_artifact_lineage_matches_golden_fixture(temp_dir):
    fixture = _seed_golden_lineage()
    result = SQLiteStorage.get_artifact_lineage("p", fixture["focus_version_id"])
    assert result == fixture["expected"]
    lineage_keys = {
        (node["run_id"], node["run_name"])
        for node in result["nodes"]
        if node["kind"] == "run"
    }
    count_keys = {
        (row["run_id"], row["run_name"])
        for row in SQLiteStorage.get_run_artifact_counts("p")
    }
    assert lineage_keys == count_keys


def test_artifact_lineage_handles_boundary_cases(temp_dir):
    _seed_golden_lineage()
    isolated = _commit(
        name="other", type="dataset", payload=b"other", run_name="solo", run_id="solo-1"
    )
    result = SQLiteStorage.get_artifact_lineage("p", isolated["version_id"])
    assert result["focus"] == f"art:{isolated['version_id']}"
    assert {node["id"] for node in result["nodes"]} == {
        f"art:{isolated['version_id']}",
        "run:solo-1",
    }
    assert len(result["edges"]) == 1

    db_path = SQLiteStorage.get_project_db_path("p")
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO artifact_versions (id, artifact_id, version, "
            "manifest_digest, manifest, metadata, size_bytes, "
            "producer_run_id, producer_run_name, created_at) "
            "VALUES (99, 1, 1, 'digest-orphan', '[]', NULL, 0, NULL, NULL, "
            "'2026-01-02T00:00:00+00:00')"
        )
    result = SQLiteStorage.get_artifact_lineage("p", 99)
    assert result["truncated"] is False
    assert result["edges"] == []
    assert len(result["nodes"]) == 1
    node = result["nodes"][0]
    assert node["id"] == "art:99"
    assert node["producer_run_id"] is None
    assert node["producer_run_name"] is None
    assert node["num_files"] == 0

    assert SQLiteStorage.get_artifact_lineage("nope", 1) == {
        "focus": "art:1",
        "truncated": False,
        "nodes": [],
        "edges": [],
    }
    result = SQLiteStorage.get_artifact_lineage("p", 12345)
    assert result["nodes"] == [] and result["edges"] == []


def test_artifact_lineage_canonicalizes_run_identities(temp_dir):
    _create_legacy_project_db("legacy")
    artifact = _commit(project="legacy", run_name="legacy-run", run_id="client-uuid")
    result = SQLiteStorage.get_artifact_lineage("legacy", artifact["version_id"])
    run_nodes = [node for node in result["nodes"] if node["kind"] == "run"]
    assert run_nodes == [
        {
            "id": "run:name:legacy-run",
            "kind": "run",
            "run_id": None,
            "run_name": "legacy-run",
            "created_at": run_nodes[0]["created_at"],
        }
    ]

    _insert_metrics_row("orphan", "train", "known-id")
    artifact = _commit(project="orphan", run_name="train", run_id=None)
    result = SQLiteStorage.get_artifact_lineage("orphan", artifact["version_id"])
    run_nodes = [node for node in result["nodes"] if node["kind"] == "run"]
    assert [node["id"] for node in run_nodes] == ["run:known-id"]
    assert run_nodes[0]["run_id"] == "known-id"

    artifact = _commit(project="dedupe")
    SQLiteStorage.insert_run_artifact_link(
        "dedupe", "producer", "other-id", artifact["version_id"], "output"
    )
    _insert_metrics_row("dedupe", "producer", "producer-id")
    result = SQLiteStorage.get_artifact_lineage("dedupe", artifact["version_id"])
    assert len(result["edges"]) == 1
    assert [node["id"] for node in result["nodes"] if node["kind"] == "run"] == [
        "run:producer-id"
    ]


def test_artifact_lineage_truncation_filters_dangling_edges(temp_dir, monkeypatch):
    fixture = _seed_golden_lineage()
    monkeypatch.setattr(trackio.sqlite_storage, "_MAX_LINEAGE_NODES", 3)
    result = SQLiteStorage.get_artifact_lineage("p", fixture["focus_version_id"])
    assert result["truncated"] is True
    node_ids = {node["id"] for node in result["nodes"]}
    assert len(node_ids) <= 3
    for edge in result["edges"]:
        assert edge["source"] in node_ids
        assert edge["target"] in node_ids


def test_artifact_lineage_row_budget_ignores_disconnected_history(
    temp_dir, monkeypatch
):
    focus = _commit()
    for index in range(20):
        _commit(
            name=f"unrelated-{index}",
            run_name=f"unrelated-run-{index}",
            run_id=f"unrelated-id-{index}",
        )

    monkeypatch.setattr(trackio.sqlite_storage, "_MAX_LINEAGE_LINK_ROWS", 3)
    result = SQLiteStorage.get_artifact_lineage("p", focus["version_id"])

    assert result["truncated"] is False
    assert {node["id"] for node in result["nodes"]} == {
        f"art:{focus['version_id']}",
        "run:producer-id",
    }
    assert len(result["edges"]) == 1


def test_artifact_lineage_budgets_cap_connected_fanout(temp_dir, monkeypatch):
    focus = _commit(project="row-budget", name="model-0")
    for index in range(1, 10):
        _commit(project="row-budget", name=f"model-{index}")

    monkeypatch.setattr(trackio.sqlite_storage, "_MAX_LINEAGE_LINK_ROWS", 4)
    result = SQLiteStorage.get_artifact_lineage("row-budget", focus["version_id"])

    assert result["truncated"] is True
    assert len(result["edges"]) <= 3

    monkeypatch.setattr(trackio.sqlite_storage, "_MAX_LINEAGE_LINK_ROWS", 10_000)
    focus = _commit(project="edge-budget", name="model-0")
    for index in range(1, 10):
        _commit(project="edge-budget", name=f"model-{index}")

    monkeypatch.setattr(trackio.sqlite_storage, "_MAX_LINEAGE_EDGES", 3)
    result = SQLiteStorage.get_artifact_lineage("edge-budget", focus["version_id"])

    assert result["truncated"] is True
    assert len(result["edges"]) == 3
    node_ids = {node["id"] for node in result["nodes"]}
    assert all(
        edge["source"] in node_ids and edge["target"] in node_ids
        for edge in result["edges"]
    )


def test_run_artifacts_does_not_deadlock_on_spaces(temp_dir, monkeypatch):
    """On Spaces, DB access goes through a non-reentrant per-DB lock; the
    run-id + run-name lookup used to re-enter it via get_run_records and
    deadlock the server."""
    artifact = _commit()
    _insert_metrics_row("p", "producer", "producer-id")
    monkeypatch.setenv("SYSTEM", "spaces")

    result: dict = {}

    def call():
        result["value"] = server.get_run_artifacts(
            "p", run="producer", run_id="producer-id"
        )

    worker = threading.Thread(target=call, daemon=True)
    worker.start()
    worker.join(timeout=10)
    try:
        assert not worker.is_alive(), "get_run_artifacts deadlocked on Spaces"
        assert [item["name"] for item in result["value"]["output"]] == ["m"]
        assert artifact["version"] == 0
    finally:
        trackio.sqlite_storage._close_all_persistent_connections()
