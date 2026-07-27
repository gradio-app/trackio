import os
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from trackio.doris_migration import migrate_sqlite_to_doris
from trackio.doris_storage import DorisStorage

REQUIRED_ENV = (
    "TRACKIO_DORIS_HOST",
    "TRACKIO_DORIS_DATABASE",
    "TRACKIO_DORIS_USER",
)


pytestmark = pytest.mark.skipif(
    any(not os.environ.get(name) for name in REQUIRED_ENV),
    reason="real Doris integration settings are not configured",
)


def test_core_evidence_round_trip_is_idempotent():
    project = "trackio-doris-integration"
    run = "core-evidence"
    run_id = "trackio-doris-integration-v1"
    timestamps = [
        "2026-07-26T11:20:00+00:00",
        "2026-07-26T11:20:01+00:00",
    ]
    payload = {
        "project": project,
        "run": run,
        "run_id": run_id,
        "metrics_list": [
            {
                "loss": 1.0,
                "tokens": 8,
                "rollout": {
                    "_type": "trackio.trace",
                    "messages": [
                        {"role": "user", "content": "test"},
                        {"role": "assistant", "content": "ok"},
                    ],
                    "metadata": {"reward": 1.0},
                },
            },
            {"loss": 0.5, "tokens": 16},
        ],
        "steps": [0, 1],
        "timestamps": timestamps,
        "log_ids": ["metric-0", "metric-1"],
        "config": {"engine": "doris"},
    }

    DorisStorage.bulk_log(**payload)
    DorisStorage.bulk_log(**payload)
    DorisStorage.bulk_log_system(
        project=project,
        run=run,
        run_id=run_id,
        metrics_list=[{"gpu/utilization": 50.0}],
        timestamps=["2026-07-26T11:20:00.500000+00:00"],
        log_ids=["system-0"],
    )
    DorisStorage.bulk_alert(
        project=project,
        run=run,
        run_id=run_id,
        titles=["qualification"],
        texts=["native Doris write/read"],
        levels=["INFO"],
        steps=[1],
        timestamps=["2026-07-26T11:20:02+00:00"],
        alert_ids=["alert-0"],
    )

    assert DorisStorage.get_log_count(project, run_id=run_id) == 2
    assert DorisStorage.get_logs(project, run_id=run_id)[-1]["loss"] == 0.5
    assert DorisStorage.get_run_config(project, run_id=run_id) == {"engine": "doris"}
    assert (
        DorisStorage.get_system_logs(project, run_id=run_id)[0]["gpu/utilization"]
        == 50.0
    )
    assert (
        DorisStorage.get_alerts(project, run_id=run_id)[0]["title"] == "qualification"
    )
    traces = DorisStorage.get_traces(project, run_id=run_id)
    assert len(traces) == 1
    assert traces[0]["metadata"]["reward"] == 1.0


def test_artifact_metadata_lineage_and_run_mutations():
    project = "trackio-doris-artifact-integration"
    producer_id = "producer-v1"
    manifest = [
        {
            "path": "adapter/config.json",
            "digest": "a" * 64,
            "size": 17,
        }
    ]

    first = DorisStorage.commit_artifact_version(
        project=project,
        name="adapter",
        type="model",
        description="qualification",
        manifest=manifest,
        metadata={"format": "peft"},
        aliases=["candidate"],
        run_name="producer",
        run_id=producer_id,
    )
    second = DorisStorage.commit_artifact_version(
        project=project,
        name="adapter",
        type="model",
        description="qualification",
        manifest=manifest,
        metadata={"format": "peft"},
        aliases=["candidate"],
        run_name="producer",
        run_id=producer_id,
    )
    assert first["version_id"] == second["version_id"]
    assert first["version"] == 0
    assert set(first["aliases"]) == {"candidate", "latest"}

    DorisStorage.insert_run_artifact_link(
        project=project,
        run_name="consumer",
        run_id="consumer-v1",
        version_id=first["version_id"],
        direction="input",
    )
    linked = DorisStorage.get_run_artifacts(project, "consumer", run_id="consumer-v1")
    assert linked["input"][0]["name"] == "adapter"
    assert (
        DorisStorage.get_artifact_consumers(project, first["version_id"])[0]["run_id"]
        == "consumer-v1"
    )

    mutation_id = "mutation-v1"
    DorisStorage.bulk_log(
        project=project,
        run="before",
        run_id=mutation_id,
        metrics_list=[{"value": 1}],
        steps=[0],
        timestamps=["2026-07-26T11:31:00+00:00"],
        log_ids=["mutation-0"],
        config={"state": "before"},
    )
    DorisStorage.rename_run(project, "before", "after", run_id=mutation_id)
    assert DorisStorage.get_logs(project, "after", run_id=mutation_id)[0]["value"] == 1
    assert DorisStorage.delete_run(project, "after", run_id=mutation_id)
    assert not DorisStorage.delete_run(project, "after", run_id=mutation_id)


def test_sqlite_copy_and_reconciliation(tmp_path):
    source = tmp_path / "trackio-doris-migration-integration.db"
    connection = sqlite3.connect(source)
    try:
        connection.execute(
            """
            CREATE TABLE metrics (
                id INTEGER PRIMARY KEY,
                run_id TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                run_name TEXT NOT NULL,
                step INTEGER NOT NULL,
                metrics TEXT NOT NULL,
                log_id TEXT,
                space_id TEXT
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE configs (
                id INTEGER PRIMARY KEY,
                run_id TEXT NOT NULL,
                run_name TEXT NOT NULL,
                config TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        connection.executemany(
            """
            INSERT INTO metrics
                (id, run_id, timestamp, run_name, step, metrics, log_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    1,
                    "migration-run-v1",
                    "2026-07-26T11:40:00+00:00",
                    "migration-run",
                    0,
                    '{"loss":1.0}',
                    "migration-log-0",
                ),
                (
                    2,
                    "migration-run-v1",
                    "2026-07-26T11:40:01+00:00",
                    "migration-run",
                    1,
                    '{"loss":0.5}',
                    "migration-log-1",
                ),
            ],
        )
        connection.execute(
            """
            INSERT INTO configs
                (id, run_id, run_name, config, created_at)
            VALUES (1, 'migration-run-v1', 'migration-run',
                    '{"engine":"sqlite"}',
                    '2026-07-26T11:40:00+00:00')
            """
        )
        connection.commit()
    finally:
        connection.close()

    receipt = migrate_sqlite_to_doris(
        source,
        tmp_path / "migration-receipt.json",
        batch_size=1,
    )
    assert receipt["verified"] is True
    project = source.stem
    assert DorisStorage.get_log_count(project, run_id="migration-run-v1") == 2
    assert DorisStorage.get_run_config(project, run_id="migration-run-v1") == {
        "engine": "sqlite"
    }

    verified = migrate_sqlite_to_doris(
        source,
        tmp_path / "verify-receipt.json",
        verify_only=True,
    )
    assert verified["verified"] is True


def test_concurrent_writers_and_project_isolation():
    project = "trackio-doris-concurrency"

    def write(writer: int) -> None:
        run_id = f"writer-{writer}"
        DorisStorage.bulk_log(
            project=project,
            run="shared-name",
            run_id=run_id,
            metrics_list=[{"writer": writer, "value": index} for index in range(25)],
            steps=list(range(25)),
            timestamps=[
                f"2026-07-26T12:{writer:02d}:{index:02d}+00:00" for index in range(25)
            ],
            log_ids=[f"writer-{writer}-log-{index}" for index in range(25)],
            config={"writer": writer},
        )

    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(write, range(4)))
    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(write, range(4)))

    records = DorisStorage.get_run_records(project)
    assert {record["id"] for record in records} == {
        "writer-0",
        "writer-1",
        "writer-2",
        "writer-3",
    }
    assert (
        sum(
            DorisStorage.get_log_count(project, run_id=f"writer-{writer}")
            for writer in range(4)
        )
        == 100
    )

    other_project = "trackio-doris-concurrency-other"
    DorisStorage.bulk_log(
        project=other_project,
        run="shared-name",
        run_id="writer-0",
        metrics_list=[{"value": 999}],
        steps=[0],
        timestamps=["2026-07-26T12:59:00+00:00"],
        log_ids=["other-project-log"],
    )
    assert DorisStorage.get_log_count(other_project, run_id="writer-0") == 1
    assert DorisStorage.get_log_count(project, run_id="writer-0") == 25
