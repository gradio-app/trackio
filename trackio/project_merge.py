"""Combine one Trackio project that was logged by several parallel jobs (for
example Hugging Face Jobs that each upload their own bucket with
`upload_project_to_bucket`) into the local project database."""

import shutil
import sqlite3
import tempfile
from collections.abc import Iterable
from contextlib import ExitStack, closing
from pathlib import Path

import orjson

from trackio.bucket_storage import download_project_from_bucket
from trackio.cas import is_partial_blob
from trackio.sqlite_storage import SQLiteStorage
from trackio.utils import (
    canonical_project_name,
    deserialize_values,
    project_artifacts_dir,
    resolve_media_path,
    serialize_values,
)

ON_CONFLICT_CHOICES = ("error", "suffix")

_RUN_TABLES = ("configs", "metrics", "system_metrics", "alerts", "traces")
_LINK_TABLES = ("run_artifact_links", "external_run_artifact_links")
_ROW_KEYS = {
    "configs": ("run_id", ("run_id",)),
    "metrics": ("log_id", ("run_id", "timestamp", "step")),
    "system_metrics": ("log_id", ("run_id", "timestamp")),
    "alerts": ("alert_id", ("run_id", "timestamp", "title")),
    "traces": ("id", ("id",)),
}
_SKIPPED_COLUMNS = {
    "configs": {"id"},
    "metrics": {"id", "space_id"},
    "system_metrics": {"id", "space_id"},
    "alerts": {"id"},
    "traces": {"space_id"},
    "external_run_artifact_links": {"id"},
}
_MEDIA_COLUMNS = {
    "metrics": ("metrics",),
    "traces": ("messages", "metadata", "spans"),
}


class MergeConflictError(ValueError):
    """Raised when runs from different sources share a name and
    `on_conflict="error"`."""


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return SQLiteStorage._table_columns(conn, table)


def _resolve_source(project: str, source: str | Path) -> tuple[Path, Path]:
    path = Path(source).expanduser()
    if path.is_dir():
        db_path = path / SQLiteStorage.get_project_db_filename(project)
        root = path
    else:
        db_path = path
        root = path.parent
    if not db_path.is_file():
        raise FileNotFoundError(
            f"No database for project '{project}' found at '{db_path}'."
        )
    return db_path, root


def _open_read_only(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"{db_path.resolve().as_uri()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _run_names(conn: sqlite3.Connection, project: str) -> dict[str, str]:
    """Map every run_id in a database to its run name, in creation order."""
    if "run_name" in _columns(conn, "metrics") and "run_id" not in _columns(
        conn, "metrics"
    ):
        raise ValueError(
            "Database predates run ids (Trackio < 0.24). Open it once with a "
            "current Trackio to migrate it, then merge again."
        )
    names: dict[str, str] = {}
    for table in (*_RUN_TABLES, *_LINK_TABLES):
        columns = _columns(conn, table)
        if not {"run_id", "run_name"} <= columns:
            continue
        where = "run_id IS NOT NULL AND run_name IS NOT NULL"
        params: tuple = ()
        if table == "run_artifact_links" and "run_project" in columns:
            where += " AND (run_project IS NULL OR run_project = ?)"
            params = (project,)
        order_col = next(
            (c for c in ("created_at", "timestamp") if c in columns), "rowid"
        )
        for run_id, run_name in conn.execute(
            f"SELECT run_id, run_name FROM {table} WHERE {where} ORDER BY {order_col}",
            params,
        ):
            names.setdefault(run_id, run_name)
    return names


def _plan_run_names(
    dest_runs: dict[str, str],
    source_runs: list[dict[str, str]],
    labels: list[str],
    on_conflict: str,
) -> list[dict[str, str]]:
    """Decide the final run name for every run in every source. A run whose id
    is already known keeps the name it has; a new run keeps its own name unless
    a run from the destination or from another source already uses it."""
    owners: dict[str, set] = {}
    reserved = set(dest_runs.values()).union(*(runs.values() for runs in source_runs))
    for name in dest_runs.values():
        owners.setdefault(name, set()).add(None)
    assigned = dict(dest_runs)
    plans: list[dict[str, str]] = []
    conflicts: list[str] = []
    for index, runs in enumerate(source_runs):
        plan: dict[str, str] = {}
        for run_id, name in runs.items():
            if run_id in assigned:
                plan[run_id] = assigned[run_id]
                continue
            final = name
            if owners.get(name, set()) - {index}:
                if on_conflict == "error":
                    conflicts.append(f"'{name}' (from {labels[index]})")
                    continue
                suffix = 2
                while f"{name}-{suffix}" in owners or f"{name}-{suffix}" in reserved:
                    suffix += 1
                final = f"{name}-{suffix}"
            owners.setdefault(final, set()).add(index)
            assigned[run_id] = final
            plan[run_id] = final
        plans.append(plan)
    if conflicts:
        raise MergeConflictError(
            "Run name(s) already used by a different run: "
            + ", ".join(conflicts)
            + ". Rename the runs, or pass on_conflict='suffix' "
            "(--on-conflict suffix) to append -2, -3, ... to the incoming names."
        )
    return plans


def _rewrite_media(value, old_prefix: str, new_prefix: str):
    data = deserialize_values(orjson.loads(value))
    updated = SQLiteStorage._update_media_paths(data, old_prefix, new_prefix)
    return orjson.dumps(serialize_values(updated))


def _row_exists(
    dest: sqlite3.Connection, table: str, values: dict, key: str, fallback: tuple
) -> bool:
    key_columns = (key,) if values.get(key) is not None else fallback
    where = " AND ".join(f"{column} IS ?" for column in key_columns)
    return (
        dest.execute(
            f"SELECT 1 FROM {table} WHERE {where} LIMIT 1",
            [values[column] for column in key_columns],
        ).fetchone()
        is not None
    )


def _merge_run_table(
    dest: sqlite3.Connection,
    src: sqlite3.Connection,
    table: str,
    plan: dict[str, str],
    prefixes: dict[str, tuple[str, str]],
) -> int:
    src_columns = _columns(src, table)
    if "run_id" not in src_columns:
        return 0
    columns = sorted((src_columns & _columns(dest, table)) - _SKIPPED_COLUMNS[table])
    key, fallback = _ROW_KEYS[table]
    insert = (
        f"INSERT OR IGNORE INTO {table} ({', '.join(columns)}) "
        f"VALUES ({', '.join('?' for _ in columns)})"
    )
    inserted = 0
    for row in src.execute(f"SELECT {', '.join(columns)} FROM {table}"):
        values = dict(row)
        run_id = values["run_id"]
        if run_id not in plan:
            continue
        values["run_name"] = plan[run_id]
        if run_id in prefixes:
            for column in _MEDIA_COLUMNS.get(table, ()):
                if values.get(column) is not None:
                    values[column] = _rewrite_media(values[column], *prefixes[run_id])
        if _row_exists(dest, table, values, key, fallback):
            continue
        inserted += dest.execute(insert, [values[c] for c in columns]).rowcount
    return inserted


def _merge_artifacts(
    dest: sqlite3.Connection,
    src: sqlite3.Connection,
    plan: dict[str, str],
    project: str,
) -> int:
    """Replay the source's artifact versions in creation order through the same
    helpers `log_artifact` uses: identical content is deduplicated, new content
    gets the next free version number, and aliases only move forward."""
    if not _columns(src, "artifact_versions") or not _columns(src, "artifacts"):
        return 0
    version_map: dict[int, tuple[int, int, int]] = {}
    created_count = 0
    rows = src.execute(
        """SELECT av.id, av.manifest, av.metadata, av.producer_run_id,
               av.producer_run_name, av.created_at, a.name, a.type,
               a.description, a.created_at AS artifact_created_at
        FROM artifact_versions av JOIN artifacts a ON a.id = av.artifact_id
        ORDER BY av.created_at, av.id"""
    ).fetchall()
    for row in rows:
        known = dest.execute(
            "SELECT 1 FROM artifacts WHERE name = ?", (row["name"],)
        ).fetchone()
        artifact_id = SQLiteStorage._create_or_get_artifact_cursor(
            dest,
            row["name"],
            row["type"],
            None if known else row["description"],
            row["artifact_created_at"],
        )
        producer_id = row["producer_run_id"]
        producer_name = plan.get(producer_id, row["producer_run_name"])
        version_id, version, created = SQLiteStorage._insert_artifact_version_cursor(
            dest,
            artifact_id,
            orjson.loads(row["manifest"]),
            orjson.loads(row["metadata"]) if row["metadata"] else None,
            producer_id,
            producer_name,
            row["created_at"],
        )
        version_map[int(row["id"])] = (artifact_id, version_id, version)
        if created:
            created_count += 1
            SQLiteStorage._reassign_alias_cursor(
                dest, artifact_id, "latest", version_id
            )

    if _columns(src, "artifact_aliases"):
        for row in src.execute(
            "SELECT alias, artifact_version_id FROM artifact_aliases "
            "WHERE alias != 'latest'"
        ):
            mapped = version_map.get(int(row["artifact_version_id"]))
            if mapped is not None:
                SQLiteStorage._reassign_alias_forward_cursor(
                    dest, mapped[0], row["alias"], mapped[1], mapped[2]
                )

    link_columns = _columns(src, "run_artifact_links")
    if link_columns:
        project_col = "run_project" if "run_project" in link_columns else "NULL"
        for row in src.execute(
            f"""SELECT run_id, run_name, {project_col} AS run_project,
                   artifact_version_id, direction, created_at
            FROM run_artifact_links"""
        ):
            mapped = version_map.get(int(row["artifact_version_id"]))
            if mapped is None:
                continue
            local = row["run_project"] in (None, project)
            run_name = (
                plan.get(row["run_id"], row["run_name"]) if local else row["run_name"]
            )
            SQLiteStorage._insert_run_artifact_link_cursor(
                dest,
                run_name,
                row["run_id"],
                mapped[1],
                row["direction"],
                row["created_at"],
                run_project=row["run_project"],
            )

    external_columns = _columns(src, "external_run_artifact_links")
    if external_columns:
        columns = sorted(
            (external_columns & _columns(dest, "external_run_artifact_links"))
            - _SKIPPED_COLUMNS["external_run_artifact_links"]
        )
        insert = (
            f"INSERT OR IGNORE INTO external_run_artifact_links "
            f"({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})"
        )
        for row in src.execute(
            f"SELECT {', '.join(columns)} FROM external_run_artifact_links"
        ):
            values = dict(row)
            values["run_name"] = plan.get(values["run_id"], values["run_name"])
            dest.execute(insert, [values[c] for c in columns])
    return created_count


def _contained(base: Path, name: str) -> Path | None:
    path = base / name
    try:
        if path.resolve() == base.resolve() or not path.resolve().is_relative_to(
            base.resolve()
        ):
            return None
    except OSError:
        return None
    return path


def _copy_blobs(project: str, root: Path) -> None:
    source = root / "artifacts" / canonical_project_name(project)
    if not source.is_dir():
        return
    target_root = project_artifacts_dir(project)
    for blob in source.rglob("*"):
        if blob.is_symlink() or not blob.is_file() or is_partial_blob(blob.name):
            continue
        target = target_root / blob.relative_to(source)
        if target.exists():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(blob, target)


def _copy_media(project: str, root: Path, moves: Iterable[tuple[str, str]]) -> None:
    source_root = root / "media" / canonical_project_name(project)
    if not source_root.is_dir():
        return
    for source_name, final_name in sorted(set(moves)):
        source = _contained(source_root, source_name)
        if source is None or not source.is_dir():
            continue
        try:
            target = resolve_media_path(project, final_name)
        except ValueError:
            continue
        shutil.copytree(source, target, dirs_exist_ok=True)


def merge_project_dirs(
    project: str,
    sources: list[str | Path],
    on_conflict: str = "error",
    labels: list[str] | None = None,
) -> dict:
    """Merge `project` from several local copies into the local project database.

    Each source is either a directory laid out like `TRACKIO_DIR` (holding the
    project's `.db` file and optionally its `media/` and `artifacts/` folders)
    or the path of a project `.db` file. Runs are matched by run id, so merging
    the same source twice adds nothing; rows of a run that already exists are
    added only when missing (deduplicated by `log_id`, `alert_id`, or trace id).
    Configs are copied verbatim, keeping provenance keys such as `_Code` and
    `_Job` for `trackio verify`.

    Two different runs with the same name raise `MergeConflictError` unless
    `on_conflict="suffix"`, which renames the incoming run to `<name>-2`,
    `<name>-3`, ... and rewrites its media paths to match. Nothing is written
    when a conflict is raised.

    Returns a summary with each source's runs and the number of rows added
    per table.
    """
    if on_conflict not in ON_CONFLICT_CHOICES:
        raise ValueError(
            f"on_conflict must be one of {ON_CONFLICT_CHOICES}, got {on_conflict!r}"
        )
    if not sources:
        raise ValueError("At least one source is required.")
    labels = labels or [str(source) for source in sources]
    resolved = [_resolve_source(project, source) for source in sources]
    canonical = canonical_project_name(project)
    db_path = SQLiteStorage.init_db(project)
    rows_added = {table: 0 for table in _RUN_TABLES}
    artifact_versions_added = 0
    summary_sources = []
    media_moves: list[list[tuple[str, str]]] = []

    with ExitStack() as stack:
        source_conns = [
            stack.enter_context(closing(_open_read_only(src_db)))
            for src_db, _ in resolved
        ]
        with SQLiteStorage._get_process_lock(project):
            with SQLiteStorage._get_connection(db_path) as dest:
                dest_runs = _run_names(dest, project)
                source_runs = [_run_names(src, project) for src in source_conns]
                plans = _plan_run_names(dest_runs, source_runs, labels, on_conflict)
                known_ids = set(dest_runs)
                for index, src in enumerate(source_conns):
                    plan = plans[index]
                    runs = source_runs[index]
                    prefixes = {
                        run_id: (
                            f"{canonical}/{runs[run_id]}/",
                            f"{canonical}/{final}/",
                        )
                        for run_id, final in plan.items()
                        if final != runs[run_id]
                    }
                    _copy_blobs(project, resolved[index][1])
                    for table in _RUN_TABLES:
                        rows_added[table] += _merge_run_table(
                            dest, src, table, plan, prefixes
                        )
                    artifact_versions_added += _merge_artifacts(
                        dest, src, plan, project
                    )
                    summary_sources.append(
                        {
                            "source": labels[index],
                            "runs": [
                                {
                                    "run_id": run_id,
                                    "name": final,
                                    "source_name": runs[run_id],
                                    "status": "existing"
                                    if run_id in known_ids
                                    else "new",
                                }
                                for run_id, final in plan.items()
                            ],
                        }
                    )
                    known_ids.update(plan)
                    media_moves.append(
                        [(runs[run_id], final) for run_id, final in plan.items()]
                    )
                dest.commit()

    for index, (_, root) in enumerate(resolved):
        _copy_media(project, root, media_moves[index])

    return {
        "project": project,
        "db_path": str(db_path),
        "sources": summary_sources,
        "rows_added": rows_added,
        "artifact_versions_added": artifact_versions_added,
    }


def merge_project(
    project: str,
    buckets: list[str] | None = None,
    sources: list[str | Path] | None = None,
    on_conflict: str = "error",
) -> dict:
    """Merge `project` from Hugging Face buckets (each written by
    `upload_project_to_bucket`, e.g. one per parallel Job) and/or local
    directories into the local project database. See `merge_project_dirs`."""
    buckets = list(buckets or [])
    sources = list(sources or [])
    if not buckets and not sources:
        raise ValueError("Provide at least one bucket or source.")
    if on_conflict not in ON_CONFLICT_CHOICES:
        raise ValueError(
            f"on_conflict must be one of {ON_CONFLICT_CHOICES}, got {on_conflict!r}"
        )
    with tempfile.TemporaryDirectory() as tmp:
        bucket_dirs = []
        for index, bucket_id in enumerate(buckets):
            bucket_dir = Path(tmp) / str(index)
            download_project_from_bucket(project, bucket_id, bucket_dir)
            bucket_dirs.append(bucket_dir)
        return merge_project_dirs(
            project,
            [*bucket_dirs, *sources],
            on_conflict=on_conflict,
            labels=[f"hf://buckets/{b}" for b in buckets] + [str(s) for s in sources],
        )
