"""Copy and reconcile Trackio project databases into Apache Doris."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import defaultdict
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Iterator

import orjson

from trackio.doris_storage import DorisStorage
from trackio.utils import deserialize_values

AUTHORITATIVE_TABLES = (
    "metrics",
    "configs",
    "system_metrics",
    "traces",
    "alerts",
    "project_metadata",
    "artifacts",
    "artifact_versions",
    "artifact_aliases",
    "run_artifact_links",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _tables(connection: sqlite3.Connection) -> set[str]:
    return {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }


def _rows(connection: sqlite3.Connection, table: str) -> list[dict[str, Any]]:
    if table not in _tables(connection):
        return []
    return [dict(row) for row in connection.execute(f"SELECT * FROM {table}")]


def _decode(value: Any, default: Any) -> Any:
    if value is None:
        return default
    return deserialize_values(orjson.loads(value))


def _canonical_json(value: Any, default: Any) -> Any:
    if value is None:
        return default
    return orjson.loads(value)


def _canonical_evidence(records: list[dict[str, Any]]) -> dict[str, Any]:
    encoded = [orjson.dumps(record, option=orjson.OPT_SORT_KEYS) for record in records]
    encoded.sort()
    digest = hashlib.sha256()
    for record in encoded:
        digest.update(len(record).to_bytes(8, "big"))
        digest.update(record)
    return {"count": len(encoded), "sha256": digest.hexdigest()}


def _records_evidence(
    records: dict[str, list[dict[str, Any]]],
) -> dict[str, dict[str, Any]]:
    return {
        table: _canonical_evidence(records.get(table, []))
        for table in AUTHORITATIVE_TABLES
    }


@contextmanager
def _sqlite_snapshot(db_path: Path) -> Iterator[tuple[Path, dict[str, Any]]]:
    """Yield a consistent read-only backup, including committed WAL records."""

    if not db_path.is_file():
        raise FileNotFoundError(f"Trackio project database not found: {db_path}")
    source_stat = db_path.stat()
    wal_path = Path(f"{db_path}-wal")
    metadata = {
        "source_file_sha256": _sha256(db_path),
        "source_file_bytes": source_stat.st_size,
        "source_file_mtime_ns": source_stat.st_mtime_ns,
        "wal_present": wal_path.is_file(),
    }
    with TemporaryDirectory(prefix="trackio-doris-snapshot-") as directory:
        snapshot = Path(directory) / db_path.name
        source = sqlite3.connect(
            f"{db_path.resolve().as_uri()}?mode=ro",
            uri=True,
            timeout=30,
        )
        target = sqlite3.connect(snapshot)
        try:
            source.execute("PRAGMA query_only = ON")
            source.backup(target)
            target.commit()
        finally:
            target.close()
            source.close()
        metadata["snapshot_sha256"] = _sha256(snapshot)
        metadata["snapshot_bytes"] = snapshot.stat().st_size
        yield snapshot, metadata


def _source_records(
    connection: sqlite3.Connection,
) -> dict[str, list[dict[str, Any]]]:
    metrics = [
        {
            "run_id": str(row.get("run_id") or row["run_name"]),
            "timestamp": str(row["timestamp"]),
            "run_name": str(row["run_name"]),
            "step": int(row["step"]),
            "metrics": _canonical_json(row["metrics"], {}),
            "log_id": row.get("log_id"),
            "space_id": row.get("space_id"),
        }
        for row in _rows(connection, "metrics")
    ]
    configs = [
        {
            "run_id": str(row.get("run_id") or row["run_name"]),
            "run_name": str(row["run_name"]),
            "config": _canonical_json(row["config"], {}),
            "created_at": str(row["created_at"]),
        }
        for row in _rows(connection, "configs")
    ]
    system_metrics = [
        {
            "run_id": str(row.get("run_id") or row["run_name"]),
            "timestamp": str(row["timestamp"]),
            "run_name": str(row["run_name"]),
            "metrics": _canonical_json(row["metrics"], {}),
            "log_id": row.get("log_id"),
            "space_id": row.get("space_id"),
        }
        for row in _rows(connection, "system_metrics")
    ]
    traces = [
        {
            "trace_id": str(row["id"]),
            "run_id": str(row.get("run_id") or row["run_name"]),
            "timestamp": str(row["timestamp"]),
            "run_name": str(row["run_name"]),
            "step": int(row["step"]),
            "metric_key": str(row["key"]),
            "trace_index": row.get("trace_index"),
            "messages": _canonical_json(row["messages"], []),
            "metadata": _canonical_json(row["metadata"], {}),
            "search_text": str(row.get("search_text") or ""),
            "log_id": row.get("log_id"),
            "space_id": row.get("space_id"),
            "trace_type": str(row.get("trace_type") or "trackio"),
            "external_id": row.get("external_id"),
            "schema_version": row.get("schema_version"),
            "payload": _canonical_json(row.get("payload"), None),
        }
        for row in _rows(connection, "traces")
    ]
    alerts = [
        {
            "run_id": str(row.get("run_id") or row["run_name"]),
            "timestamp": str(row["timestamp"]),
            "run_name": str(row["run_name"]),
            "title": str(row["title"]),
            "text": row.get("text"),
            "level": str(row["level"]),
            "step": row.get("step"),
            "alert_id": row.get("alert_id"),
        }
        for row in _rows(connection, "alerts")
    ]
    project_metadata = [
        {"key": str(row["key"]), "value": str(row["value"])}
        for row in _rows(connection, "project_metadata")
    ]

    source_artifacts = _rows(connection, "artifacts")
    artifacts_by_id = {int(row["id"]): row for row in source_artifacts}
    artifacts = [
        {
            "name": str(row["name"]),
            "type": str(row["type"]),
            "description": row.get("description"),
            "created_at": str(row["created_at"]),
        }
        for row in source_artifacts
    ]
    source_versions = _rows(connection, "artifact_versions")
    versions_by_id = {int(row["id"]): row for row in source_versions}
    artifact_versions = []
    for row in source_versions:
        artifact = artifacts_by_id.get(int(row["artifact_id"]))
        if artifact is None:
            raise RuntimeError("artifact version references a missing artifact")
        manifest = _canonical_json(row["manifest"], [])
        canonical_manifest, manifest_digest, size_bytes = (
            DorisStorage._canonical_manifest(manifest)
        )
        if manifest_digest != str(row["manifest_digest"]):
            raise RuntimeError(
                "source artifact version manifest digest is inconsistent"
            )
        if size_bytes != int(row["size_bytes"]):
            raise RuntimeError("source artifact version size is inconsistent")
        artifact_versions.append(
            {
                "artifact_name": str(artifact["name"]),
                "version": int(row["version"]),
                "manifest_digest": manifest_digest,
                "manifest": canonical_manifest,
                "metadata": _canonical_json(row.get("metadata"), None),
                "size_bytes": int(row["size_bytes"]),
                "producer_run_id": row.get("producer_run_id"),
                "producer_run_name": row.get("producer_run_name"),
                "created_at": str(row["created_at"]),
            }
        )
    artifact_aliases = []
    for row in _rows(connection, "artifact_aliases"):
        artifact = artifacts_by_id.get(int(row["artifact_id"]))
        version = versions_by_id.get(int(row["artifact_version_id"]))
        if artifact is None or version is None:
            raise RuntimeError("artifact alias references missing artifact data")
        if int(version["artifact_id"]) != int(row["artifact_id"]):
            raise RuntimeError(
                "artifact alias references a version from another artifact"
            )
        artifact_aliases.append(
            {
                "artifact_name": str(artifact["name"]),
                "alias": str(row["alias"]),
                "version": int(version["version"]),
            }
        )
    run_artifact_links = []
    for row in _rows(connection, "run_artifact_links"):
        version = versions_by_id.get(int(row["artifact_version_id"]))
        if version is None:
            raise RuntimeError(
                "run artifact link references a missing artifact version"
            )
        artifact = artifacts_by_id.get(int(version["artifact_id"]))
        if artifact is None:
            raise RuntimeError("run artifact link references a missing artifact")
        run_artifact_links.append(
            {
                "run_id": row.get("run_id"),
                "run_name": row.get("run_name"),
                "artifact_name": str(artifact["name"]),
                "version": int(version["version"]),
                "direction": str(row["direction"]),
                "created_at": str(row["created_at"]),
            }
        )
    return {
        "metrics": metrics,
        "configs": configs,
        "system_metrics": system_metrics,
        "traces": traces,
        "alerts": alerts,
        "project_metadata": project_metadata,
        "artifacts": artifacts,
        "artifact_versions": artifact_versions,
        "artifact_aliases": artifact_aliases,
        "run_artifact_links": run_artifact_links,
    }


def _inspect_sqlite_snapshot(
    snapshot_path: Path,
    source_path: Path,
    snapshot_metadata: dict[str, Any],
) -> dict[str, Any]:
    connection = sqlite3.connect(
        f"{snapshot_path.resolve().as_uri()}?mode=ro&immutable=1",
        uri=True,
    )
    connection.row_factory = sqlite3.Row
    try:
        tables = _tables(connection)
        counts = {
            table: int(
                connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            )
            for table in sorted(tables)
            if not table.startswith("sqlite_")
        }
        runs = set()
        for table in ("metrics", "configs", "system_metrics", "traces", "alerts"):
            if table not in tables:
                continue
            for row in connection.execute(f"SELECT * FROM {table}"):
                runs.add(
                    str(row["run_id"] if "run_id" in row.keys() else row["run_name"])
                )
        evidence = _records_evidence(_source_records(connection))
    finally:
        connection.close()
    return {
        "project": source_path.stem,
        "path": str(source_path),
        "sha256": snapshot_metadata["snapshot_sha256"],
        "bytes": snapshot_metadata["snapshot_bytes"],
        **snapshot_metadata,
        "tables": counts,
        "run_count": len(runs),
        "evidence": evidence,
    }


def inspect_sqlite_project(db_path: Path) -> dict[str, Any]:
    with _sqlite_snapshot(db_path) as (snapshot, metadata):
        return _inspect_sqlite_snapshot(snapshot, db_path, metadata)


def _migrate_project(
    db_path: Path,
    project: str,
    batch_size: int,
) -> dict[str, Any]:
    connection = sqlite3.connect(
        f"{db_path.resolve().as_uri()}?mode=ro&immutable=1",
        uri=True,
    )
    connection.row_factory = sqlite3.Row
    migrated: dict[str, int] = defaultdict(int)
    try:
        metrics_by_run: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for row in _rows(connection, "metrics"):
            run_name = str(row["run_name"])
            run_id = str(row.get("run_id") or run_name)
            metrics_by_run[(run_id, run_name)].append(row)
        for (run_id, run_name), rows in metrics_by_run.items():
            rows.sort(key=lambda item: (str(item["timestamp"]), int(item["id"])))
            for start in range(0, len(rows), batch_size):
                batch = rows[start : start + batch_size]
                DorisStorage.bulk_log(
                    project=project,
                    run=run_name,
                    run_id=run_id,
                    metrics_list=[_decode(row["metrics"], {}) for row in batch],
                    steps=[int(row["step"]) for row in batch],
                    timestamps=[str(row["timestamp"]) for row in batch],
                    log_ids=[row.get("log_id") for row in batch],
                    space_id=None,
                )
            migrated["metrics"] += len(rows)

        for row in _rows(connection, "configs"):
            run_name = str(row["run_name"])
            DorisStorage.upsert_run_config(
                project=project,
                run=run_name,
                run_id=str(row.get("run_id") or run_name),
                config=_decode(row["config"], {}),
                created_at=str(row["created_at"]),
            )
            migrated["configs"] += 1

        system_by_run: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for row in _rows(connection, "system_metrics"):
            run_name = str(row["run_name"])
            run_id = str(row.get("run_id") or run_name)
            system_by_run[(run_id, run_name)].append(row)
        for (run_id, run_name), rows in system_by_run.items():
            rows.sort(key=lambda item: (str(item["timestamp"]), int(item["id"])))
            for start in range(0, len(rows), batch_size):
                batch = rows[start : start + batch_size]
                DorisStorage.bulk_log_system(
                    project=project,
                    run=run_name,
                    run_id=run_id,
                    metrics_list=[_decode(row["metrics"], {}) for row in batch],
                    timestamps=[str(row["timestamp"]) for row in batch],
                    log_ids=[row.get("log_id") for row in batch],
                )
            migrated["system_metrics"] += len(rows)

        alerts_by_run: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for row in _rows(connection, "alerts"):
            run_name = str(row["run_name"])
            run_id = str(row.get("run_id") or run_name)
            alerts_by_run[(run_id, run_name)].append(row)
        for (run_id, run_name), rows in alerts_by_run.items():
            for start in range(0, len(rows), batch_size):
                batch = rows[start : start + batch_size]
                DorisStorage.bulk_alert(
                    project=project,
                    run=run_name,
                    run_id=run_id,
                    titles=[str(row["title"]) for row in batch],
                    texts=[row.get("text") for row in batch],
                    levels=[str(row["level"]) for row in batch],
                    steps=[row.get("step") for row in batch],
                    timestamps=[str(row["timestamp"]) for row in batch],
                    alert_ids=[row.get("alert_id") for row in batch],
                )
            migrated["alerts"] += len(rows)

        trace_rows = []
        for row in _rows(connection, "traces"):
            trace_rows.append(
                {
                    **row,
                    "messages": _decode(row.get("messages"), []),
                    "metadata": _decode(row.get("metadata"), {}),
                    "payload": _decode(row.get("payload"), None),
                }
            )
        for start in range(0, len(trace_rows), batch_size):
            DorisStorage.import_trace_rows(
                project, trace_rows[start : start + batch_size]
            )
        migrated["traces"] += len(trace_rows)

        for row in _rows(connection, "project_metadata"):
            DorisStorage.set_project_metadata(
                project, str(row["key"]), str(row["value"])
            )
            migrated["project_metadata"] += 1

        artifacts = _rows(connection, "artifacts")
        versions = _rows(connection, "artifact_versions")
        aliases = _rows(connection, "artifact_aliases")
        links = _rows(connection, "run_artifact_links")
        for version in versions:
            version["manifest"] = _decode(version["manifest"], [])
            version["metadata"] = _decode(version.get("metadata"), None)
        DorisStorage.import_artifact_graph(
            project,
            artifacts=artifacts,
            versions=versions,
            aliases=aliases,
            links=links,
        )
        migrated["artifacts"] += len(artifacts)
        migrated["artifact_versions"] += len(versions)
        migrated["artifact_aliases"] += len(aliases)
        migrated["run_artifact_links"] += len(links)
    finally:
        connection.close()
    return dict(migrated)


def _target_records(
    cursor: Any,
    project: str,
) -> dict[str, list[dict[str, Any]]]:
    def rows(table: str) -> list[dict[str, Any]]:
        cursor.execute(f"SELECT * FROM {table} WHERE project_id = %s", (project,))
        return list(cursor.fetchall())

    metrics = [
        {
            "run_id": str(row["run_id"]),
            "timestamp": str(row["timestamp"]),
            "run_name": str(row["run_name"]),
            "step": int(row["step"]),
            "metrics": _canonical_json(row["metrics"], {}),
            "log_id": row.get("log_id"),
            "space_id": row.get("space_id"),
        }
        for row in rows("metrics")
    ]
    configs = [
        {
            "run_id": str(row["run_id"]),
            "run_name": str(row["run_name"]),
            "config": _canonical_json(row["config"], {}),
            "created_at": str(row["created_at"]),
        }
        for row in rows("configs")
    ]
    system_metrics = [
        {
            "run_id": str(row["run_id"]),
            "timestamp": str(row["timestamp"]),
            "run_name": str(row["run_name"]),
            "metrics": _canonical_json(row["metrics"], {}),
            "log_id": row.get("log_id"),
            "space_id": row.get("space_id"),
        }
        for row in rows("system_metrics")
    ]
    traces = [
        {
            "trace_id": str(row["trace_id"]),
            "run_id": str(row["run_id"]),
            "timestamp": str(row["timestamp"]),
            "run_name": str(row["run_name"]),
            "step": int(row["step"]),
            "metric_key": str(row["metric_key"]),
            "trace_index": row.get("trace_index"),
            "messages": _canonical_json(row["messages"], []),
            "metadata": _canonical_json(row["metadata"], {}),
            "search_text": str(row.get("search_text") or ""),
            "log_id": row.get("log_id"),
            "space_id": row.get("space_id"),
            "trace_type": str(row.get("trace_type") or "trackio"),
            "external_id": row.get("external_id"),
            "schema_version": row.get("schema_version"),
            "payload": _canonical_json(row.get("payload"), None),
        }
        for row in rows("traces")
    ]
    alerts = [
        {
            "run_id": str(row["run_id"]),
            "timestamp": str(row["timestamp"]),
            "run_name": str(row["run_name"]),
            "title": str(row["title"]),
            "text": row.get("text"),
            "level": str(row["level"]),
            "step": row.get("step"),
            "alert_id": row.get("alert_id"),
        }
        for row in rows("alerts")
    ]
    project_metadata = [
        {
            "key": str(row["metadata_key"]),
            "value": str(row["metadata_value"]),
        }
        for row in rows("project_metadata")
    ]

    target_artifacts = rows("artifacts")
    artifacts_by_id = {int(row["artifact_id"]): row for row in target_artifacts}
    artifacts = [
        {
            "name": str(row["name"]),
            "type": str(row["artifact_type"]),
            "description": row.get("description"),
            "created_at": str(row["created_at"]),
        }
        for row in target_artifacts
    ]
    target_versions = rows("artifact_versions")
    versions_by_id = {int(row["version_id"]): row for row in target_versions}
    artifact_versions = []
    for row in target_versions:
        artifact = artifacts_by_id.get(int(row["artifact_id"]))
        if artifact is None:
            raise RuntimeError("Doris artifact version references a missing artifact")
        manifest = _canonical_json(row["manifest"], [])
        canonical_manifest, manifest_digest, size_bytes = (
            DorisStorage._canonical_manifest(manifest)
        )
        if manifest_digest != str(row["manifest_digest"]):
            raise RuntimeError("Doris artifact version manifest digest is inconsistent")
        if size_bytes != int(row["size_bytes"]):
            raise RuntimeError("Doris artifact version size is inconsistent")
        artifact_versions.append(
            {
                "artifact_name": str(artifact["name"]),
                "version": int(row["version_number"]),
                "manifest_digest": manifest_digest,
                "manifest": canonical_manifest,
                "metadata": _canonical_json(row.get("metadata"), None),
                "size_bytes": int(row["size_bytes"]),
                "producer_run_id": row.get("producer_run_id"),
                "producer_run_name": row.get("producer_run_name"),
                "created_at": str(row["created_at"]),
            }
        )
    artifact_aliases = []
    for row in rows("artifact_aliases"):
        artifact = artifacts_by_id.get(int(row["artifact_id"]))
        version = versions_by_id.get(int(row["version_id"]))
        if artifact is None or version is None:
            raise RuntimeError("Doris artifact alias references missing artifact data")
        if int(version["artifact_id"]) != int(row["artifact_id"]):
            raise RuntimeError(
                "Doris artifact alias references a version from another artifact"
            )
        if int(version["version_number"]) != int(row["version_number"]):
            raise RuntimeError("Doris artifact alias version metadata is inconsistent")
        artifact_aliases.append(
            {
                "artifact_name": str(artifact["name"]),
                "alias": str(row["alias"]),
                "version": int(version["version_number"]),
            }
        )
    run_artifact_links = []
    for row in rows("run_artifact_links"):
        version = versions_by_id.get(int(row["version_id"]))
        if version is None:
            raise RuntimeError(
                "Doris run artifact link references a missing artifact version"
            )
        artifact = artifacts_by_id.get(int(version["artifact_id"]))
        if artifact is None:
            raise RuntimeError("Doris run artifact link references a missing artifact")
        run_artifact_links.append(
            {
                "run_id": row.get("run_id"),
                "run_name": row.get("run_name"),
                "artifact_name": str(artifact["name"]),
                "version": int(version["version_number"]),
                "direction": str(row["direction"]),
                "created_at": str(row["created_at"]),
            }
        )
    return {
        "metrics": metrics,
        "configs": configs,
        "system_metrics": system_metrics,
        "traces": traces,
        "alerts": alerts,
        "project_metadata": project_metadata,
        "artifacts": artifacts,
        "artifact_versions": artifact_versions,
        "artifact_aliases": artifact_aliases,
        "run_artifact_links": run_artifact_links,
    }


def _target_evidence(project: str) -> dict[str, dict[str, Any]]:
    # Verification is deliberately non-initializing: a missing database or
    # schema is a failed verification, not permission to create remote state.
    with (
        DorisStorage._connection(initialize=False) as connection,
        connection.cursor() as cursor,
    ):
        return _records_evidence(_target_records(cursor, project))


def migrate_sqlite_to_doris(
    source: Path,
    receipt_path: Path,
    *,
    dry_run: bool = False,
    verify_only: bool = False,
    projects: tuple[str, ...] = (),
    batch_size: int = 500,
) -> dict[str, Any]:
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    candidates = (
        [source]
        if source.is_file()
        else sorted(path for path in source.glob("*.db") if path.is_file())
    )
    if projects:
        selected = set(projects)
        candidates = [path for path in candidates if path.stem in selected]
        missing = selected - {path.stem for path in candidates}
        if missing:
            raise FileNotFoundError(
                f"Trackio project database not found: {', '.join(sorted(missing))}"
            )
    if not candidates:
        raise FileNotFoundError(f"No Trackio project databases found under {source}")

    results = []
    for db_path in candidates:
        with _sqlite_snapshot(db_path) as (snapshot, metadata):
            source_info = _inspect_sqlite_snapshot(snapshot, db_path, metadata)
            migrated = {}
            if not dry_run and not verify_only:
                DorisStorage.initialize()
                migrated = _migrate_project(snapshot, db_path.stem, batch_size)
            target = {} if dry_run else _target_evidence(db_path.stem)
            expected = source_info["evidence"]
            mismatches = {
                table: {
                    "source": expected[table],
                    "target": target.get(table),
                }
                for table in AUTHORITATIVE_TABLES
                if not dry_run and expected[table] != target.get(table)
            }
            results.append(
                {
                    "source": source_info,
                    "migrated": migrated,
                    "target_evidence": target,
                    "mismatches": mismatches,
                    "verified": not dry_run and not mismatches,
                }
            )

    receipt = {
        "schema_version": 1,
        "kind": "trackio-sqlite-to-doris",
        "created_at": datetime.now(UTC).isoformat(),
        "dry_run": dry_run,
        "verify_only": verify_only,
        "batch_size": batch_size,
        "projects": results,
        "verified": not dry_run and all(result["verified"] for result in results),
    }
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    if not dry_run and not receipt["verified"]:
        raise RuntimeError(
            f"Doris migration reconciliation failed; inspect {receipt_path}"
        )
    return receipt


__all__ = ["inspect_sqlite_project", "migrate_sqlite_to_doris"]
