"""Native Apache Doris persistence for a self-hosted Trackio server."""

from __future__ import annotations

import hashlib
import os
import re
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Iterator

import orjson
import pymysql
from pymysql.cursors import DictCursor

import trackio.cas as cas
import trackio.references as references
from trackio.lifecycle import lifecycle_row
from trackio.doris_schema import (
    MANAGED_TABLES,
    SCHEMA_VERSION,
    negotiate_schema,
    schema_statements,
)
from trackio.dummy_commit_scheduler import DummyCommitScheduler
from trackio.sqlite_storage import SQLiteStorage
from trackio.utils import deserialize_values, serialize_values

_DATABASE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")


def _required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required when TRACKIO_DATABASE_ENGINE=doris")
    return value


def _json(value: Any) -> str:
    return orjson.dumps(serialize_values(value)).decode("utf-8")


def _decode(value: str | bytes) -> Any:
    return deserialize_values(orjson.loads(value))


def _event_id(
    project: str,
    run_id: str,
    timestamp: str,
    discriminator: str,
    explicit_id: str | None,
) -> str:
    if explicit_id:
        return hashlib.sha256(
            f"{project}\0{run_id}\0{explicit_id}".encode()
        ).hexdigest()
    return hashlib.sha256(
        f"{project}\0{run_id}\0{timestamp}\0{discriminator}".encode()
    ).hexdigest()


class DorisStorage:
    """Logical Trackio storage operations backed by Apache Doris.

    The class preserves the static-call shape of ``SQLiteStorage`` while the
    server migrates to an explicit provider object.
    """

    _schema_lock = threading.Lock()
    _artifact_lock = threading.Lock()
    _schema_ready = False
    _schema_target: tuple[str, int, str, str] | None = None
    _dataset_import_attempted = True

    @classmethod
    def _settings(cls) -> dict[str, Any]:
        database = _required_env("TRACKIO_DORIS_DATABASE")
        if not _DATABASE_RE.fullmatch(database):
            raise RuntimeError("TRACKIO_DORIS_DATABASE must be a simple SQL identifier")
        port_text = os.environ.get("TRACKIO_DORIS_PORT", "9030").strip()
        try:
            port = int(port_text)
        except ValueError as error:
            raise RuntimeError("TRACKIO_DORIS_PORT must be an integer") from error
        settings: dict[str, Any] = {
            "host": _required_env("TRACKIO_DORIS_HOST"),
            "port": port,
            "user": _required_env("TRACKIO_DORIS_USER"),
            "password": os.environ.get("TRACKIO_DORIS_PASSWORD", ""),
            "database": database,
            "connect_timeout": int(
                os.environ.get("TRACKIO_DORIS_CONNECT_TIMEOUT", "10")
            ),
            "read_timeout": int(os.environ.get("TRACKIO_DORIS_READ_TIMEOUT", "30")),
            "write_timeout": int(os.environ.get("TRACKIO_DORIS_WRITE_TIMEOUT", "30")),
            "autocommit": True,
            "cursorclass": DictCursor,
            "charset": "utf8mb4",
        }
        ca = os.environ.get("TRACKIO_DORIS_SSL_CA", "").strip()
        if ca:
            settings["ssl"] = {"ca": ca}
        return settings

    @classmethod
    @contextmanager
    def _connection(
        cls, *, initialize: bool = True, include_database: bool = True
    ) -> Iterator[pymysql.Connection]:
        if initialize:
            cls._ensure_schema()
        settings = cls._settings()
        if not include_database:
            settings.pop("database")
        connection = pymysql.connect(**settings)
        try:
            yield connection
        finally:
            connection.close()

    @classmethod
    def _ensure_schema(cls) -> None:
        settings = cls._settings()
        target = (
            str(settings["host"]),
            int(settings["port"]),
            str(settings["database"]),
            str(settings["user"]),
        )
        if cls._schema_ready and cls._schema_target == target:
            return
        with cls._schema_lock:
            if cls._schema_ready and cls._schema_target == target:
                return
            database = settings.pop("database")
            connection = pymysql.connect(**settings)
            try:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT TABLE_NAME AS table_name
                        FROM information_schema.tables
                        WHERE table_schema = %s
                        """,
                        (database,),
                    )
                    tables = {
                        str(row["table_name"])
                        for row in cursor.fetchall()
                        if str(row["table_name"]) in MANAGED_TABLES
                    }
                    recorded_version = None
                    if "schema_versions" in tables:
                        cursor.execute(f"USE `{database}`")
                        cursor.execute(
                            """
                            SELECT version FROM schema_versions
                            WHERE component = %s
                            LIMIT 1
                            """,
                            ("trackio",),
                        )
                        row = cursor.fetchone()
                        if row is not None:
                            recorded_version = int(row["version"])
                    action = negotiate_schema(tables, recorded_version)
                    if action == "bootstrap":
                        cursor.execute(f"CREATE DATABASE IF NOT EXISTS `{database}`")
                        cursor.execute(f"USE `{database}`")
                        replication = int(
                            os.environ.get("TRACKIO_DORIS_REPLICATION_NUM", "1")
                        )
                        for statement in schema_statements(replication):
                            cursor.execute(statement)
                        cursor.execute(
                            """
                            INSERT INTO schema_versions
                                (component, version, applied_at)
                            VALUES (%s, %s, %s)
                            """,
                            (
                                "trackio",
                                SCHEMA_VERSION,
                                datetime.now(timezone.utc).isoformat(),
                            ),
                        )
                cls._schema_ready = True
                cls._schema_target = target
            finally:
                connection.close()

    @classmethod
    def initialize(cls) -> None:
        cls._ensure_schema()

    @staticmethod
    def validate_project_name(project: str) -> None:
        if not isinstance(project, str) or not project.strip():
            raise ValueError("project must be a non-empty string")
        if len(project) > 255:
            raise ValueError("project cannot exceed 255 characters")

    @classmethod
    def _resolve_run_id(
        cls,
        cursor: DictCursor,
        project: str,
        run: str | None,
        run_id: str | None,
        table: str = "metrics",
    ) -> str | None:
        if run_id is not None:
            return run_id
        if run is None:
            return None
        cursor.execute(
            f"""
            SELECT run_id, MIN(timestamp) AS created_at
            FROM {table}
            WHERE project_id = %s AND run_name = %s
            GROUP BY run_id
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (project, run),
        )
        row = cursor.fetchone()
        if row is not None:
            return str(row["run_id"])
        cursor.execute(
            """
            SELECT run_id
            FROM configs
            WHERE project_id = %s AND run_name = %s
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (project, run),
        )
        row = cursor.fetchone()
        return str(row["run_id"]) if row is not None else None

    @staticmethod
    def _run_exists(cursor: DictCursor, project: str, run_id: str) -> bool:
        cursor.execute(
            """
            SELECT 1 AS present FROM (
                SELECT run_id FROM metrics WHERE project_id = %s
                UNION ALL
                SELECT run_id FROM configs WHERE project_id = %s
                UNION ALL
                SELECT run_id FROM system_metrics WHERE project_id = %s
                UNION ALL
                SELECT run_id FROM traces WHERE project_id = %s
                UNION ALL
                SELECT run_id FROM alerts WHERE project_id = %s
                UNION ALL
                SELECT run_id FROM run_artifact_links WHERE project_id = %s
            ) evidence
            WHERE run_id = %s
            LIMIT 1
            """,
            (project, project, project, project, project, project, run_id),
        )
        return cursor.fetchone() is not None

    @staticmethod
    def _subsample(rows: list[Any], max_points: int | None) -> list[Any]:
        if max_points is None or max_points < 1 or len(rows) <= max_points:
            return rows
        stride = len(rows) / max_points
        indices = {int(i * stride) for i in range(max_points)}
        indices.add(len(rows) - 1)
        return [rows[index] for index in sorted(indices)]

    @staticmethod
    def _optional_str(value: Any) -> str | None:
        return None if value is None else str(value)

    @staticmethod
    def _run_records_from_evidence(
        metric_rows: list[dict[str, Any]],
        link_rows: list[dict[str, Any]],
    ) -> list[dict[str, str | None]]:
        """Apply the same run-discovery rules as ``SQLiteStorage``.

        Metrics are the run-record authority. Artifact links only introduce
        artifact-only runs, and legacy name-only links are suppressed when an
        id-bearing link already identifies the same name.
        """

        metrics: dict[tuple[str | None, str], str] = {}
        for row in metric_rows:
            run_name = DorisStorage._optional_str(row.get("run_name"))
            if run_name is None:
                continue
            key = (DorisStorage._optional_str(row.get("run_id")), run_name)
            created_at = str(row["created_at"])
            metrics[key] = min(created_at, metrics.get(key, created_at))

        metric_ids = {run_id for run_id, _ in metrics if run_id is not None}
        metric_names = {run_name for _, run_name in metrics}
        id_bearing_link_names = {
            str(row["run_name"])
            for row in link_rows
            if row.get("run_id") is not None and row.get("run_name") is not None
        }
        records = dict(metrics)
        for row in link_rows:
            run_name = DorisStorage._optional_str(row.get("run_name"))
            if run_name is None or run_name in metric_names:
                continue
            run_id = DorisStorage._optional_str(row.get("run_id"))
            if run_id is not None and run_id in metric_ids:
                continue
            if run_id is None and run_name in id_bearing_link_names:
                continue
            key = (run_id, run_name)
            created_at = str(row["created_at"])
            records[key] = min(created_at, records.get(key, created_at))

        result = [
            {"id": run_id, "name": run_name, "created_at": created_at}
            for (run_id, run_name), created_at in records.items()
        ]
        return sorted(
            result,
            key=lambda row: (
                str(row["created_at"]),
                str(row["name"]),
                row["id"] or "",
            ),
        )

    @staticmethod
    def _artifact_link_counts_from_rows(
        rows: list[dict[str, Any]],
        records: list[dict[str, str | None]],
    ) -> list[dict[str, Any]]:
        """Fold legacy/orphan artifact links into an unambiguous run."""

        record_ids = {record["id"] for record in records if record["id"] is not None}
        ids_by_name: dict[str, set[str]] = {}
        for record in records:
            if record["id"] is not None and record["name"] is not None:
                ids_by_name.setdefault(record["name"], set()).add(record["id"])

        counts: dict[tuple[str | None, str | None], dict[str, Any]] = {}
        links_by_key: dict[tuple[str | None, str | None], set[tuple[int, str]]] = {}
        for row in rows:
            run_id = DorisStorage._optional_str(row.get("run_id"))
            run_name = DorisStorage._optional_str(row.get("run_name"))
            if run_id is None or run_id not in record_ids:
                owners = ids_by_name.get(run_name or "", set())
                run_id = next(iter(owners)) if len(owners) == 1 else None
            key = (run_id, run_name)
            entry = counts.setdefault(
                key,
                {
                    "run_id": run_id,
                    "run_name": run_name,
                    "input": 0,
                    "output": 0,
                },
            )
            direction = str(row["direction"])
            if direction not in {"input", "output"}:
                continue
            link = (int(row["version_id"]), direction)
            seen = links_by_key.setdefault(key, set())
            if link in seen:
                continue
            seen.add(link)
            entry[direction] += 1

        return sorted(
            counts.values(),
            key=lambda row: (
                str(row["run_name"] or ""),
                str(row["run_id"] or ""),
            ),
        )

    @staticmethod
    def _filter_metric_rows(
        rows: list[dict[str, Any]],
        *,
        step: int | None,
        around_step: int | None,
        at_time: str | None,
        window: int | float | None,
    ) -> list[dict[str, Any]]:
        if step is not None:
            return [row for row in rows if row["step"] == step]
        if around_step is not None and window is not None:
            lower, upper = around_step - int(window), around_step + int(window)
            return [row for row in rows if lower <= row["step"] <= upper]
        if at_time is None or window is None:
            return rows

        def parse(value: Any) -> datetime | None:
            try:
                parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            except ValueError:
                return None
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)

        target = parse(at_time)
        if target is None:
            return []
        radius = timedelta(seconds=int(window))
        lower, upper = target - radius, target + radius
        return [
            row
            for row in rows
            if (timestamp := parse(row["timestamp"])) is not None
            and lower <= timestamp <= upper
        ]

    @staticmethod
    def _stable_int(*parts: Any) -> int:
        payload = "\0".join(str(part) for part in parts).encode()
        return int(hashlib.sha256(payload).hexdigest()[:15], 16)

    @staticmethod
    def _canonical_manifest(
        manifest: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], str, int]:
        canonical = []
        size_bytes = 0
        for entry in manifest:
            normalized = {
                "path": entry["path"],
                "digest": entry["digest"],
                "size": int(entry["size"]),
            }
            if references.is_reference_entry(entry):
                normalized["ref"] = entry["ref"]
            canonical.append(normalized)
            size_bytes += int(entry["size"])
        canonical.sort(key=lambda entry: entry["path"])
        payload = orjson.dumps(canonical, option=orjson.OPT_SORT_KEYS)
        return canonical, hashlib.sha256(payload).hexdigest(), size_bytes

    @classmethod
    def log(
        cls,
        project: str,
        run: str,
        metrics: dict,
        step: int | None = None,
        run_id: str | None = None,
    ) -> None:
        cls.bulk_log(
            project=project,
            run=run,
            run_id=run_id,
            metrics_list=[metrics],
            steps=[step],
        )

    @classmethod
    def bulk_log(
        cls,
        project: str,
        run: str,
        metrics_list: list[dict],
        steps: list[int | None] | None = None,
        timestamps: list[str] | None = None,
        config: dict | None = None,
        log_ids: list[str | None] | None = None,
        space_id: str | None = None,
        run_id: str | None = None,
    ) -> None:
        if not metrics_list:
            return
        cls.validate_project_name(project)
        resolved_run_id = run_id or run
        timestamps = timestamps or [
            datetime.now(timezone.utc).isoformat() for _ in metrics_list
        ]
        if steps is None:
            steps = list(range(len(metrics_list)))
        if not (
            len(metrics_list) == len(steps) == len(timestamps)
            and (log_ids is None or len(log_ids) == len(metrics_list))
        ):
            raise ValueError(
                "metrics_list, steps, timestamps, and log_ids must have equal length"
            )
        with cls._connection() as connection, connection.cursor() as cursor:
            if any(step is None for step in steps):
                cursor.execute(
                    """
                    SELECT MAX(step) AS max_step FROM metrics
                    WHERE project_id = %s AND run_id = %s
                    """,
                    (project, resolved_run_id),
                )
                row = cursor.fetchone()
                next_step = 0 if row["max_step"] is None else int(row["max_step"]) + 1
                normalized_steps: list[int] = []
                for step in steps:
                    if step is None:
                        normalized_steps.append(next_step)
                        next_step += 1
                    else:
                        normalized_steps.append(step)
                steps = normalized_steps

            metric_rows = []
            trace_rows = []
            for index, metrics in enumerate(metrics_list):
                log_id = log_ids[index] if log_ids else None
                clean_metrics, extracted = SQLiteStorage._split_trace_metrics(
                    metrics,
                    run=run,
                    run_id=resolved_run_id,
                    step=int(steps[index]),
                    timestamp=timestamps[index],
                    log_id=log_id,
                    space_id=space_id,
                )
                trace_rows.extend(extracted)
                event_id = _event_id(
                    project,
                    resolved_run_id,
                    timestamps[index],
                    f"{steps[index]}\0{_json(clean_metrics)}",
                    log_id,
                )
                metric_rows.append(
                    (
                        project,
                        event_id,
                        resolved_run_id,
                        timestamps[index],
                        run,
                        int(steps[index]),
                        _json(clean_metrics),
                        log_id,
                        space_id,
                    )
                )

            cursor.executemany(
                """
                INSERT INTO metrics
                    (project_id, event_id, run_id, timestamp, run_name, step,
                     metrics, log_id, space_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                metric_rows,
            )
            if trace_rows:
                cursor.executemany(
                    """
                    INSERT INTO traces
                        (project_id, trace_id, run_id, timestamp, run_name, step,
                         metric_key, trace_index, messages, metadata, search_text,
                         log_id, space_id, trace_type, external_id, schema_version,
                         payload)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                            %s, %s, %s, %s, %s, %s)
                    """,
                    [
                        (
                            project,
                            row["id"],
                            row["run_id"],
                            row["timestamp"],
                            row["run_name"],
                            row["step"],
                            row["key"],
                            row["trace_index"],
                            _json(row["messages"]),
                            _json(row["metadata"]),
                            row["search_text"],
                            row["log_id"],
                            row["space_id"],
                            row["trace_type"],
                            row["external_id"],
                            row["schema_version"],
                            _json(row["payload"])
                            if row["payload"] is not None
                            else None,
                        )
                        for row in trace_rows
                    ],
                )
            if config:
                cursor.execute(
                    """
                    INSERT INTO configs
                        (project_id, run_id, run_name, config, created_at)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (
                        project,
                        resolved_run_id,
                        run,
                        _json(config),
                        datetime.now(timezone.utc).isoformat(),
                    ),
                )

    @classmethod
    def bulk_log_system(
        cls,
        project: str,
        run: str,
        metrics_list: list[dict],
        timestamps: list[str] | None = None,
        log_ids: list[str | None] | None = None,
        space_id: str | None = None,
        run_id: str | None = None,
    ) -> None:
        if not metrics_list:
            return
        resolved_run_id = run_id or run
        timestamps = timestamps or [
            datetime.now(timezone.utc).isoformat() for _ in metrics_list
        ]
        if len(metrics_list) != len(timestamps):
            raise ValueError("metrics_list and timestamps must have the same length")
        rows = []
        for index, metrics in enumerate(metrics_list):
            log_id = log_ids[index] if log_ids else None
            rows.append(
                (
                    project,
                    _event_id(
                        project,
                        resolved_run_id,
                        timestamps[index],
                        _json(metrics),
                        log_id,
                    ),
                    resolved_run_id,
                    timestamps[index],
                    run,
                    _json(metrics),
                    log_id,
                    space_id,
                )
            )
        with cls._connection() as connection, connection.cursor() as cursor:
            cursor.executemany(
                """
                INSERT INTO system_metrics
                    (project_id, event_id, run_id, timestamp, run_name, metrics,
                     log_id, space_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                rows,
            )

    @classmethod
    def upsert_run_config(
        cls,
        project: str,
        run: str,
        run_id: str,
        config: dict[str, Any],
        created_at: str,
    ) -> None:
        with cls._connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO configs
                    (project_id, run_id, run_name, config, created_at)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (project, run_id, run, _json(config), created_at),
            )

    @classmethod
    def import_trace_rows(cls, project: str, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        values = []
        for row in rows:
            values.append(
                (
                    project,
                    row["id"],
                    row["run_id"],
                    row["timestamp"],
                    row["run_name"],
                    int(row["step"]),
                    row["key"],
                    row.get("trace_index"),
                    _json(row.get("messages") or []),
                    _json(row.get("metadata") or {}),
                    row.get("search_text") or "",
                    row.get("log_id"),
                    row.get("space_id"),
                    row.get("trace_type") or "trackio",
                    row.get("external_id"),
                    row.get("schema_version"),
                    _json(row["payload"]) if row.get("payload") is not None else None,
                )
            )
        with cls._connection() as connection, connection.cursor() as cursor:
            cursor.executemany(
                """
                INSERT INTO traces
                    (project_id, trace_id, run_id, timestamp, run_name, step,
                     metric_key, trace_index, messages, metadata, search_text,
                     log_id, space_id, trace_type, external_id, schema_version,
                     payload)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s)
                """,
                values,
            )

    @classmethod
    def import_artifact_graph(
        cls,
        project: str,
        *,
        artifacts: list[dict[str, Any]],
        versions: list[dict[str, Any]],
        aliases: list[dict[str, Any]],
        links: list[dict[str, Any]],
    ) -> None:
        """Import retained artifact lineage without changing logical history.

        Source SQLite integer identifiers are translated to deterministic Doris
        identifiers. Version numbers and lineage timestamps remain the source
        values so migration reconciliation can compare logical records exactly.
        """

        artifacts_by_source_id = {
            int(artifact["id"]): artifact for artifact in artifacts
        }
        target_artifact_ids = {
            source_id: cls._stable_int(project, artifact["name"])
            for source_id, artifact in artifacts_by_source_id.items()
        }
        versions_by_source_id = {int(version["id"]): version for version in versions}
        target_version_ids: dict[int, int] = {}

        with cls._artifact_lock:
            with cls._connection() as connection, connection.cursor() as cursor:
                for source_id, artifact in artifacts_by_source_id.items():
                    cursor.execute(
                        """
                        INSERT INTO artifacts
                            (project_id, artifact_id, name, artifact_type,
                             description, created_at)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        """,
                        (
                            project,
                            target_artifact_ids[source_id],
                            artifact["name"],
                            artifact["type"],
                            artifact.get("description"),
                            artifact["created_at"],
                        ),
                    )

                for source_version_id, version in sorted(
                    versions_by_source_id.items(),
                    key=lambda item: (
                        int(item[1]["artifact_id"]),
                        int(item[1]["version"]),
                    ),
                ):
                    source_artifact_id = int(version["artifact_id"])
                    if source_artifact_id not in target_artifact_ids:
                        raise RuntimeError(
                            "artifact version references an unmigrated artifact"
                        )
                    canonical, digest, size_bytes = cls._canonical_manifest(
                        version["manifest"]
                    )
                    if digest != str(version["manifest_digest"]):
                        raise RuntimeError(
                            "artifact version manifest digest does not match its "
                            "canonical manifest"
                        )
                    if size_bytes != int(version["size_bytes"]):
                        raise RuntimeError(
                            "artifact version size does not match its manifest"
                        )
                    target_version_id = cls._stable_int(
                        project,
                        artifacts_by_source_id[source_artifact_id]["name"],
                        digest,
                    )
                    target_version_ids[source_version_id] = target_version_id
                    cursor.execute(
                        """
                        INSERT INTO artifact_versions
                            (project_id, version_id, artifact_id, version_number,
                             manifest_digest, manifest, metadata, size_bytes,
                             producer_run_id, producer_run_name, created_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            project,
                            target_version_id,
                            target_artifact_ids[source_artifact_id],
                            int(version["version"]),
                            digest,
                            _json(canonical),
                            _json(version["metadata"])
                            if version.get("metadata") is not None
                            else None,
                            size_bytes,
                            version.get("producer_run_id"),
                            version.get("producer_run_name"),
                            version["created_at"],
                        ),
                    )

                for alias in aliases:
                    source_artifact_id = int(alias["artifact_id"])
                    source_version_id = int(alias["artifact_version_id"])
                    if (
                        source_artifact_id not in target_artifact_ids
                        or source_version_id not in target_version_ids
                    ):
                        raise RuntimeError(
                            "artifact alias references unmigrated artifact data"
                        )
                    version = versions_by_source_id[source_version_id]
                    if int(version["artifact_id"]) != source_artifact_id:
                        raise RuntimeError(
                            "artifact alias references a version from another artifact"
                        )
                    cursor.execute(
                        """
                        INSERT INTO artifact_aliases
                            (project_id, artifact_id, alias, version_id,
                             version_number, updated_at)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        """,
                        (
                            project,
                            target_artifact_ids[source_artifact_id],
                            alias["alias"],
                            target_version_ids[source_version_id],
                            int(version["version"]),
                            version["created_at"],
                        ),
                    )

                for link in links:
                    source_version_id = int(link["artifact_version_id"])
                    if source_version_id not in target_version_ids:
                        raise RuntimeError(
                            "run artifact link references an unmigrated artifact version"
                        )
                    if link["direction"] not in {"input", "output"}:
                        raise RuntimeError(
                            "run artifact link has an unsupported direction"
                        )
                    target_version_id = target_version_ids[source_version_id]
                    link_id = cls._stable_int(
                        project,
                        link.get("run_id") or "",
                        link.get("run_name") or "",
                        target_version_id,
                        link["direction"],
                    )
                    cursor.execute(
                        """
                        INSERT INTO run_artifact_links
                            (project_id, link_id, run_id, run_name, version_id,
                             direction, created_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            project,
                            link_id,
                            link.get("run_id"),
                            link.get("run_name"),
                            target_version_id,
                            link["direction"],
                            link["created_at"],
                        ),
                    )

    @classmethod
    def bulk_alert(
        cls,
        project: str,
        run: str,
        titles: list[str],
        texts: list[str | None],
        levels: list[str],
        steps: list[int | None],
        timestamps: list[str] | None = None,
        alert_ids: list[str | None] | None = None,
        run_id: str | None = None,
    ) -> None:
        if not titles:
            return
        resolved_run_id = run_id or run
        timestamps = timestamps or [
            datetime.now(timezone.utc).isoformat() for _ in titles
        ]
        rows = []
        for index, title in enumerate(titles):
            alert_id = alert_ids[index] if alert_ids else None
            rows.append(
                (
                    project,
                    _event_id(
                        project,
                        resolved_run_id,
                        timestamps[index],
                        f"{title}\0{steps[index]}",
                        alert_id,
                    ),
                    resolved_run_id,
                    timestamps[index],
                    run,
                    title,
                    texts[index],
                    levels[index],
                    steps[index],
                    alert_id,
                )
            )
        with cls._connection() as connection, connection.cursor() as cursor:
            cursor.executemany(
                """
                INSERT INTO alerts
                    (project_id, event_id, run_id, timestamp, run_name, title,
                     text, level, step, alert_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                rows,
            )

    @classmethod
    def get_projects(cls) -> list[str]:
        with cls._connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT project_id FROM (
                    SELECT project_id FROM metrics
                    UNION ALL SELECT project_id FROM configs
                    UNION ALL SELECT project_id FROM system_metrics
                    UNION ALL SELECT project_id FROM traces
                    UNION ALL SELECT project_id FROM alerts
                    UNION ALL SELECT project_id FROM artifacts
                    UNION ALL SELECT project_id FROM run_artifact_links
                ) projects
                GROUP BY project_id
                ORDER BY project_id
                """
            )
            return [str(row["project_id"]) for row in cursor.fetchall()]

    @classmethod
    def get_run_records(cls, project: str) -> list[dict[str, str | None]]:
        with cls._connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT run_id, run_name, MIN(timestamp) AS created_at
                FROM metrics WHERE project_id = %s
                GROUP BY run_id, run_name
                """,
                (project,),
            )
            metric_rows = list(cursor.fetchall())
            cursor.execute(
                """
                SELECT run_id, run_name, MIN(created_at) AS created_at
                FROM run_artifact_links WHERE project_id = %s
                GROUP BY run_id, run_name
                """,
                (project,),
            )
            link_rows = list(cursor.fetchall())
        return cls._run_records_from_evidence(metric_rows, link_rows)

    @classmethod
    def get_runs(cls, project: str) -> list[str]:
        return [str(record["name"]) for record in cls.get_run_records(project)]

    @classmethod
    def get_all_run_configs(cls, project: str) -> dict[str, dict]:
        with cls._connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT run_id, config FROM configs WHERE project_id = %s",
                (project,),
            )
            return {
                str(row["run_id"]): _decode(row["config"]) for row in cursor.fetchall()
            }

    @classmethod
    def get_run_config(
        cls, project: str, run: str | None = None, run_id: str | None = None
    ) -> dict | None:
        with cls._connection() as connection, connection.cursor() as cursor:
            resolved = cls._resolve_run_id(cursor, project, run, run_id)
            if resolved is None:
                return None
            cursor.execute(
                """
                SELECT config FROM configs
                WHERE project_id = %s AND run_id = %s
                LIMIT 1
                """,
                (project, resolved),
            )
            row = cursor.fetchone()
            return _decode(row["config"]) if row is not None else None

    @classmethod
    def get_logs(
        cls,
        project: str,
        run: str | None = None,
        max_points: int | None = None,
        run_id: str | None = None,
        scalar_only: bool = False,
    ) -> list[dict]:
        with cls._connection() as connection, connection.cursor() as cursor:
            resolved = cls._resolve_run_id(cursor, project, run, run_id)
            if resolved is None:
                return []
            cursor.execute(
                """
                SELECT timestamp, step, metrics FROM metrics
                WHERE project_id = %s AND run_id = %s
                ORDER BY timestamp, event_id
                """,
                (project, resolved),
            )
            rows = cls._subsample(list(cursor.fetchall()), max_points)
        result = []
        for row in rows:
            metrics = orjson.loads(row["metrics"])
            if scalar_only:
                metrics = {
                    key: value
                    for key, value in metrics.items()
                    if isinstance(value, int | float) and not isinstance(value, bool)
                }
            else:
                metrics = deserialize_values(metrics)
            metrics["timestamp"] = str(row["timestamp"])
            metrics["step"] = int(row["step"])
            result.append(metrics)
        return result

    @classmethod
    def get_logs_batch(
        cls,
        project: str,
        runs: list[dict[str, Any]] | None = None,
        max_points: int | None = None,
        scalar_only: bool = False,
    ) -> list[dict[str, Any]]:
        return [
            {
                "run": item.get("run"),
                "run_id": item.get("run_id"),
                "logs": cls.get_logs(
                    project,
                    item.get("run"),
                    run_id=item.get("run_id"),
                    max_points=max_points,
                    scalar_only=scalar_only,
                ),
            }
            for item in (runs or [])
        ]

    @classmethod
    def get_system_logs(
        cls,
        project: str,
        run: str | None = None,
        run_id: str | None = None,
        max_points: int | None = None,
    ) -> list[dict]:
        with cls._connection() as connection, connection.cursor() as cursor:
            resolved = cls._resolve_run_id(
                cursor, project, run, run_id, table="system_metrics"
            )
            if resolved is None:
                return []
            cursor.execute(
                """
                SELECT timestamp, metrics FROM system_metrics
                WHERE project_id = %s AND run_id = %s
                ORDER BY timestamp, event_id
                """,
                (project, resolved),
            )
            rows = cls._subsample(list(cursor.fetchall()), max_points)
        result = []
        for row in rows:
            metrics = _decode(row["metrics"])
            metrics["timestamp"] = str(row["timestamp"])
            result.append(metrics)
        return result

    @classmethod
    def get_system_logs_batch(
        cls,
        project: str,
        runs: list[dict[str, Any]] | None = None,
        max_points: int | None = None,
    ) -> list[dict[str, Any]]:
        return [
            {
                "run": item.get("run"),
                "run_id": item.get("run_id"),
                "logs": cls.get_system_logs(
                    project,
                    item.get("run"),
                    run_id=item.get("run_id"),
                    max_points=max_points,
                ),
            }
            for item in (runs or [])
        ]

    @classmethod
    def _metric_names(
        cls,
        project: str,
        run: str | None,
        run_id: str | None,
        table: str,
    ) -> list[str]:
        logs = (
            cls.get_logs(project, run, run_id=run_id)
            if table == "metrics"
            else cls.get_system_logs(project, run, run_id=run_id)
        )
        ignored = {"timestamp", "step"}
        return sorted({key for log in logs for key in log if key not in ignored})

    @classmethod
    def get_all_metrics_for_run(
        cls, project: str, run: str | None = None, run_id: str | None = None
    ) -> list[str]:
        return cls._metric_names(project, run, run_id, "metrics")

    @classmethod
    def get_all_system_metrics_for_run(
        cls, project: str, run: str | None = None, run_id: str | None = None
    ) -> list[str]:
        return cls._metric_names(project, run, run_id, "system_metrics")

    @classmethod
    def get_log_count(
        cls, project: str, run: str | None = None, run_id: str | None = None
    ) -> int:
        with cls._connection() as connection, connection.cursor() as cursor:
            resolved = cls._resolve_run_id(cursor, project, run, run_id)
            if resolved is None:
                return 0
            cursor.execute(
                """
                SELECT COUNT(*) AS count FROM metrics
                WHERE project_id = %s AND run_id = %s
                """,
                (project, resolved),
            )
            return int(cursor.fetchone()["count"])

    @classmethod
    def get_last_step(
        cls, project: str, run: str | None = None, run_id: str | None = None
    ) -> int | None:
        with cls._connection() as connection, connection.cursor() as cursor:
            resolved = cls._resolve_run_id(cursor, project, run, run_id)
            if resolved is None:
                return None
            cursor.execute(
                """
                SELECT MAX(step) AS max_step FROM metrics
                WHERE project_id = %s AND run_id = %s
                """,
                (project, resolved),
            )
            value = cursor.fetchone()["max_step"]
            return int(value) if value is not None else None

    get_max_step_for_run = get_last_step

    @classmethod
    def get_max_steps_for_runs(cls, project: str) -> dict[str, int]:
        with cls._connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT run_id, MAX(step) AS max_step FROM metrics
                WHERE project_id = %s GROUP BY run_id
                """,
                (project,),
            )
            return {
                str(row["run_id"]): int(row["max_step"]) for row in cursor.fetchall()
            }

    @classmethod
    def get_run_lifecycles(cls, project: str) -> dict[str, dict]:
        """Return the latest lifecycle row for every run in `project`.

    Lifecycle values are logged as ordinary metric rows, so describing a run
    otherwise costs a request per run and a listing costs one per run in the
    project. This answers for every run at once, which is what makes listing a
    project cost the same whether it holds one run or a thousand.
    """
        lifecycles: dict[str, dict] = {}
        with cls._connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT run_id, timestamp, metrics FROM metrics
                WHERE project_id = %s AND metrics LIKE %s
                ORDER BY timestamp, event_id
                """,
                (project, "%run/status%"),
            )
            for row in cursor.fetchall():
                values = _decode(row["metrics"])
                if not isinstance(values, dict) or "run/status" not in values:
                    continue
                # Ordered oldest first, so the last row seen for a run wins.
                lifecycles[str(row["run_id"])] = lifecycle_row(values)
        return lifecycles

    @classmethod
    def get_alerts(
        cls,
        project: str,
        run_name: str | None = None,
        run_id: str | None = None,
        level: str | None = None,
        since: str | None = None,
    ) -> list[dict]:
        with cls._connection() as connection, connection.cursor() as cursor:
            conditions = ["project_id = %s"]
            params: list[Any] = [project]
            resolved = cls._resolve_run_id(
                cursor, project, run_name, run_id, table="alerts"
            )
            if run_name is not None or run_id is not None:
                if resolved is None:
                    return []
                conditions.append("run_id = %s")
                params.append(resolved)
            if level is not None:
                conditions.append("level = %s")
                params.append(level)
            if since is not None:
                conditions.append("timestamp > %s")
                params.append(since)
            cursor.execute(
                f"""
                SELECT timestamp, run_name, title, text, level, step
                FROM alerts WHERE {" AND ".join(conditions)}
                ORDER BY timestamp DESC, event_id DESC
                """,
                params,
            )
            return [
                {
                    "timestamp": str(row["timestamp"]),
                    "run": str(row["run_name"]),
                    "title": row["title"],
                    "text": row["text"],
                    "level": str(row["level"]),
                    "step": row["step"],
                }
                for row in cursor.fetchall()
            ]

    @classmethod
    def get_traces(
        cls,
        project: str,
        run: str | None = None,
        search: str | None = None,
        sort: str | None = None,
        limit: int | None = None,
        offset: int = 0,
        run_id: str | None = None,
        step: int | None = None,
        trace_type: str | None = None,
    ) -> list[dict[str, Any]]:
        with cls._connection() as connection, connection.cursor() as cursor:
            resolved = cls._resolve_run_id(cursor, project, run, run_id, table="traces")
            if resolved is None:
                return []
            conditions = ["project_id = %s", "run_id = %s"]
            params: list[Any] = [project, resolved]
            if step is not None:
                conditions.append("step = %s")
                params.append(step)
            if trace_type:
                conditions.append("trace_type = %s")
                params.append(trace_type)
            if search and search.strip():
                conditions.append("LOWER(search_text) LIKE %s")
                params.append(f"%{search.strip().lower()}%")
            order = {
                "step_asc": "step ASC, timestamp ASC, trace_id ASC",
                "step_desc": "step DESC, timestamp DESC, trace_id DESC",
                "request_time_asc": "timestamp ASC, trace_id ASC",
            }.get(sort or "", "timestamp DESC, trace_id DESC")
            query = f"""
                SELECT trace_id, metric_key, trace_index, run_name, run_id, step,
                       timestamp, messages, metadata, trace_type, external_id,
                       schema_version, payload
                FROM traces
                WHERE {" AND ".join(conditions)}
                ORDER BY {order}
            """
            if limit is not None:
                query += " LIMIT %s"
                params.append(max(0, int(limit)))
            elif offset:
                query += " LIMIT 1000000"
            if offset:
                query += " OFFSET %s"
                params.append(max(0, int(offset)))
            cursor.execute(query, params)
            rows = cursor.fetchall()
        return [
            {
                "id": row["trace_id"],
                "key": row["metric_key"],
                "index": row["trace_index"],
                "run": row["run_name"],
                "run_id": row["run_id"],
                "step": row["step"],
                "timestamp": row["timestamp"],
                "messages": _decode(row["messages"]),
                "metadata": _decode(row["metadata"]),
                "trace_type": row["trace_type"],
                "external_id": row["external_id"],
                "schema_version": row["schema_version"],
                "payload": _decode(row["payload"])
                if row["payload"] is not None
                else None,
            }
            for row in rows
        ]

    @classmethod
    def get_trace_steps(
        cls,
        project: str,
        run: str | None = None,
        run_id: str | None = None,
        trace_type: str | None = None,
    ) -> dict[str, Any]:
        traces = cls.get_traces(
            project, run, run_id=run_id, trace_type=trace_type, sort="step_asc"
        )
        counts: dict[int, int] = {}
        for trace in traces:
            counts[int(trace["step"])] = counts.get(int(trace["step"]), 0) + 1
        steps = [{"step": step, "count": counts[step]} for step in sorted(counts)]
        return {"total": len(traces), "steps": steps}

    @classmethod
    def get_tab_availability_flags(cls, project: str) -> dict[str, bool]:
        with cls._connection() as connection, connection.cursor() as cursor:
            flags = {}
            for key, predicate in (
                ("metrics", "metrics REGEXP ':[[:space:]]*-?[0-9]'"),
                (
                    "media",
                    "("
                    """metrics LIKE '%"_type":"trackio.image"%' OR """
                    """metrics LIKE '%"_type":"trackio.video"%' OR """
                    """metrics LIKE '%"_type":"trackio.audio"%' OR """
                    """metrics LIKE '%"_type":"trackio.table"%'"""
                    ")",
                ),
                ("reports", """metrics LIKE '%"_type":"trackio.markdown"%'"""),
            ):
                cursor.execute(
                    f"""
                    SELECT 1 AS present FROM metrics
                    WHERE project_id = %s AND {predicate} LIMIT 1
                    """,
                    (project,),
                )
                flags[key] = cursor.fetchone() is not None
            for key, table, predicate in (
                ("system", "system_metrics", ""),
                ("traces", "traces", " AND trace_type = 'trackio'"),
                ("alerts", "alerts", ""),
            ):
                cursor.execute(
                    f"""
                    SELECT 1 AS present FROM {table}
                    WHERE project_id = %s{predicate} LIMIT 1
                    """,
                    (project,),
                )
                flags[key] = cursor.fetchone() is not None
            cursor.execute(
                """
                SELECT 1 AS present FROM traces
                WHERE project_id = %s AND trace_type = 'verifiers' LIMIT 1
                """,
                (project,),
            )
            flags["verifiers_traces"] = cursor.fetchone() is not None
            cursor.execute(
                """
                SELECT 1 AS present FROM artifact_versions
                WHERE project_id = %s LIMIT 1
                """,
                (project,),
            )
            flags["artifacts"] = cursor.fetchone() is not None
        return flags

    @classmethod
    def set_project_metadata(cls, project: str, key: str, value: str) -> None:
        with cls._connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO project_metadata
                    (project_id, metadata_key, metadata_value)
                VALUES (%s, %s, %s)
                """,
                (project, key, value),
            )

    @classmethod
    def get_project_metadata(cls, project: str, key: str) -> str | None:
        with cls._connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT metadata_value FROM project_metadata
                WHERE project_id = %s AND metadata_key = %s LIMIT 1
                """,
                (project, key),
            )
            row = cursor.fetchone()
            return str(row["metadata_value"]) if row else None

    @classmethod
    def get_space_id(cls, project: str) -> str | None:
        return cls.get_project_metadata(project, "space_id")

    @classmethod
    def get_metric_values(
        cls,
        project: str,
        run: str | None,
        metric_name: str,
        step: int | None = None,
        around_step: int | None = None,
        at_time: str | None = None,
        window: int | float | None = None,
        run_id: str | None = None,
    ) -> list[dict]:
        rows = cls.get_logs(project, run, run_id=run_id)
        rows = cls._filter_metric_rows(
            rows,
            step=step,
            around_step=around_step,
            at_time=at_time,
            window=window,
        )
        return [
            {
                "timestamp": row["timestamp"],
                "step": row["step"],
                "value": row[metric_name],
            }
            for row in rows
            if metric_name in row
        ]

    @classmethod
    def get_snapshot(
        cls,
        project: str,
        run: str | None = None,
        step: int | None = None,
        around_step: int | None = None,
        at_time: str | None = None,
        window: int | float | None = None,
        run_id: str | None = None,
    ) -> dict[str, list[dict]]:
        rows = cls.get_logs(project, run, run_id=run_id)
        rows = cls._filter_metric_rows(
            rows,
            step=step,
            around_step=around_step,
            at_time=at_time,
            window=window,
        )
        result: dict[str, list[dict]] = {}
        for row in rows:
            for key, value in row.items():
                if key in {"timestamp", "step"}:
                    continue
                result.setdefault(key, []).append(
                    {
                        "timestamp": row["timestamp"],
                        "step": row["step"],
                        "value": value,
                    }
                )
        return result

    @classmethod
    def query_project(
        cls, project: str, query: str, max_rows: int = 10_000
    ) -> dict[str, Any]:
        del project, query, max_rows
        raise ValueError(
            "query_project is SQLite-specific and is not available with the Doris engine"
        )

    @classmethod
    def rename_run(
        cls,
        project: str,
        old_name: str,
        new_name: str,
        run_id: str | None = None,
    ) -> None:
        normalized = new_name.strip()
        if not normalized:
            raise ValueError("new run name must be a non-empty string")
        with cls._connection() as connection, connection.cursor() as cursor:
            resolved = cls._resolve_run_id(cursor, project, old_name, run_id)
            if resolved is None or not cls._run_exists(cursor, project, resolved):
                raise ValueError(f"Run '{old_name}' does not exist.")
            cursor.execute(
                """
                SELECT 1 AS present FROM metrics
                WHERE project_id = %s AND run_name = %s AND run_id != %s
                LIMIT 1
                """,
                (project, normalized, resolved),
            )
            if cursor.fetchone() is not None:
                raise ValueError(f"Run '{normalized}' already exists.")
            for table in (
                "metrics",
                "configs",
                "system_metrics",
                "traces",
                "alerts",
                "run_artifact_links",
            ):
                cursor.execute(
                    f"""
                    UPDATE {table} SET run_name = %s
                    WHERE project_id = %s AND run_id = %s
                    """,
                    (normalized, project, resolved),
                )
            cursor.execute(
                """
                UPDATE artifact_versions SET producer_run_name = %s
                WHERE project_id = %s AND producer_run_id = %s
                """,
                (normalized, project, resolved),
            )

    @classmethod
    def delete_run(
        cls,
        project: str,
        run: str | None = None,
        run_id: str | None = None,
    ) -> bool:
        with cls._connection() as connection, connection.cursor() as cursor:
            resolved = cls._resolve_run_id(cursor, project, run, run_id)
            if resolved is None or not cls._run_exists(cursor, project, resolved):
                return False
            cursor.execute(
                """
                UPDATE artifact_versions
                SET producer_run_id = NULL, producer_run_name = NULL
                WHERE project_id = %s AND producer_run_id = %s
                """,
                (project, resolved),
            )
            for table in (
                "metrics",
                "configs",
                "system_metrics",
                "traces",
                "alerts",
                "run_artifact_links",
            ):
                cursor.execute(
                    f"DELETE FROM {table} WHERE project_id = %s AND run_id = %s",
                    (project, resolved),
                )
        return True

    @classmethod
    def _resolve_artifact_version(
        cls,
        cursor: DictCursor,
        project: str,
        name: str,
        spec: str | None,
    ) -> dict[str, Any] | None:
        cursor.execute(
            """
            SELECT artifact_id FROM artifacts
            WHERE project_id = %s AND name = %s LIMIT 1
            """,
            (project, name),
        )
        artifact = cursor.fetchone()
        if artifact is None:
            return None
        artifact_id = int(artifact["artifact_id"])
        resolved_spec = spec or "latest"
        match = cas.ARTIFACT_VERSION_SPEC_RE.match(resolved_spec)
        if match:
            cursor.execute(
                """
                SELECT version_id, version_number FROM artifact_versions
                WHERE project_id = %s AND artifact_id = %s
                  AND version_number = %s
                LIMIT 1
                """,
                (project, artifact_id, int(match.group(1))),
            )
        else:
            cursor.execute(
                """
                SELECT version_id, version_number FROM artifact_aliases
                WHERE project_id = %s AND artifact_id = %s AND alias = %s
                LIMIT 1
                """,
                (project, artifact_id, resolved_spec),
            )
        version = cursor.fetchone()
        if version is None:
            return None
        return {
            "artifact_id": artifact_id,
            "version_id": int(version["version_id"]),
            "version": int(version["version_number"]),
        }

    @classmethod
    def commit_artifact_version(
        cls,
        project: str,
        name: str,
        type: str,
        description: str | None,
        manifest: list[dict[str, Any]],
        metadata: dict | None,
        aliases: list[str] | None,
        run_name: str | None,
        run_id: str | None,
    ) -> dict:
        canonical, manifest_digest, size_bytes = cls._canonical_manifest(manifest)
        now = datetime.now(timezone.utc).isoformat()
        artifact_id = cls._stable_int(project, name)
        version_id = cls._stable_int(project, name, manifest_digest)
        with cls._artifact_lock:
            with cls._connection() as connection, connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT artifact_type FROM artifacts
                    WHERE project_id = %s AND artifact_id = %s LIMIT 1
                    """,
                    (project, artifact_id),
                )
                existing_artifact = cursor.fetchone()
                if (
                    existing_artifact is not None
                    and existing_artifact["artifact_type"] != type
                ):
                    raise ValueError(
                        f"Artifact '{name}' already exists with type "
                        f"'{existing_artifact['artifact_type']}'; cannot relog "
                        f"with type '{type}'."
                    )
                if existing_artifact is None:
                    cursor.execute(
                        """
                        INSERT INTO artifacts
                            (project_id, artifact_id, name, artifact_type,
                             description, created_at)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        """,
                        (project, artifact_id, name, type, description, now),
                    )
                elif description is not None:
                    cursor.execute(
                        """
                        UPDATE artifacts SET description = %s
                        WHERE project_id = %s AND artifact_id = %s
                        """,
                        (description, project, artifact_id),
                    )
                cursor.execute(
                    """
                    SELECT version_id, version_number FROM artifact_versions
                    WHERE project_id = %s AND artifact_id = %s
                      AND manifest_digest = %s LIMIT 1
                    """,
                    (project, artifact_id, manifest_digest),
                )
                existing_version = cursor.fetchone()
                created = existing_version is None
                if created:
                    cursor.execute(
                        """
                        SELECT MAX(version_number) AS max_version
                        FROM artifact_versions
                        WHERE project_id = %s AND artifact_id = %s
                        """,
                        (project, artifact_id),
                    )
                    maximum = cursor.fetchone()["max_version"]
                    version_number = 0 if maximum is None else int(maximum) + 1
                    cursor.execute(
                        """
                        INSERT INTO artifact_versions
                            (project_id, version_id, artifact_id, version_number,
                             manifest_digest, manifest, metadata, size_bytes,
                             producer_run_id, producer_run_name, created_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            project,
                            version_id,
                            artifact_id,
                            version_number,
                            manifest_digest,
                            _json(canonical),
                            _json(metadata) if metadata is not None else None,
                            size_bytes,
                            run_id,
                            run_name,
                            now,
                        ),
                    )
                else:
                    version_id = int(existing_version["version_id"])
                    version_number = int(existing_version["version_number"])
                    if metadata:
                        cursor.execute(
                            """
                            UPDATE artifact_versions SET metadata = %s
                            WHERE project_id = %s AND version_id = %s
                            """,
                            (_json(metadata), project, version_id),
                        )

                requested_aliases = list(aliases or [])
                if created:
                    requested_aliases.append("latest")
                for alias in requested_aliases:
                    if cas.ARTIFACT_VERSION_SPEC_RE.match(alias):
                        raise ValueError(
                            f"Alias '{alias}' is reserved for version pointers (vN); "
                            "choose another."
                        )
                    cursor.execute(
                        """
                        SELECT version_number FROM artifact_aliases
                        WHERE project_id = %s AND artifact_id = %s AND alias = %s
                        LIMIT 1
                        """,
                        (project, artifact_id, alias),
                    )
                    current = cursor.fetchone()
                    if (
                        current is not None
                        and int(current["version_number"]) > version_number
                    ):
                        continue
                    cursor.execute(
                        """
                        INSERT INTO artifact_aliases
                            (project_id, artifact_id, alias, version_id,
                             version_number, updated_at)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        """,
                        (
                            project,
                            artifact_id,
                            alias,
                            version_id,
                            version_number,
                            now,
                        ),
                    )
                cls._insert_run_artifact_link_with_cursor(
                    cursor,
                    project=project,
                    run_name=run_name,
                    run_id=run_id,
                    version_id=version_id,
                    direction="output",
                    now=now,
                )
        result = cls.get_artifact_manifest(project, name, f"v{version_number}")
        if result is None:
            raise RuntimeError("Doris artifact commit was not visible after write")
        return result

    @classmethod
    def get_artifact_manifest(
        cls, project: str, name: str, spec: str | None
    ) -> dict | None:
        with cls._connection() as connection, connection.cursor() as cursor:
            resolved = cls._resolve_artifact_version(cursor, project, name, spec)
            if resolved is None:
                return None
            cursor.execute(
                """
                SELECT av.version_id, av.version_number, av.manifest,
                       av.manifest_digest, av.metadata, av.size_bytes,
                       av.producer_run_id, av.producer_run_name, av.created_at,
                       a.name, a.artifact_type, a.description
                FROM artifact_versions av
                JOIN artifacts a
                  ON a.project_id = av.project_id
                 AND a.artifact_id = av.artifact_id
                WHERE av.project_id = %s AND av.version_id = %s
                LIMIT 1
                """,
                (project, resolved["version_id"]),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            cursor.execute(
                """
                SELECT alias FROM artifact_aliases
                WHERE project_id = %s AND version_id = %s
                ORDER BY alias
                """,
                (project, resolved["version_id"]),
            )
            aliases = [str(item["alias"]) for item in cursor.fetchall()]
            return {
                "artifact_id": resolved["artifact_id"],
                "version_id": int(row["version_id"]),
                "version": int(row["version_number"]),
                "name": row["name"],
                "type": row["artifact_type"],
                "description": row["description"],
                "manifest": _decode(row["manifest"]),
                "manifest_digest": row["manifest_digest"],
                "metadata": _decode(row["metadata"])
                if row["metadata"] is not None
                else None,
                "size_bytes": int(row["size_bytes"]),
                "producer_run_id": row["producer_run_id"],
                "producer_run_name": row["producer_run_name"],
                "created_at": row["created_at"],
                "aliases": aliases,
            }

    @classmethod
    def list_artifacts(cls, project: str) -> list[dict]:
        with cls._connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT artifact_id, name, artifact_type, description, created_at
                FROM artifacts WHERE project_id = %s
                ORDER BY artifact_type, name
                """,
                (project,),
            )
            artifacts = cursor.fetchall()
            cursor.execute(
                """
                SELECT version_id, artifact_id, version_number, manifest,
                       size_bytes, created_at
                FROM artifact_versions WHERE project_id = %s
                ORDER BY artifact_id, version_number DESC
                """,
                (project,),
            )
            versions = cursor.fetchall()
            cursor.execute(
                """
                SELECT alias, version_id FROM artifact_aliases
                WHERE project_id = %s
                """,
                (project,),
            )
            aliases = cursor.fetchall()
        aliases_by_version: dict[int, list[str]] = {}
        for row in aliases:
            aliases_by_version.setdefault(int(row["version_id"]), []).append(
                str(row["alias"])
            )
        versions_by_artifact: dict[int, list[dict[str, Any]]] = {}
        for row in versions:
            manifest = _decode(row["manifest"])
            versions_by_artifact.setdefault(int(row["artifact_id"]), []).append(
                {
                    "version_id": int(row["version_id"]),
                    "version": int(row["version_number"]),
                    "aliases": aliases_by_version.get(int(row["version_id"]), []),
                    "size_bytes": int(row["size_bytes"]),
                    "num_files": len(manifest),
                    "created_at": row["created_at"],
                }
            )
        return [
            {
                "name": artifact["name"],
                "type": artifact["artifact_type"],
                "description": artifact["description"],
                "created_at": artifact["created_at"],
                "num_versions": len(
                    versions_by_artifact.get(int(artifact["artifact_id"]), [])
                ),
                "latest_version": (
                    versions_by_artifact[int(artifact["artifact_id"])][0]["version"]
                    if versions_by_artifact.get(int(artifact["artifact_id"]))
                    else None
                ),
                "versions": versions_by_artifact.get(int(artifact["artifact_id"]), []),
            }
            for artifact in artifacts
        ]

    @classmethod
    def get_artifacts(cls, project: str) -> list[dict]:
        return [
            {
                "name": artifact["name"],
                "type": artifact["type"],
                "description": artifact["description"],
                "num_versions": artifact["num_versions"],
                "latest_version": artifact["latest_version"],
                "size_bytes": (
                    artifact["versions"][0]["size_bytes"]
                    if artifact["versions"]
                    else None
                ),
                "aliases": sorted(
                    {
                        alias
                        for version in artifact["versions"]
                        for alias in version["aliases"]
                    }
                ),
                "created_at": artifact["created_at"],
            }
            for artifact in cls.list_artifacts(project)
        ]

    @classmethod
    def _insert_run_artifact_link_with_cursor(
        cls,
        cursor: DictCursor,
        *,
        project: str,
        run_name: str | None,
        run_id: str | None,
        version_id: int,
        direction: str,
        now: str,
    ) -> None:
        if direction not in {"input", "output"}:
            raise ValueError(
                f"direction must be 'input' or 'output', got {direction!r}"
            )
        link_id = cls._stable_int(
            project, run_id or "", run_name or "", version_id, direction
        )
        cursor.execute(
            """
            INSERT INTO run_artifact_links
                (project_id, link_id, run_id, run_name, version_id, direction,
                 created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (project, link_id, run_id, run_name, version_id, direction, now),
        )

    @classmethod
    def insert_run_artifact_link(
        cls,
        project: str,
        run_name: str | None,
        run_id: str | None,
        version_id: int,
        direction: str,
    ) -> None:
        with cls._connection() as connection, connection.cursor() as cursor:
            cls._insert_run_artifact_link_with_cursor(
                cursor,
                project=project,
                run_name=run_name,
                run_id=run_id,
                version_id=version_id,
                direction=direction,
                now=datetime.now(timezone.utc).isoformat(),
            )

    @classmethod
    def get_run_artifacts(
        cls,
        project: str,
        run_name: str | None = None,
        run_id: str | None = None,
    ) -> dict[str, list[dict]]:
        with cls._connection() as connection, connection.cursor() as cursor:
            resolved = cls._resolve_run_id(cursor, project, run_name, run_id)
            if resolved is None:
                resolved = run_id
            if resolved is not None:
                where = "links.run_id = %s"
                identity: Any = resolved
            elif run_name is not None:
                where = "links.run_name = %s"
                identity = run_name
            else:
                return {"input": [], "output": []}
            cursor.execute(
                f"""
                SELECT links.direction, links.created_at, versions.version_id,
                       versions.version_number, versions.size_bytes,
                       artifacts.name, artifacts.artifact_type
                FROM run_artifact_links links
                JOIN artifact_versions versions
                  ON versions.project_id = links.project_id
                 AND versions.version_id = links.version_id
                JOIN artifacts
                  ON artifacts.project_id = versions.project_id
                 AND artifacts.artifact_id = versions.artifact_id
                WHERE links.project_id = %s AND {where}
                ORDER BY links.created_at, versions.version_id, links.direction
                """,
                (project, identity),
            )
            result: dict[str, list[dict]] = {"input": [], "output": []}
            for row in cursor.fetchall():
                result[str(row["direction"])].append(
                    {
                        "version_id": int(row["version_id"]),
                        "name": row["name"],
                        "type": row["artifact_type"],
                        "version": int(row["version_number"]),
                        "size_bytes": int(row["size_bytes"]),
                        "created_at": row["created_at"],
                    }
                )
            return result

    @classmethod
    def get_run_artifact_counts(cls, project: str) -> list[dict]:
        with cls._connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT DISTINCT run_id, run_name, version_id, direction
                FROM run_artifact_links
                WHERE project_id = %s
                """,
                (project,),
            )
            rows = list(cursor.fetchall())
        return cls._artifact_link_counts_from_rows(rows, cls.get_run_records(project))

    @classmethod
    def get_artifact_consumers(cls, project: str, version_id: int) -> list[dict]:
        with cls._connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT run_name, run_id, created_at
                FROM run_artifact_links
                WHERE project_id = %s AND version_id = %s
                  AND direction = 'input'
                ORDER BY created_at, run_name, run_id
                """,
                (project, version_id),
            )
            return list(cursor.fetchall())

    @classmethod
    def force_sync(cls) -> bool:
        return True

    @classmethod
    def export_to_parquet(cls) -> None:
        return None

    @classmethod
    def get_scheduler(cls) -> Any:
        return DummyCommitScheduler()

    @classmethod
    def get_project_db_path(cls, project: str) -> Any:
        del project
        raise RuntimeError("Doris projects do not have local database files")

    @classmethod
    def list_artifact_blobs_present(cls, project: str, digests: list[str]) -> list[str]:
        return [
            digest for digest in digests if cas.blob_path(project, digest).is_file()
        ]

    @classmethod
    def _unsupported(cls, *args: Any, **kwargs: Any) -> Any:
        del args, kwargs
        raise NotImplementedError(
            "This Trackio operation is not implemented by the Doris engine yet"
        )
