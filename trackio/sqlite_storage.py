import atexit
import hashlib
import json as json_mod
import os
import shutil
import sqlite3
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock, local
from typing import Any

try:
    import fcntl
except ImportError:
    fcntl = None

try:
    import msvcrt as _msvcrt
except ImportError:
    _msvcrt = None

import huggingface_hub as hf
import orjson

from trackio import cas
from trackio.commit_scheduler import CommitScheduler
from trackio.dummy_commit_scheduler import DummyCommitScheduler
from trackio.typehints import Manifest, Sha256Digest
from trackio.utils import (
    TRACKIO_DIR,
    _emit_nonfatal_warning,
    canonical_project_name,
    deserialize_values,
    get_color_palette,
    on_spaces,
    project_media_dir,
    serialize_values,
)

DB_EXT = ".db"

_JOURNAL_MODE_WHITELIST = frozenset(
    {"wal", "delete", "truncate", "persist", "memory", "off"}
)
_SYNCHRONOUS_WHITELIST = frozenset({"off", "normal", "full", "extra"})
_LOCKING_MODE_WHITELIST = frozenset({"normal", "exclusive"})
_TEMP_STORE_WHITELIST = frozenset({"default", "file", "memory"})
_READ_ONLY_QUERY_PREFIXES = ("select", "with", "pragma")
_QUERY_MAX_ROWS = 10_000
_READ_ONLY_PRAGMAS = frozenset(
    {"table_info", "table_xinfo", "index_list", "index_info", "index_xinfo"}
)


def _env_pragma_choice(name: str, whitelist: frozenset[str]) -> str | None:
    value = os.environ.get(name, "").strip().lower()
    if value in whitelist:
        return value.upper()
    return None


def _env_pragma_int(name: str) -> int | None:
    value = os.environ.get(name, "").strip()
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _configure_sqlite_pragmas(conn: sqlite3.Connection) -> None:
    override = os.environ.get("TRACKIO_SQLITE_JOURNAL_MODE", "").strip().lower()
    if override in _JOURNAL_MODE_WHITELIST:
        journal = override.upper()
    elif on_spaces():
        journal = "DELETE"
    else:
        journal = "WAL"
    conn.execute(f"PRAGMA journal_mode = {journal}")
    synchronous = (
        _env_pragma_choice("TRACKIO_SQLITE_SYNCHRONOUS", _SYNCHRONOUS_WHITELIST)
        or "NORMAL"
    )
    conn.execute(f"PRAGMA synchronous = {synchronous}")
    temp_store = (
        _env_pragma_choice("TRACKIO_SQLITE_TEMP_STORE", _TEMP_STORE_WHITELIST)
        or "MEMORY"
    )
    conn.execute(f"PRAGMA temp_store = {temp_store}")
    conn.execute("PRAGMA cache_size = -20000")
    mmap_size = _env_pragma_int("TRACKIO_SQLITE_MMAP_SIZE")
    conn.execute(f"PRAGMA mmap_size = {0 if mmap_size is None else mmap_size}")
    locking_mode = _env_pragma_choice(
        "TRACKIO_SQLITE_LOCKING_MODE", _LOCKING_MODE_WHITELIST
    )
    if locking_mode is not None:
        conn.execute(f"PRAGMA locking_mode = {locking_mode}")
    elif on_spaces():
        conn.execute("PRAGMA locking_mode = EXCLUSIVE")


_persistent_connections: dict[str, sqlite3.Connection] = {}
_persistent_lock = Lock()
_db_access_locks: dict[str, Lock] = {}


def _get_db_access_lock(db_path: Path) -> Lock:
    key = str(db_path)
    with _persistent_lock:
        if key not in _db_access_locks:
            _db_access_locks[key] = Lock()
        return _db_access_locks[key]


def _get_or_create_persistent_conn(
    db_path: Path, timeout: float = 30.0
) -> sqlite3.Connection:
    key = str(db_path)
    with _persistent_lock:
        conn = _persistent_connections.get(key)
        if conn is not None:
            try:
                conn.execute("SELECT 1")
                return conn
            except sqlite3.Error:
                try:
                    conn.close()
                except sqlite3.Error:
                    pass
                _persistent_connections.pop(key, None)
        conn = sqlite3.connect(str(db_path), timeout=timeout, check_same_thread=False)
        _configure_sqlite_pragmas(conn)
        conn.execute("SELECT 1")
        _persistent_connections[key] = conn
        return conn


def _close_all_persistent_connections() -> None:
    with _persistent_lock:
        for conn in _persistent_connections.values():
            try:
                conn.close()
            except sqlite3.Error:
                pass
        _persistent_connections.clear()


atexit.register(_close_all_persistent_connections)


class ProcessLock:
    """Lock used to coordinate database access.

    Normally uses file-based locking for cross-process coordination. When running
    on a bucket-mounted filesystem where file locks are unreliable,
    falls back to an in-memory threading Lock (single-process only)."""

    _thread_locks: dict[str, Lock] = {}
    _meta_lock = Lock()

    def __init__(self, lockfile_path: Path):
        self.lockfile_path = lockfile_path
        self.lockfile = None
        self._use_thread_lock = on_spaces()
        if self._use_thread_lock:
            key = str(lockfile_path)
            with ProcessLock._meta_lock:
                if key not in ProcessLock._thread_locks:
                    ProcessLock._thread_locks[key] = Lock()
                self._thread_lock = ProcessLock._thread_locks[key]

    def __enter__(self):
        if self._use_thread_lock:
            self._thread_lock.acquire()
            return self
        if fcntl is None and _msvcrt is None:
            return self
        self.lockfile_path.parent.mkdir(parents=True, exist_ok=True)
        self.lockfile = open(self.lockfile_path, "w")

        max_retries = 100
        for attempt in range(max_retries):
            try:
                if fcntl is not None:
                    fcntl.flock(self.lockfile.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                else:
                    _msvcrt.locking(self.lockfile.fileno(), _msvcrt.LK_NBLCK, 1)
                return self
            except (IOError, OSError):
                if attempt < max_retries - 1:
                    time.sleep(0.1)
                else:
                    raise IOError("Could not acquire database lock after 10 seconds")

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._use_thread_lock:
            self._thread_lock.release()
            return
        if self.lockfile:
            try:
                if fcntl is not None:
                    fcntl.flock(self.lockfile.fileno(), fcntl.LOCK_UN)
                elif _msvcrt is not None:
                    _msvcrt.locking(self.lockfile.fileno(), _msvcrt.LK_UNLCK, 1)
            except (IOError, OSError):
                pass
            self.lockfile.close()


_LOGS_READ_CACHE: dict[tuple[Any, ...], tuple[int, list[dict[str, Any]]]] = {}
_LOGS_READ_CACHE_LOCK = Lock()
_LOGS_READ_CACHE_MAX_KEYS = 512
_LOGS_READ_CACHE_MAX_ROWS_PER_ENTRY = 4000


def _spaces_logs_read_cache_enabled() -> bool:
    if not on_spaces():
        return False
    v = os.environ.get("TRACKIO_DISABLE_LOGS_CACHE", "").strip().lower()
    return v not in ("1", "true", "yes")


def _sqlite_db_invalidation_mtime_ns(db_path: Path) -> int | None:
    try:
        m = db_path.stat().st_mtime_ns
    except OSError:
        return None
    wal_path = db_path.with_name(db_path.name + "-wal")
    if wal_path.is_file():
        try:
            m = max(m, wal_path.stat().st_mtime_ns)
        except OSError:
            pass
    return m


def _logs_read_cache_key(
    project: str,
    run: str | None,
    run_id: str | None,
    max_points: int | None,
) -> tuple[Any, ...]:
    return (
        project,
        run or "",
        run_id or "",
        max_points if max_points is not None else -1,
    )


def _logs_read_cache_get(
    db_path: Path, key: tuple[Any, ...]
) -> list[dict[str, Any]] | None:
    if not _spaces_logs_read_cache_enabled():
        return None
    mtime_ns = _sqlite_db_invalidation_mtime_ns(db_path)
    if mtime_ns is None:
        return None
    with _LOGS_READ_CACHE_LOCK:
        item = _LOGS_READ_CACHE.get(key)
        if item is None:
            return None
        cached_mtime, logs = item
        if cached_mtime != mtime_ns:
            del _LOGS_READ_CACHE[key]
            return None
    return [{**d} for d in logs]


def _logs_read_cache_put(
    db_path: Path, key: tuple[Any, ...], logs: list[dict[str, Any]]
) -> None:
    if not _spaces_logs_read_cache_enabled():
        return
    if len(logs) > _LOGS_READ_CACHE_MAX_ROWS_PER_ENTRY:
        return
    mtime_ns = _sqlite_db_invalidation_mtime_ns(db_path)
    if mtime_ns is None:
        return
    snapshot = [{**d} for d in logs]
    with _LOGS_READ_CACHE_LOCK:
        while len(_LOGS_READ_CACHE) >= _LOGS_READ_CACHE_MAX_KEYS:
            _LOGS_READ_CACHE.pop(next(iter(_LOGS_READ_CACHE)))
        _LOGS_READ_CACHE[key] = (mtime_ns, snapshot)


_SYSTEM_LOGS_READ_CACHE: dict[tuple[Any, ...], tuple[int, list[dict[str, Any]]]] = {}


def _system_logs_read_cache_key(
    project: str,
    run: str | None,
    run_id: str | None,
    max_points: int | None = None,
) -> tuple[Any, ...]:
    return (
        "system_logs",
        project,
        run or "",
        run_id or "",
        max_points if max_points is not None else -1,
    )


def _system_logs_read_cache_get(
    db_path: Path, key: tuple[Any, ...]
) -> list[dict[str, Any]] | None:
    if not _spaces_logs_read_cache_enabled():
        return None
    mtime_ns = _sqlite_db_invalidation_mtime_ns(db_path)
    if mtime_ns is None:
        return None
    with _LOGS_READ_CACHE_LOCK:
        item = _SYSTEM_LOGS_READ_CACHE.get(key)
        if item is None:
            return None
        cached_mtime, logs = item
        if cached_mtime != mtime_ns:
            del _SYSTEM_LOGS_READ_CACHE[key]
            return None
    return [{**d} for d in logs]


def _system_logs_read_cache_put(
    db_path: Path, key: tuple[Any, ...], logs: list[dict[str, Any]]
) -> None:
    if not _spaces_logs_read_cache_enabled():
        return
    if len(logs) > _LOGS_READ_CACHE_MAX_ROWS_PER_ENTRY:
        return
    mtime_ns = _sqlite_db_invalidation_mtime_ns(db_path)
    if mtime_ns is None:
        return
    snapshot = [{**d} for d in logs]
    with _LOGS_READ_CACHE_LOCK:
        while len(_SYSTEM_LOGS_READ_CACHE) >= _LOGS_READ_CACHE_MAX_KEYS:
            _SYSTEM_LOGS_READ_CACHE.pop(next(iter(_SYSTEM_LOGS_READ_CACHE)))
        _SYSTEM_LOGS_READ_CACHE[key] = (mtime_ns, snapshot)


class SQLiteStorage:
    _dataset_import_attempted = False
    _dataset_import_pending = False
    _dataset_remote_synced = False
    _dataset_loading = local()
    _current_scheduler: CommitScheduler | DummyCommitScheduler | None = None
    _scheduler_lock = Lock()

    _ARTIFACT_PARQUET_TABLES: dict[str, list[str]] = {
        "artifacts": ["id", "name", "type", "description", "created_at"],
        "artifact_versions": [
            "id",
            "artifact_id",
            "version",
            "manifest_digest",
            "manifest",
            "metadata",
            "size_bytes",
            "producer_run_id",
            "producer_run_name",
            "created_at",
        ],
        "artifact_aliases": ["artifact_id", "alias", "artifact_version_id"],
        "run_artifact_links": [
            "id",
            "run_id",
            "run_name",
            "artifact_version_id",
            "direction",
            "created_at",
        ],
    }

    @staticmethod
    @contextmanager
    def _get_connection(
        db_path: Path,
        *,
        timeout: float = 30.0,
        configure_pragmas: bool = True,
        row_factory=sqlite3.Row,
    ) -> Iterator[sqlite3.Connection]:
        if on_spaces():
            # On Spaces, all callers share a single persistent connection
            # that is pragma-configured at creation time. The `configure_pragmas`
            # flag is intentionally ignored here — the pragmas (journal mode,
            # synchronous, locking mode) don't affect query semantics.
            access_lock = _get_db_access_lock(db_path)
            access_lock.acquire()
            try:
                conn = _get_or_create_persistent_conn(db_path, timeout=timeout)
                conn.row_factory = row_factory
                with conn:
                    yield conn
            finally:
                access_lock.release()
        else:
            conn = sqlite3.connect(str(db_path), timeout=timeout)
            try:
                if configure_pragmas:
                    _configure_sqlite_pragmas(conn)
                if row_factory is not None:
                    conn.row_factory = row_factory
                with conn:
                    yield conn
            finally:
                conn.close()

    @staticmethod
    def _get_process_lock(project: str) -> ProcessLock:
        lockfile_path = TRACKIO_DIR / f"{canonical_project_name(project)}.lock"
        return ProcessLock(lockfile_path)

    @staticmethod
    def get_project_db_filename(project: str) -> str:
        """Get the database filename for a specific project."""
        return f"{canonical_project_name(project)}{DB_EXT}"

    @staticmethod
    def get_project_db_path(project: str) -> Path:
        """Get the database path for a specific project."""
        filename = SQLiteStorage.get_project_db_filename(project)
        return TRACKIO_DIR / filename

    @staticmethod
    def validate_project_name(project: str) -> None:
        """Reject project names whose canonical on-disk identity would collide
        with the parquet sidecar files trackio writes for another project's
        metrics/artifact tables (e.g. a project ``model_artifacts`` shares the
        file ``model_artifacts.parquet`` with project ``model``'s artifacts
        sidecar)."""
        reserved = tuple(
            f"_{table}"
            for table in (
                "system",
                "configs",
                "traces",
                *SQLiteStorage._ARTIFACT_PARQUET_TABLES,
            )
        )
        canonical = canonical_project_name(project)
        for suffix in reserved:
            if len(canonical) > len(suffix) and canonical.endswith(suffix):
                sibling = canonical[: -len(suffix)]
                raise ValueError(
                    f"Project name {project!r} is not allowed: its on-disk name "
                    f"{canonical!r} ends with the reserved suffix {suffix!r}, which "
                    f"collides with the parquet sidecar files trackio writes for a "
                    f"project named {sibling!r}. Choose a different project name."
                )

    @staticmethod
    def init_db(project: str) -> Path:
        """
        Initialize the SQLite database with required tables.
        Returns the database path.
        """
        SQLiteStorage._ensure_hub_loaded()
        db_path = SQLiteStorage.get_project_db_path(project)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        with SQLiteStorage._get_process_lock(project):
            with SQLiteStorage._get_connection(db_path, row_factory=None) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS metrics (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        run_id TEXT NOT NULL,
                        timestamp TEXT NOT NULL,
                        run_name TEXT NOT NULL,
                        step INTEGER NOT NULL,
                        metrics TEXT NOT NULL
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS configs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        run_id TEXT NOT NULL,
                        run_name TEXT NOT NULL,
                        config TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        UNIQUE(run_id)
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS system_metrics (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        run_id TEXT NOT NULL,
                        timestamp TEXT NOT NULL,
                        run_name TEXT NOT NULL,
                        metrics TEXT NOT NULL
                    )
                    """
                )

                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS traces (
                        id TEXT PRIMARY KEY,
                        run_id TEXT NOT NULL,
                        timestamp TEXT NOT NULL,
                        run_name TEXT NOT NULL,
                        step INTEGER NOT NULL,
                        key TEXT NOT NULL,
                        trace_index INTEGER,
                        messages TEXT NOT NULL,
                        metadata TEXT NOT NULL,
                        search_text TEXT NOT NULL,
                        log_id TEXT,
                        space_id TEXT
                    )
                    """
                )

                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS project_metadata (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL
                    )
                    """
                )

                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS pending_uploads (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        space_id TEXT NOT NULL,
                        run_id TEXT,
                        run_name TEXT,
                        step INTEGER,
                        file_path TEXT NOT NULL,
                        relative_path TEXT,
                        created_at TEXT NOT NULL
                    )
                    """
                )

                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS alerts (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        run_id TEXT NOT NULL,
                        timestamp TEXT NOT NULL,
                        run_name TEXT NOT NULL,
                        title TEXT NOT NULL,
                        text TEXT,
                        level TEXT NOT NULL DEFAULT 'warn',
                        step INTEGER,
                        alert_id TEXT
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS artifacts (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name TEXT NOT NULL UNIQUE,
                        type TEXT NOT NULL,
                        description TEXT,
                        created_at TEXT NOT NULL
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS artifact_versions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        artifact_id INTEGER NOT NULL REFERENCES artifacts(id),
                        version INTEGER NOT NULL,
                        manifest_digest TEXT NOT NULL,
                        manifest TEXT NOT NULL,
                        metadata TEXT,
                        size_bytes INTEGER NOT NULL,
                        producer_run_id TEXT,
                        producer_run_name TEXT,
                        created_at TEXT NOT NULL,
                        UNIQUE(artifact_id, version),
                        UNIQUE(artifact_id, manifest_digest)
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS artifact_aliases (
                        artifact_id INTEGER NOT NULL REFERENCES artifacts(id),
                        alias TEXT NOT NULL,
                        artifact_version_id INTEGER NOT NULL REFERENCES artifact_versions(id),
                        PRIMARY KEY (artifact_id, alias)
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS run_artifact_links (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        run_id TEXT,
                        run_name TEXT,
                        artifact_version_id INTEGER NOT NULL REFERENCES artifact_versions(id),
                        direction TEXT NOT NULL CHECK(direction IN ('input', 'output')),
                        created_at TEXT NOT NULL
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_run_artifact_links_run
                    ON run_artifact_links(run_id, run_name)
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_run_artifact_links_version
                    ON run_artifact_links(artifact_version_id)
                    """
                )
                cursor.execute(
                    """
                    CREATE UNIQUE INDEX IF NOT EXISTS idx_run_artifact_links_unique
                    ON run_artifact_links(run_id, artifact_version_id, direction)
                    """
                )
                for col in ("kind TEXT NOT NULL DEFAULT 'media'", "digest TEXT"):
                    try:
                        cursor.execute(f"ALTER TABLE pending_uploads ADD COLUMN {col}")
                    except sqlite3.OperationalError:
                        pass
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_pending_uploads_kind
                    ON pending_uploads(kind)
                    """
                )
                metrics_cols = SQLiteStorage._table_columns(conn, "metrics")
                metrics_run_key = "run_id" if "run_id" in metrics_cols else "run_name"
                cursor.execute(
                    f"""
                    CREATE INDEX IF NOT EXISTS idx_metrics_run_step
                    ON metrics({metrics_run_key}, step)
                    """
                )
                cursor.execute(
                    f"""
                    CREATE INDEX IF NOT EXISTS idx_metrics_run_timestamp
                    ON metrics({metrics_run_key}, timestamp)
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_configs_run_name
                    ON configs(run_name)
                    """
                )
                system_cols = SQLiteStorage._table_columns(conn, "system_metrics")
                system_run_key = "run_id" if "run_id" in system_cols else "run_name"
                cursor.execute(
                    f"""
                    CREATE INDEX IF NOT EXISTS idx_system_metrics_run_timestamp
                    ON system_metrics({system_run_key}, timestamp)
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_traces_run_step
                    ON traces(run_id, step)
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_traces_run_timestamp
                    ON traces(run_id, timestamp)
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_traces_search
                    ON traces(search_text)
                    """
                )
                alerts_cols = SQLiteStorage._table_columns(conn, "alerts")
                alerts_run_key = "run_id" if "run_id" in alerts_cols else "run_name"
                cursor.execute(
                    f"""
                    CREATE INDEX IF NOT EXISTS idx_alerts_run
                    ON alerts({alerts_run_key})
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_alerts_timestamp
                    ON alerts(timestamp)
                    """
                )
                cursor.execute(
                    """
                    CREATE UNIQUE INDEX IF NOT EXISTS idx_alerts_alert_id
                    ON alerts(alert_id) WHERE alert_id IS NOT NULL
                    """
                )

                for table in ("metrics", "system_metrics"):
                    for col in ("log_id TEXT", "space_id TEXT"):
                        try:
                            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {col}")
                        except sqlite3.OperationalError:
                            pass
                    cursor.execute(
                        f"""CREATE UNIQUE INDEX IF NOT EXISTS idx_{table}_log_id
                        ON {table}(log_id) WHERE log_id IS NOT NULL"""
                    )
                    cursor.execute(
                        f"""CREATE INDEX IF NOT EXISTS idx_{table}_pending
                        ON {table}(space_id) WHERE space_id IS NOT NULL"""
                    )

                conn.commit()
        return db_path

    @staticmethod
    def _require_pyarrow():
        try:
            import pyarrow as pa
            import pyarrow.parquet as pq
        except ImportError as e:
            raise ImportError(
                "Parquet import/export requires `trackio[spaces]`."
            ) from e
        return pa, pq

    @staticmethod
    def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
        cursor = conn.cursor()
        try:
            cursor.execute(f"PRAGMA table_info({table})")
        except sqlite3.OperationalError:
            return set()
        return {row[1] for row in cursor.fetchall()}

    @staticmethod
    def _supports_run_ids(conn: sqlite3.Connection, table: str = "metrics") -> bool:
        return "run_id" in SQLiteStorage._table_columns(conn, table)

    @staticmethod
    def _resolve_run_identity(
        conn: sqlite3.Connection,
        run_name: str | None = None,
        run_id: str | None = None,
        *,
        table: str = "metrics",
    ) -> tuple[str, str] | None:
        supports_run_ids = SQLiteStorage._supports_run_ids(conn, table)
        if supports_run_ids:
            if run_id is not None:
                return ("run_id", run_id)
            if run_name is None:
                return None
            source_table = (
                table
                if "timestamp" in SQLiteStorage._table_columns(conn, table)
                else "metrics"
            )
            cursor = conn.cursor()
            cursor.execute(
                f"""
                SELECT run_id
                FROM {source_table}
                WHERE run_name = ?
                GROUP BY run_id
                ORDER BY MIN(timestamp) DESC
                LIMIT 1
                """,
                (run_name,),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            return ("run_id", row[0])

        resolved = run_name if run_name is not None else run_id
        if resolved is None:
            return None
        return ("run_name", resolved)

    @staticmethod
    def get_run_records(project: str) -> list[dict[str, str | None]]:
        SQLiteStorage._ensure_hub_loaded()
        db_path = SQLiteStorage.get_project_db_path(project)
        if not db_path.exists():
            return []

        try:
            with SQLiteStorage._get_connection(db_path) as conn:
                cursor = conn.cursor()
                if SQLiteStorage._supports_run_ids(conn):
                    cursor.execute(
                        """
                        SELECT run_id, run_name, MIN(timestamp) as created_at
                        FROM metrics
                        GROUP BY run_id, run_name
                        ORDER BY created_at ASC
                        """
                    )
                    return [
                        {
                            "id": row["run_id"],
                            "name": row["run_name"],
                            "created_at": row["created_at"],
                        }
                        for row in cursor.fetchall()
                    ]

                cursor.execute(
                    """
                    SELECT run_name, MIN(timestamp) as created_at
                    FROM metrics
                    GROUP BY run_name
                    ORDER BY created_at ASC
                    """
                )
                return [
                    {
                        "id": row["run_name"],
                        "name": row["run_name"],
                        "created_at": row["created_at"],
                    }
                    for row in cursor.fetchall()
                ]
        except sqlite3.OperationalError as e:
            if "no such table: metrics" in str(e):
                return []
            raise

    @staticmethod
    def get_latest_run_record_by_name(
        project: str, run_name: str
    ) -> dict[str, str | None] | None:
        db_path = SQLiteStorage.get_project_db_path(project)
        if not db_path.exists():
            return None

        with SQLiteStorage._get_connection(db_path) as conn:
            cursor = conn.cursor()
            if SQLiteStorage._supports_run_ids(conn):
                cursor.execute(
                    """
                    SELECT run_id, run_name, MIN(timestamp) as created_at
                    FROM metrics
                    WHERE run_name = ?
                    GROUP BY run_id, run_name
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    (run_name,),
                )
                row = cursor.fetchone()
                if row is None:
                    return None
                return {
                    "id": row["run_id"],
                    "name": row["run_name"],
                    "created_at": row["created_at"],
                }

            cursor.execute(
                """
                SELECT run_name, MIN(timestamp) as created_at
                FROM metrics
                WHERE run_name = ?
                GROUP BY run_name
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (run_name,),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            return {
                "id": row["run_name"],
                "name": row["run_name"],
                "created_at": row["created_at"],
            }

    @staticmethod
    def _normalize_trace_rows_for_parquet(
        rows: list[dict[str, object]],
    ) -> list[dict[str, object]]:
        normalized: list[dict[str, object]] = []
        for row in rows:
            new_row = dict(row)
            for col in ("messages", "metadata"):
                value = new_row.get(col)
                if value is None:
                    continue
                if isinstance(value, memoryview):
                    value = value.tobytes()
                if isinstance(value, (bytes, bytearray)):
                    new_row[col] = bytes(value).decode("utf-8")
                elif not isinstance(value, str):
                    new_row[col] = orjson.dumps(value).decode("utf-8")
            normalized.append(new_row)
        return normalized

    @staticmethod
    def _read_table_rows(db_path: Path, table: str) -> list[dict[str, object]]:
        try:
            with SQLiteStorage._get_connection(
                db_path, timeout=5.0, configure_pragmas=False
            ) as conn:
                cursor = conn.cursor()
                cursor.execute(f"SELECT * FROM {table}")
                return [dict(row) for row in cursor.fetchall()]
        except Exception:
            return []

    @staticmethod
    def _decode_json_blob(value: object) -> dict[str, object]:
        if value is None:
            return {}
        if isinstance(value, memoryview):
            value = value.tobytes()
        return deserialize_values(orjson.loads(value))

    @staticmethod
    def _flatten_json_rows(
        rows: list[dict[str, object]], json_col: str
    ) -> list[dict[str, object]]:
        flattened_rows = []
        for row in rows:
            flat_row = {key: value for key, value in row.items() if key != json_col}
            expanded = SQLiteStorage._decode_json_blob(row.get(json_col))
            for key, value in expanded.items():
                if key not in flat_row:
                    flat_row[key] = value
            flattened_rows.append(flat_row)
        return flattened_rows

    @staticmethod
    def _write_parquet_rows(parquet_path: Path, rows: list[dict[str, object]]) -> None:
        if not rows:
            return
        pa, pq = SQLiteStorage._require_pyarrow()
        column_names: list[str] = []
        seen_columns: set[str] = set()
        for row in rows:
            for key in row:
                if key not in seen_columns:
                    column_names.append(key)
                    seen_columns.add(key)
        normalized_rows = [{key: row.get(key) for key in column_names} for row in rows]
        table = pa.Table.from_pylist(normalized_rows)
        write_kwargs = {
            "write_page_index": True,
            "use_content_defined_chunking": True,
        }
        try:
            pq.write_table(table, parquet_path, **write_kwargs)
        except TypeError:
            pq.write_table(table, parquet_path)

    @staticmethod
    def _read_parquet_rows(parquet_path: Path) -> list[dict[str, object]]:
        _, pq = SQLiteStorage._require_pyarrow()
        return pq.read_table(parquet_path).to_pylist()

    @staticmethod
    def _normalize_json_column_value(value: object) -> object:
        if value is None:
            return orjson.dumps({})
        if isinstance(value, memoryview):
            return value.tobytes()
        if isinstance(value, (bytes, bytearray, str)):
            return value
        return orjson.dumps(serialize_values(value))

    @staticmethod
    def _rows_to_sql_table_rows(
        rows: list[dict[str, object]],
        *,
        json_col: str,
        structural_cols: list[str],
    ) -> list[dict[str, object]]:
        sql_rows = []
        for row in rows:
            sql_row = {col: row.get(col) for col in structural_cols}
            if json_col in row:
                sql_row[json_col] = SQLiteStorage._normalize_json_column_value(
                    row.get(json_col)
                )
            else:
                payload = {
                    key: value
                    for key, value in row.items()
                    if key not in structural_cols and key != json_col
                }
                sql_row[json_col] = orjson.dumps(serialize_values(payload))
            sql_rows.append(sql_row)
        return sql_rows

    @staticmethod
    def _replace_table_rows(
        db_path: Path,
        table: str,
        rows: list[dict[str, object]],
        columns: list[str],
    ) -> None:
        with SQLiteStorage._get_connection(
            db_path, configure_pragmas=False, row_factory=None
        ) as conn:
            cursor = conn.cursor()
            cursor.execute(f"DELETE FROM {table}")
            if rows:
                placeholders = ", ".join(["?"] * len(columns))
                cursor.executemany(
                    f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})",
                    [[row.get(column) for column in columns] for row in rows],
                )
            conn.commit()

    @staticmethod
    def _flatten_and_write_parquet(
        db_path: Path, table: str, json_col: str, parquet_path: Path
    ) -> None:
        db_mtime_ns = _sqlite_db_invalidation_mtime_ns(db_path)
        if (
            parquet_path.exists()
            and db_mtime_ns is not None
            and db_mtime_ns < parquet_path.stat().st_mtime_ns
        ):
            return
        rows = SQLiteStorage._read_table_rows(db_path, table)
        if not rows:
            return
        flat_rows = SQLiteStorage._flatten_json_rows(rows, json_col)
        SQLiteStorage._write_parquet_rows(parquet_path, flat_rows)

    @staticmethod
    def export_to_parquet():
        """
        Exports all projects' DB files as Parquet under the same path but with extension ".parquet".
        Also exports system_metrics to separate parquet files with "_system.parquet" suffix.
        Also exports configs to separate parquet files with "_configs.parquet" suffix.
        """
        if not SQLiteStorage._dataset_import_attempted:
            return
        if not TRACKIO_DIR.exists():
            return

        all_paths = os.listdir(TRACKIO_DIR)
        db_names = [f for f in all_paths if f.endswith(DB_EXT)]
        for db_name in db_names:
            db_path = TRACKIO_DIR / db_name
            SQLiteStorage._flatten_and_write_parquet(
                db_path, "metrics", "metrics", db_path.with_suffix(".parquet")
            )
            SQLiteStorage._flatten_and_write_parquet(
                db_path,
                "system_metrics",
                "metrics",
                TRACKIO_DIR / (db_path.stem + "_system.parquet"),
            )
            SQLiteStorage._flatten_and_write_parquet(
                db_path,
                "configs",
                "config",
                TRACKIO_DIR / (db_path.stem + "_configs.parquet"),
            )
            trace_rows = SQLiteStorage._read_table_rows(db_path, "traces")
            if trace_rows:
                SQLiteStorage._write_parquet_rows(
                    TRACKIO_DIR / (db_path.stem + "_traces.parquet"),
                    SQLiteStorage._normalize_trace_rows_for_parquet(trace_rows),
                )
            db_mtime_ns = _sqlite_db_invalidation_mtime_ns(db_path)
            for table in SQLiteStorage._ARTIFACT_PARQUET_TABLES:
                parquet_path = TRACKIO_DIR / f"{db_path.stem}_{table}.parquet"
                if (
                    parquet_path.exists()
                    and db_mtime_ns is not None
                    and db_mtime_ns < parquet_path.stat().st_mtime_ns
                ):
                    continue
                artifact_rows = SQLiteStorage._read_table_rows(db_path, table)
                if artifact_rows:
                    SQLiteStorage._write_parquet_rows(parquet_path, artifact_rows)

    @staticmethod
    def export_for_static_space(
        project: str, output_dir: Path, db_path_override: Path | None = None
    ) -> None:
        """
        Exports a single project's data as Parquet + JSON files for static Space deployment.

        Args:
            project: The project name.
            output_dir: Directory to write the exported files to.
            db_path_override: If provided, read from this DB file instead of the
                default local project path. Useful when exporting from a downloaded
                remote database.
        """
        db_path = db_path_override or SQLiteStorage.get_project_db_path(project)
        if not db_path.exists():
            raise FileNotFoundError(f"No database found for project '{project}'")

        output_dir.mkdir(parents=True, exist_ok=True)
        aux_dir = output_dir / "aux"
        aux_dir.mkdir(parents=True, exist_ok=True)

        metrics_rows = SQLiteStorage._read_table_rows(db_path, "metrics")
        if metrics_rows:
            flat = SQLiteStorage._flatten_json_rows(metrics_rows, "metrics")
            SQLiteStorage._write_parquet_rows(output_dir / "metrics.parquet", flat)

        sys_rows = SQLiteStorage._read_table_rows(db_path, "system_metrics")
        if sys_rows:
            flat = SQLiteStorage._flatten_json_rows(sys_rows, "metrics")
            SQLiteStorage._write_parquet_rows(aux_dir / "system_metrics.parquet", flat)

        trace_rows = SQLiteStorage._read_table_rows(db_path, "traces")
        if trace_rows:
            SQLiteStorage._write_parquet_rows(
                aux_dir / "traces.parquet",
                SQLiteStorage._normalize_trace_rows_for_parquet(trace_rows),
            )

        configs_rows = SQLiteStorage._read_table_rows(db_path, "configs")
        if configs_rows:
            flat = SQLiteStorage._flatten_json_rows(configs_rows, "config")
            SQLiteStorage._write_parquet_rows(aux_dir / "configs.parquet", flat)

        try:
            with SQLiteStorage._get_connection(db_path) as conn:
                cursor = conn.cursor()
                if SQLiteStorage._supports_run_ids(conn):
                    cursor.execute(
                        """SELECT run_id, run_name, MIN(timestamp) as created_at,
                        MAX(step) as last_step, COUNT(*) as log_count
                        FROM metrics
                        GROUP BY run_id, run_name
                        ORDER BY created_at ASC"""
                    )
                    rows = cursor.fetchall()
                    runs_meta = [
                        {
                            "id": row["run_id"],
                            "name": row["run_name"],
                            "created_at": row["created_at"],
                            "last_step": row["last_step"],
                            "log_count": row["log_count"],
                        }
                        for row in rows
                    ]
                else:
                    cursor.execute(
                        """SELECT run_name, MIN(timestamp) as created_at,
                        MAX(step) as last_step, COUNT(*) as log_count
                        FROM metrics GROUP BY run_name ORDER BY created_at ASC"""
                    )
                    rows = cursor.fetchall()
                    runs_meta = [
                        {
                            "id": row["run_name"],
                            "name": row["run_name"],
                            "created_at": row["created_at"],
                            "last_step": row["last_step"],
                            "log_count": row["log_count"],
                        }
                        for row in rows
                    ]
        except sqlite3.OperationalError:
            runs_meta = []
        with open(output_dir / "runs.json", "w") as f:
            json_mod.dump(runs_meta, f)

        settings = {
            "color_palette": get_color_palette(),
            "plot_order": [
                item.strip()
                for item in os.environ.get("TRACKIO_PLOT_ORDER", "").split(",")
                if item.strip()
            ],
        }
        with open(output_dir / "settings.json", "w") as f:
            json_mod.dump(settings, f)

    @staticmethod
    def _cleanup_wal_sidecars(db_path: Path) -> None:
        """Remove leftover -wal/-shm files for a DB basename (prevents disk I/O errors)."""
        for suffix in ("-wal", "-shm"):
            sidecar = Path(str(db_path) + suffix)
            try:
                if sidecar.exists():
                    sidecar.unlink()
            except Exception:
                pass

    @staticmethod
    def _project_parquet_paths(db_path: Path) -> list[Path]:
        """Every parquet file that export_to_parquet writes for a project: the
        metrics file plus the system/configs/traces and per-artifact-table
        sidecars. Deleting these alongside the .db removes the project's durable
        form, so import_from_parquet cannot resurrect it from a lingering sidecar.
        """
        stem = db_path.stem
        suffixes = [
            ".parquet",
            "_system.parquet",
            "_configs.parquet",
            "_traces.parquet",
        ]
        suffixes += [
            f"_{table}.parquet" for table in SQLiteStorage._ARTIFACT_PARQUET_TABLES
        ]
        return [db_path.with_name(f"{stem}{suffix}") for suffix in suffixes]

    @staticmethod
    def import_from_parquet():
        """
        Imports to all DB files that have matching files under the same path but with extension ".parquet".
        Also imports system_metrics from "_system.parquet" files.
        Also imports configs from "_configs.parquet" files.
        """
        if not TRACKIO_DIR.exists():
            return

        all_paths = os.listdir(TRACKIO_DIR)
        all_paths_set = set(all_paths)

        def _artifact_sidecar(pq_name: str) -> tuple[str, str] | None:
            for table in SQLiteStorage._ARTIFACT_PARQUET_TABLES:
                suffix = f"_{table}.parquet"
                if not pq_name.endswith(suffix) or len(pq_name) <= len(suffix):
                    continue
                base = pq_name[: -len(suffix)]
                if (
                    f"{base}.parquet" in all_paths_set
                    or (TRACKIO_DIR / f"{base}{DB_EXT}").exists()
                    or f"{base}_artifact_versions.parquet" in all_paths_set
                ):
                    return base, table
            return None

        parquet_names = [
            f
            for f in all_paths
            if f.endswith(".parquet")
            and not f.endswith("_system.parquet")
            and not f.endswith("_configs.parquet")
            and not f.endswith("_traces.parquet")
            and _artifact_sidecar(f) is None
        ]
        imported_projects = {Path(name).stem for name in parquet_names}
        for pq_name in parquet_names:
            parquet_path = TRACKIO_DIR / pq_name
            db_path = parquet_path.with_suffix(DB_EXT)

            SQLiteStorage._cleanup_wal_sidecars(db_path)

            rows = SQLiteStorage._read_parquet_rows(parquet_path)
            project = db_path.stem
            SQLiteStorage.init_db(project)
            metrics_rows = SQLiteStorage._rows_to_sql_table_rows(
                rows,
                json_col="metrics",
                structural_cols=[
                    "id",
                    "run_id",
                    "timestamp",
                    "run_name",
                    "step",
                    "log_id",
                    "space_id",
                ],
            )
            SQLiteStorage._replace_table_rows(
                db_path,
                "metrics",
                metrics_rows,
                [
                    "id",
                    "run_id",
                    "timestamp",
                    "run_name",
                    "step",
                    "metrics",
                    "log_id",
                    "space_id",
                ],
            )

        system_parquet_names = [f for f in all_paths if f.endswith("_system.parquet")]
        for pq_name in system_parquet_names:
            parquet_path = TRACKIO_DIR / pq_name
            db_name = pq_name.replace("_system.parquet", DB_EXT)
            db_path = TRACKIO_DIR / db_name
            project_name = db_path.stem
            if project_name not in imported_projects and not db_path.exists():
                continue

            rows = SQLiteStorage._read_parquet_rows(parquet_path)
            SQLiteStorage.init_db(project_name)
            system_rows = SQLiteStorage._rows_to_sql_table_rows(
                rows,
                json_col="metrics",
                structural_cols=[
                    "id",
                    "run_id",
                    "timestamp",
                    "run_name",
                    "log_id",
                    "space_id",
                ],
            )
            SQLiteStorage._replace_table_rows(
                db_path,
                "system_metrics",
                system_rows,
                [
                    "id",
                    "run_id",
                    "timestamp",
                    "run_name",
                    "metrics",
                    "log_id",
                    "space_id",
                ],
            )

        configs_parquet_names = [f for f in all_paths if f.endswith("_configs.parquet")]
        for pq_name in configs_parquet_names:
            parquet_path = TRACKIO_DIR / pq_name
            db_name = pq_name.replace("_configs.parquet", DB_EXT)
            db_path = TRACKIO_DIR / db_name
            project_name = db_path.stem
            if project_name not in imported_projects and not db_path.exists():
                continue

            rows = SQLiteStorage._read_parquet_rows(parquet_path)
            SQLiteStorage.init_db(project_name)
            config_rows = SQLiteStorage._rows_to_sql_table_rows(
                rows,
                json_col="config",
                structural_cols=["id", "run_id", "run_name", "created_at"],
            )
            SQLiteStorage._replace_table_rows(
                db_path,
                "configs",
                config_rows,
                ["id", "run_id", "run_name", "config", "created_at"],
            )

        traces_parquet_names = [f for f in all_paths if f.endswith("_traces.parquet")]
        for pq_name in traces_parquet_names:
            parquet_path = TRACKIO_DIR / pq_name
            db_name = pq_name.replace("_traces.parquet", DB_EXT)
            db_path = TRACKIO_DIR / db_name
            project_name = db_path.stem
            if project_name not in imported_projects and not db_path.exists():
                continue

            rows = SQLiteStorage._read_parquet_rows(parquet_path)
            SQLiteStorage.init_db(project_name)
            SQLiteStorage._replace_table_rows(
                db_path,
                "traces",
                rows,
                [
                    "id",
                    "run_id",
                    "timestamp",
                    "run_name",
                    "step",
                    "key",
                    "trace_index",
                    "messages",
                    "metadata",
                    "search_text",
                    "log_id",
                    "space_id",
                ],
            )

        for pq_name in all_paths:
            sidecar = _artifact_sidecar(pq_name)
            if sidecar is None:
                continue
            project_name, table = sidecar
            columns = SQLiteStorage._ARTIFACT_PARQUET_TABLES[table]
            parquet_path = TRACKIO_DIR / pq_name
            db_path = TRACKIO_DIR / f"{project_name}{DB_EXT}"
            rows = SQLiteStorage._read_parquet_rows(parquet_path)
            SQLiteStorage.init_db(project_name)
            SQLiteStorage._replace_table_rows(db_path, table, rows, columns)

    @staticmethod
    def get_scheduler():
        """
        Get the scheduler for the database based on the environment variables.
        This applies to both local and Spaces.
        """
        with SQLiteStorage._scheduler_lock:
            if SQLiteStorage._current_scheduler is not None:
                return SQLiteStorage._current_scheduler
            hf_token = os.environ.get("HF_TOKEN")
            dataset_id = os.environ.get("TRACKIO_DATASET_ID")
            space_repo_name = os.environ.get("SPACE_REPO_NAME")
            if dataset_id is not None and space_repo_name is not None:
                scheduler = CommitScheduler(
                    repo_id=dataset_id,
                    repo_type="dataset",
                    folder_path=TRACKIO_DIR,
                    private=True,
                    allow_patterns=[
                        "*.parquet",
                        "*_system.parquet",
                        "*_configs.parquet",
                        "*_traces.parquet",
                        "aux/*.parquet",
                        "media/**/*",
                        "artifacts/**/*",
                    ],
                    squash_history=True,
                    token=hf_token,
                    on_before_commit=SQLiteStorage.export_to_parquet,
                )
            else:
                scheduler = DummyCommitScheduler()
            SQLiteStorage._current_scheduler = scheduler
            return scheduler

    @staticmethod
    def log(
        project: str,
        run: str,
        metrics: dict,
        step: int | None = None,
        run_id: str | None = None,
    ):
        """
        Safely log metrics to the database. Before logging, this method will ensure the database exists
        and is set up with the correct tables. It also uses a cross-process lock to prevent
        database locking errors when multiple processes access the same database.

        This method is not used in the latest versions of Trackio (replaced by bulk_log) but
        is kept for backwards compatibility for users who are connecting to a newer version of
        a Trackio Spaces dashboard with an older version of Trackio installed locally.
        """
        db_path = SQLiteStorage.init_db(project)
        with SQLiteStorage._get_process_lock(project):
            with SQLiteStorage._get_connection(db_path) as conn:
                cursor = conn.cursor()
                supports_run_ids = SQLiteStorage._supports_run_ids(conn)
                resolved_run_id = run_id or run
                run_col = "run_id" if supports_run_ids else "run_name"
                cursor.execute(
                    f"""
                    SELECT MAX(step) 
                    FROM metrics 
                    WHERE {run_col} = ?
                    """,
                    (resolved_run_id if supports_run_ids else run,),
                )
                last_step = cursor.fetchone()[0]
                current_step = (
                    0
                    if step is None and last_step is None
                    else (step if step is not None else last_step + 1)
                )
                current_timestamp = datetime.now(timezone.utc).isoformat()
                clean_metrics, trace_rows = SQLiteStorage._split_trace_metrics(
                    metrics,
                    run=run,
                    run_id=resolved_run_id,
                    step=current_step,
                    timestamp=current_timestamp,
                    log_id=None,
                    space_id=None,
                )
                if supports_run_ids:
                    cursor.execute(
                        """
                        INSERT INTO metrics
                        (timestamp, run_id, run_name, step, metrics)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            current_timestamp,
                            resolved_run_id,
                            run,
                            current_step,
                            orjson.dumps(serialize_values(clean_metrics)),
                        ),
                    )
                else:
                    cursor.execute(
                        """
                        INSERT INTO metrics
                        (timestamp, run_name, step, metrics)
                        VALUES (?, ?, ?, ?)
                        """,
                        (
                            current_timestamp,
                            run,
                            current_step,
                            orjson.dumps(serialize_values(clean_metrics)),
                        ),
                    )
                SQLiteStorage._insert_trace_rows(cursor, trace_rows)
                conn.commit()

    @staticmethod
    def bulk_log(
        project: str,
        run: str,
        metrics_list: list[dict],
        steps: list[int] | None = None,
        timestamps: list[str] | None = None,
        config: dict | None = None,
        log_ids: list[str] | None = None,
        space_id: str | None = None,
        run_id: str | None = None,
    ):
        """
        Safely log bulk metrics to the database. Before logging, this method will ensure the database exists
        and is set up with the correct tables. It also uses a cross-process lock to prevent
        database locking errors when multiple processes access the same database.
        """
        if not metrics_list:
            return

        if timestamps is None:
            timestamps = [datetime.now(timezone.utc).isoformat()] * len(metrics_list)

        db_path = SQLiteStorage.init_db(project)
        with SQLiteStorage._get_process_lock(project):
            with SQLiteStorage._get_connection(db_path) as conn:
                cursor = conn.cursor()
                supports_run_ids = SQLiteStorage._supports_run_ids(conn)
                resolved_run_id = run_id or run

                if steps is None:
                    steps = list(range(len(metrics_list)))
                elif any(s is None for s in steps):
                    run_col = "run_id" if supports_run_ids else "run_name"
                    cursor.execute(
                        f"SELECT MAX(step) FROM metrics WHERE {run_col} = ?",
                        (resolved_run_id if supports_run_ids else run,),
                    )
                    last_step = cursor.fetchone()[0]
                    current_step = 0 if last_step is None else last_step + 1
                    processed_steps = []
                    for step in steps:
                        if step is None:
                            processed_steps.append(current_step)
                            current_step += 1
                        else:
                            processed_steps.append(step)
                    steps = processed_steps

                if len(metrics_list) != len(steps) or len(metrics_list) != len(
                    timestamps
                ):
                    raise ValueError(
                        "metrics_list, steps, and timestamps must have the same length"
                    )

                data = []
                trace_rows = []
                for i, metrics in enumerate(metrics_list):
                    lid = log_ids[i] if log_ids else None
                    clean_metrics, rows = SQLiteStorage._split_trace_metrics(
                        metrics,
                        run=run,
                        run_id=resolved_run_id,
                        step=steps[i],
                        timestamp=timestamps[i],
                        log_id=lid,
                        space_id=space_id,
                    )
                    trace_rows.extend(rows)
                    if supports_run_ids:
                        data.append(
                            (
                                timestamps[i],
                                resolved_run_id,
                                run,
                                steps[i],
                                orjson.dumps(serialize_values(clean_metrics)),
                                lid,
                                space_id,
                            )
                        )
                    else:
                        data.append(
                            (
                                timestamps[i],
                                run,
                                steps[i],
                                orjson.dumps(serialize_values(clean_metrics)),
                                lid,
                                space_id,
                            )
                        )

                if supports_run_ids:
                    cursor.executemany(
                        """
                        INSERT OR IGNORE INTO metrics
                        (timestamp, run_id, run_name, step, metrics, log_id, space_id)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        data,
                    )
                else:
                    cursor.executemany(
                        """
                        INSERT OR IGNORE INTO metrics
                        (timestamp, run_name, step, metrics, log_id, space_id)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        data,
                    )

                SQLiteStorage._insert_trace_rows(cursor, trace_rows)

                if config:
                    current_timestamp = datetime.now(timezone.utc).isoformat()
                    if "run_id" in SQLiteStorage._table_columns(conn, "configs"):
                        cursor.execute(
                            """
                            INSERT OR REPLACE INTO configs
                            (run_id, run_name, config, created_at)
                            VALUES (?, ?, ?, ?)
                            """,
                            (
                                resolved_run_id,
                                run,
                                orjson.dumps(serialize_values(config)),
                                current_timestamp,
                            ),
                        )
                    else:
                        cursor.execute(
                            """
                            INSERT OR REPLACE INTO configs
                            (run_name, config, created_at)
                            VALUES (?, ?, ?)
                            """,
                            (
                                run,
                                orjson.dumps(serialize_values(config)),
                                current_timestamp,
                            ),
                        )

                conn.commit()

    @staticmethod
    def bulk_log_system(
        project: str,
        run: str,
        metrics_list: list[dict],
        timestamps: list[str] | None = None,
        log_ids: list[str] | None = None,
        space_id: str | None = None,
        run_id: str | None = None,
    ):
        """
        Log system metrics (GPU, etc.) to the database without step numbers.
        These metrics use timestamps for the x-axis instead of steps.
        """
        if not metrics_list:
            return

        if timestamps is None:
            timestamps = [datetime.now(timezone.utc).isoformat()] * len(metrics_list)

        if len(metrics_list) != len(timestamps):
            raise ValueError("metrics_list and timestamps must have the same length")

        db_path = SQLiteStorage.init_db(project)
        with SQLiteStorage._get_process_lock(project):
            with SQLiteStorage._get_connection(db_path) as conn:
                cursor = conn.cursor()
                supports_run_ids = SQLiteStorage._supports_run_ids(
                    conn, "system_metrics"
                )
                resolved_run_id = run_id or run
                data = []
                for i, metrics in enumerate(metrics_list):
                    lid = log_ids[i] if log_ids else None
                    if supports_run_ids:
                        data.append(
                            (
                                timestamps[i],
                                resolved_run_id,
                                run,
                                orjson.dumps(serialize_values(metrics)),
                                lid,
                                space_id,
                            )
                        )
                    else:
                        data.append(
                            (
                                timestamps[i],
                                run,
                                orjson.dumps(serialize_values(metrics)),
                                lid,
                                space_id,
                            )
                        )

                if supports_run_ids:
                    cursor.executemany(
                        """
                        INSERT OR IGNORE INTO system_metrics
                        (timestamp, run_id, run_name, metrics, log_id, space_id)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        data,
                    )
                else:
                    cursor.executemany(
                        """
                        INSERT OR IGNORE INTO system_metrics
                        (timestamp, run_name, metrics, log_id, space_id)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        data,
                    )
                conn.commit()

    @staticmethod
    def bulk_alert(
        project: str,
        run: str,
        titles: list[str],
        texts: list[str | None],
        levels: list[str],
        steps: list[int | None],
        timestamps: list[str] | None = None,
        alert_ids: list[str] | None = None,
        run_id: str | None = None,
    ):
        if not titles:
            return

        if timestamps is None:
            timestamps = [datetime.now(timezone.utc).isoformat()] * len(titles)

        db_path = SQLiteStorage.init_db(project)
        with SQLiteStorage._get_process_lock(project):
            with SQLiteStorage._get_connection(db_path) as conn:
                cursor = conn.cursor()
                supports_run_ids = SQLiteStorage._supports_run_ids(conn, "alerts")
                resolved_run_id = run_id or run
                data = []
                for i in range(len(titles)):
                    aid = alert_ids[i] if alert_ids else None
                    if supports_run_ids:
                        data.append(
                            (
                                resolved_run_id,
                                timestamps[i],
                                run,
                                titles[i],
                                texts[i],
                                levels[i],
                                steps[i],
                                aid,
                            )
                        )
                    else:
                        data.append(
                            (
                                timestamps[i],
                                run,
                                titles[i],
                                texts[i],
                                levels[i],
                                steps[i],
                                aid,
                            )
                        )

                if supports_run_ids:
                    cursor.executemany(
                        """
                        INSERT OR IGNORE INTO alerts
                        (run_id, timestamp, run_name, title, text, level, step, alert_id)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        data,
                    )
                else:
                    cursor.executemany(
                        """
                        INSERT OR IGNORE INTO alerts
                        (timestamp, run_name, title, text, level, step, alert_id)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        data,
                    )
                conn.commit()

    @staticmethod
    def get_alerts(
        project: str,
        run_name: str | None = None,
        run_id: str | None = None,
        level: str | None = None,
        since: str | None = None,
    ) -> list[dict]:
        db_path = SQLiteStorage.get_project_db_path(project)
        if not db_path.exists():
            return []

        with SQLiteStorage._get_connection(db_path) as conn:
            cursor = conn.cursor()
            try:
                query = (
                    "SELECT timestamp, run_name, title, text, level, step FROM alerts"
                )
                conditions = []
                params = []
                run_identity = SQLiteStorage._resolve_run_identity(
                    conn, run_name=run_name, run_id=run_id, table="alerts"
                )
                if run_identity is not None:
                    conditions.append(f"{run_identity[0]} = ?")
                    params.append(run_identity[1])
                elif run_name is not None or run_id is not None:
                    return []
                if level is not None:
                    conditions.append("level = ?")
                    params.append(level)
                if since is not None:
                    conditions.append("timestamp > ?")
                    params.append(since)
                if conditions:
                    query += " WHERE " + " AND ".join(conditions)
                query += " ORDER BY timestamp DESC"
                cursor.execute(query, params)

                rows = cursor.fetchall()
                return [
                    {
                        "timestamp": row["timestamp"],
                        "run": row["run_name"],
                        "title": row["title"],
                        "text": row["text"],
                        "level": row["level"],
                        "step": row["step"],
                    }
                    for row in rows
                ]
            except sqlite3.OperationalError as e:
                if "no such table: alerts" in str(e):
                    return []
                raise

    @staticmethod
    def get_alert_count(project: str) -> int:
        db_path = SQLiteStorage.get_project_db_path(project)
        if not db_path.exists():
            return 0

        with SQLiteStorage._get_connection(db_path) as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("SELECT COUNT(*) FROM alerts")
                return cursor.fetchone()[0]
            except sqlite3.OperationalError:
                return 0

    @staticmethod
    def _fetch_system_logs_with_cursor(
        cursor: sqlite3.Cursor,
        run_identity: tuple[str, Any],
        max_points: int | None = None,
    ) -> list[dict[str, Any]]:
        cursor.execute(
            f"""
            SELECT timestamp, metrics
            FROM system_metrics
            WHERE {run_identity[0]} = ?
            ORDER BY timestamp
            """,
            (run_identity[1],),
        )
        rows = cursor.fetchall()
        rows = SQLiteStorage._subsample_metric_rows(rows, max_points)
        results = []
        for row in rows:
            metrics = orjson.loads(row["metrics"])
            metrics = deserialize_values(metrics)
            metrics["timestamp"] = row["timestamp"]
            results.append(metrics)
        return results

    @staticmethod
    def get_system_logs(
        project: str,
        run: str | None = None,
        run_id: str | None = None,
        max_points: int | None = None,
    ) -> list[dict]:
        """Retrieve system metrics for a specific run. Returns metrics with timestamps (no steps)."""
        db_path = SQLiteStorage.get_project_db_path(project)
        if not db_path.exists():
            return []

        cache_key = _system_logs_read_cache_key(project, run, run_id, max_points)
        cached = _system_logs_read_cache_get(db_path, cache_key)
        if cached is not None:
            return cached

        try:
            with SQLiteStorage._get_connection(db_path) as conn:
                cursor = conn.cursor()
                run_identity = SQLiteStorage._resolve_run_identity(
                    conn, run_name=run, run_id=run_id, table="system_metrics"
                )
                if run_identity is None:
                    logs: list[dict[str, Any]] = []
                else:
                    logs = SQLiteStorage._fetch_system_logs_with_cursor(
                        cursor, run_identity, max_points
                    )
        except sqlite3.OperationalError as e:
            if "no such table: system_metrics" in str(e):
                return []
            raise

        _system_logs_read_cache_put(db_path, cache_key, logs)
        return [{**d} for d in logs]

    @staticmethod
    def get_system_logs_batch(
        project: str,
        runs: list[dict[str, Any]] | None = None,
        max_points: int | None = None,
    ) -> list[dict[str, Any]]:
        if not runs:
            return []
        db_path = SQLiteStorage.get_project_db_path(project)
        if not db_path.exists():
            return [
                {
                    "run": r.get("run"),
                    "run_id": r.get("run_id"),
                    "logs": [],
                }
                for r in runs
            ]

        out: list[dict[str, Any]] = []
        try:
            with SQLiteStorage._get_connection(db_path) as conn:
                cursor = conn.cursor()
                for r in runs:
                    run = r.get("run")
                    run_id = r.get("run_id")
                    cache_key = _system_logs_read_cache_key(
                        project, run, run_id, max_points
                    )
                    cached = _system_logs_read_cache_get(db_path, cache_key)
                    if cached is not None:
                        out.append(
                            {
                                "run": run,
                                "run_id": run_id,
                                "logs": cached,
                            }
                        )
                        continue
                    run_identity = SQLiteStorage._resolve_run_identity(
                        conn, run_name=run, run_id=run_id, table="system_metrics"
                    )
                    if run_identity is None:
                        logs = []
                    else:
                        logs = SQLiteStorage._fetch_system_logs_with_cursor(
                            cursor, run_identity, max_points
                        )
                    _system_logs_read_cache_put(db_path, cache_key, logs)
                    out.append(
                        {
                            "run": run,
                            "run_id": run_id,
                            "logs": [{**d} for d in logs],
                        }
                    )
        except sqlite3.OperationalError as e:
            if "no such table: system_metrics" in str(e):
                return [
                    {
                        "run": r.get("run"),
                        "run_id": r.get("run_id"),
                        "logs": [],
                    }
                    for r in runs
                ]
            raise

        return out

    @staticmethod
    def get_all_system_metrics_for_run(
        project: str, run: str | None = None, run_id: str | None = None
    ) -> list[str]:
        """Get all system metric names for a specific project/run."""
        return SQLiteStorage._get_metric_names(
            project,
            run,
            "system_metrics",
            exclude_keys={"timestamp"},
            run_id=run_id,
        )

    @staticmethod
    def has_system_metrics(project: str) -> bool:
        """Check if a project has any system metrics logged."""
        db_path = SQLiteStorage.get_project_db_path(project)
        if not db_path.exists():
            return False

        with SQLiteStorage._get_connection(db_path) as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("SELECT COUNT(*) FROM system_metrics LIMIT 1")
                count = cursor.fetchone()[0]
                return count > 0
            except sqlite3.OperationalError:
                return False

    @staticmethod
    def get_log_count(
        project: str, run: str | None = None, run_id: str | None = None
    ) -> int:
        SQLiteStorage._ensure_hub_loaded()
        db_path = SQLiteStorage.get_project_db_path(project)
        if not db_path.exists():
            return 0
        try:
            with SQLiteStorage._get_connection(db_path) as conn:
                cursor = conn.cursor()
                run_identity = SQLiteStorage._resolve_run_identity(
                    conn, run_name=run, run_id=run_id
                )
                if run_identity is None:
                    return 0
                cursor.execute(
                    f"SELECT COUNT(*) FROM metrics WHERE {run_identity[0]} = ?",
                    (run_identity[1],),
                )
                return cursor.fetchone()[0]
        except sqlite3.OperationalError as e:
            if "no such table: metrics" in str(e):
                return 0
            raise

    @staticmethod
    def get_last_step(
        project: str, run: str | None = None, run_id: str | None = None
    ) -> int | None:
        db_path = SQLiteStorage.get_project_db_path(project)
        if not db_path.exists():
            return None
        try:
            with SQLiteStorage._get_connection(db_path) as conn:
                cursor = conn.cursor()
                run_identity = SQLiteStorage._resolve_run_identity(
                    conn, run_name=run, run_id=run_id
                )
                if run_identity is None:
                    return None
                cursor.execute(
                    f"SELECT MAX(step) FROM metrics WHERE {run_identity[0]} = ?",
                    (run_identity[1],),
                )
                row = cursor.fetchone()
                return row[0] if row and row[0] is not None else None
        except sqlite3.OperationalError as e:
            if "no such table: metrics" in str(e):
                return None
            raise

    @staticmethod
    def get_tab_availability_flags(project: str) -> dict[str, bool]:
        SQLiteStorage._ensure_hub_loaded()
        flags = {
            "metrics": False,
            "system": False,
            "traces": False,
            "media": False,
            "reports": False,
            "alerts": False,
        }
        db_path = SQLiteStorage.get_project_db_path(project)
        if not db_path.exists():
            return flags

        def _exists(conn, sql, params=()):
            try:
                cursor = conn.cursor()
                cursor.execute(sql, params)
                return cursor.fetchone() is not None
            except sqlite3.OperationalError:
                return False

        with SQLiteStorage._get_connection(db_path) as conn:
            flags["metrics"] = _exists(
                conn,
                "SELECT 1 FROM metrics "
                "WHERE CAST(metrics AS TEXT) GLOB '*:[0-9]*' "
                "OR CAST(metrics AS TEXT) GLOB '*:-[0-9]*' "
                "LIMIT 1",
            )
            flags["media"] = _exists(
                conn,
                "SELECT 1 FROM metrics WHERE "
                "CAST(metrics AS TEXT) GLOB ? "
                "OR CAST(metrics AS TEXT) GLOB ? "
                "OR CAST(metrics AS TEXT) GLOB ? "
                "OR CAST(metrics AS TEXT) GLOB ? "
                "LIMIT 1",
                (
                    '*"_type":"trackio.image"*',
                    '*"_type":"trackio.video"*',
                    '*"_type":"trackio.audio"*',
                    '*"_type":"trackio.table"*',
                ),
            )
            flags["reports"] = _exists(
                conn,
                "SELECT 1 FROM metrics WHERE CAST(metrics AS TEXT) GLOB ? LIMIT 1",
                ('*"_type":"trackio.markdown"*',),
            )
            flags["system"] = _exists(conn, "SELECT 1 FROM system_metrics LIMIT 1")
            flags["traces"] = _exists(conn, "SELECT 1 FROM traces LIMIT 1")
            flags["alerts"] = _exists(conn, "SELECT 1 FROM alerts LIMIT 1")
        return flags

    @staticmethod
    def _subsample_metric_rows(rows: list[Any], max_points: int | None) -> list[Any]:
        if max_points is None or max_points < 1:
            return rows
        if len(rows) <= max_points:
            return rows
        step = len(rows) / max_points
        indices = {int(i * step) for i in range(max_points)}
        indices.add(len(rows) - 1)
        return [rows[i] for i in sorted(indices)]

    @staticmethod
    def _metric_rows_to_log_dicts(rows: list[Any]) -> list[dict[str, Any]]:
        results = []
        for row in rows:
            metrics = orjson.loads(row["metrics"])
            metrics = deserialize_values(metrics)
            metrics["timestamp"] = row["timestamp"]
            metrics["step"] = row["step"]
            results.append(metrics)
        return results

    @staticmethod
    def _fetch_metric_logs_with_cursor(
        cursor: sqlite3.Cursor,
        run_identity: tuple[str, Any],
        max_points: int | None,
    ) -> list[dict[str, Any]]:
        cursor.execute(
            f"""
            SELECT timestamp, step, metrics
            FROM metrics
            WHERE {run_identity[0]} = ?
            ORDER BY timestamp
            """,
            (run_identity[1],),
        )
        rows = cursor.fetchall()
        rows = SQLiteStorage._subsample_metric_rows(rows, max_points)
        return SQLiteStorage._metric_rows_to_log_dicts(rows)

    @staticmethod
    def get_logs(
        project: str,
        run: str | None = None,
        max_points: int | None = None,
        run_id: str | None = None,
    ) -> list[dict]:
        """Retrieve logs for a specific run. Logs include the step count (int) and the timestamp (datetime object)."""
        db_path = SQLiteStorage.get_project_db_path(project)
        if not db_path.exists():
            return []

        cache_key = _logs_read_cache_key(project, run, run_id, max_points)
        cached = _logs_read_cache_get(db_path, cache_key)
        if cached is not None:
            return cached

        try:
            with SQLiteStorage._get_connection(db_path) as conn:
                cursor = conn.cursor()
                run_identity = SQLiteStorage._resolve_run_identity(
                    conn, run_name=run, run_id=run_id
                )
                if run_identity is None:
                    logs: list[dict[str, Any]] = []
                else:
                    logs = SQLiteStorage._fetch_metric_logs_with_cursor(
                        cursor, run_identity, max_points
                    )
        except sqlite3.OperationalError as e:
            if "no such table: metrics" in str(e):
                return []
            raise

        _logs_read_cache_put(db_path, cache_key, logs)
        return [{**d} for d in logs]

    @staticmethod
    def get_logs_batch(
        project: str,
        runs: list[dict[str, Any]] | None = None,
        max_points: int | None = None,
    ) -> list[dict[str, Any]]:
        if not runs:
            return []
        db_path = SQLiteStorage.get_project_db_path(project)
        if not db_path.exists():
            return [
                {
                    "run": r.get("run"),
                    "run_id": r.get("run_id"),
                    "logs": [],
                }
                for r in runs
            ]

        out: list[dict[str, Any]] = []
        try:
            with SQLiteStorage._get_connection(db_path) as conn:
                cursor = conn.cursor()
                for r in runs:
                    run = r.get("run")
                    run_id = r.get("run_id")
                    cache_key = _logs_read_cache_key(project, run, run_id, max_points)
                    cached = _logs_read_cache_get(db_path, cache_key)
                    if cached is not None:
                        out.append(
                            {
                                "run": run,
                                "run_id": run_id,
                                "logs": cached,
                            }
                        )
                        continue
                    run_identity = SQLiteStorage._resolve_run_identity(
                        conn, run_name=run, run_id=run_id
                    )
                    if run_identity is None:
                        logs = []
                    else:
                        logs = SQLiteStorage._fetch_metric_logs_with_cursor(
                            cursor, run_identity, max_points
                        )
                    _logs_read_cache_put(db_path, cache_key, logs)
                    out.append(
                        {
                            "run": run,
                            "run_id": run_id,
                            "logs": [{**d} for d in logs],
                        }
                    )
        except sqlite3.OperationalError as e:
            if "no such table: metrics" in str(e):
                return [
                    {
                        "run": r.get("run"),
                        "run_id": r.get("run_id"),
                        "logs": [],
                    }
                    for r in runs
                ]
            raise

        return out

    @staticmethod
    def _is_trace_payload(value: Any) -> bool:
        return isinstance(value, dict) and value.get("_type") == "trackio.trace"

    @staticmethod
    def _split_trace_metrics(
        metrics: dict,
        *,
        run: str,
        run_id: str,
        step: int,
        timestamp: str,
        log_id: str | None,
        space_id: str | None,
    ) -> tuple[dict, list[dict[str, Any]]]:
        clean_metrics = {}
        trace_rows: list[dict[str, Any]] = []

        for key, value in metrics.items():
            is_list = isinstance(value, list)
            candidates = value if is_list else [value]
            traces_for_key = [
                (index if is_list else None, candidate)
                for index, candidate in enumerate(candidates)
                if SQLiteStorage._is_trace_payload(candidate)
            ]
            if not traces_for_key:
                clean_metrics[key] = value
                continue

            if is_list:
                non_trace_items = [
                    candidate
                    for candidate in candidates
                    if not SQLiteStorage._is_trace_payload(candidate)
                ]
                if non_trace_items:
                    clean_metrics[key] = non_trace_items

            for trace_index, trace in traces_for_key:
                trace_id_parts = [run_id or run, log_id or uuid.uuid4().hex, key]
                if trace_index is not None:
                    trace_id_parts.append(str(trace_index))
                trace_record = {
                    "id": ":".join(str(part) for part in trace_id_parts),
                    "run_id": run_id,
                    "timestamp": timestamp,
                    "run_name": run,
                    "step": step,
                    "key": key,
                    "trace_index": trace_index,
                    "messages": trace.get("messages", []),
                    "metadata": trace.get("metadata", {}),
                    "log_id": log_id,
                    "space_id": space_id,
                }
                trace_record["search_text"] = (
                    f"{trace_record['id']} {key} "
                    f"{SQLiteStorage._flatten_trace_search_text(trace_record)}"
                ).lower()
                trace_rows.append(trace_record)

        return clean_metrics, trace_rows

    @staticmethod
    def _insert_trace_rows(cursor: sqlite3.Cursor, trace_rows: list[dict[str, Any]]):
        if not trace_rows:
            return
        cursor.executemany(
            """
            INSERT OR IGNORE INTO traces
            (id, run_id, timestamp, run_name, step, key, trace_index, messages, metadata, search_text, log_id, space_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    row["id"],
                    row["run_id"],
                    row["timestamp"],
                    row["run_name"],
                    row["step"],
                    row["key"],
                    row["trace_index"],
                    orjson.dumps(serialize_values(row["messages"])),
                    orjson.dumps(serialize_values(row["metadata"])),
                    row["search_text"],
                    row["log_id"],
                    row["space_id"],
                )
                for row in trace_rows
            ],
        )

    @staticmethod
    def _flatten_trace_search_text(trace: dict[str, Any]) -> str:
        parts: list[str] = []

        def visit(value: Any):
            if value is None:
                return
            if isinstance(value, dict):
                for nested in value.values():
                    visit(nested)
                return
            if isinstance(value, list):
                for nested in value:
                    visit(nested)
                return
            parts.append(str(value))

        visit(trace.get("messages", []))
        visit(trace.get("metadata", {}))
        return " ".join(parts).lower()

    @staticmethod
    def _extract_traces_from_logs(
        logs: list[dict[str, Any]],
        run: str | None,
        run_id: str | None,
    ) -> list[dict[str, Any]]:
        traces: list[dict[str, Any]] = []

        for log in logs:
            step = log.get("step")
            timestamp = log.get("timestamp")
            for key, value in log.items():
                if key in {"step", "timestamp"}:
                    continue

                candidates = value if isinstance(value, list) else [value]
                for index, candidate in enumerate(candidates):
                    if (
                        not isinstance(candidate, dict)
                        or candidate.get("_type") != "trackio.trace"
                    ):
                        continue

                    trace_index = index if isinstance(value, list) else None
                    trace_id_parts = [run_id or run or "run", str(step), key]
                    if trace_index is not None:
                        trace_id_parts.append(str(trace_index))

                    trace_record = {
                        "id": ":".join(trace_id_parts),
                        "key": key,
                        "index": trace_index,
                        "run": run,
                        "run_id": run_id,
                        "step": step,
                        "timestamp": timestamp,
                        "messages": candidate.get("messages", []),
                        "metadata": candidate.get("metadata", {}),
                    }
                    trace_record["_search_text"] = (
                        f"{trace_record['id']} {key} "
                        f"{SQLiteStorage._flatten_trace_search_text(trace_record)}"
                    ).lower()
                    traces.append(trace_record)

        return traces

    @staticmethod
    def _sort_traces(
        traces: list[dict[str, Any]], sort: str | None
    ) -> list[dict[str, Any]]:
        sort_key = sort or "request_time_desc"
        if sort_key == "step_asc":
            return sorted(traces, key=lambda trace: trace.get("step") or 0)
        if sort_key == "step_desc":
            return sorted(
                traces, key=lambda trace: trace.get("step") or 0, reverse=True
            )
        if sort_key == "request_time_asc":
            return sorted(traces, key=lambda trace: trace.get("timestamp") or "")
        return sorted(
            traces, key=lambda trace: trace.get("timestamp") or "", reverse=True
        )

    @staticmethod
    def get_traces(
        project: str,
        run: str | None = None,
        search: str | None = None,
        sort: str | None = None,
        limit: int | None = None,
        offset: int = 0,
        run_id: str | None = None,
        step: int | None = None,
    ) -> list[dict[str, Any]]:
        try:
            offset = max(0, int(offset or 0))
        except (TypeError, ValueError):
            offset = 0
        if limit is not None:
            try:
                limit = max(0, int(limit))
            except (TypeError, ValueError):
                limit = None

        db_path = SQLiteStorage.get_project_db_path(project)
        if not db_path.exists():
            return []

        order_by = {
            "step_asc": "step ASC, timestamp ASC, id ASC",
            "step_desc": "step DESC, timestamp DESC, id DESC",
            "request_time_asc": "timestamp ASC, id ASC",
            "request_time_desc": "timestamp DESC, id DESC",
        }.get(sort or "request_time_desc", "timestamp DESC, id DESC")

        try:
            with SQLiteStorage._get_connection(db_path) as conn:
                run_identity = SQLiteStorage._resolve_run_identity(
                    conn, run_name=run, run_id=run_id, table="traces"
                )
                if run_identity is None:
                    return []

                where = [f"{run_identity[0]} = ?"]
                params: list[Any] = [run_identity[1]]
                if step is not None:
                    where.append("step = ?")
                    params.append(step)
                if search:
                    needle = search.strip().lower()
                    if needle:
                        where.append("search_text LIKE ?")
                        params.append(f"%{needle}%")

                query = f"""
                    SELECT id, key, trace_index, run_name, run_id, step, timestamp, messages, metadata
                    FROM traces
                    WHERE {" AND ".join(where)}
                    ORDER BY {order_by}
                """
                if limit is not None:
                    query += " LIMIT ?"
                    params.append(limit)
                if offset > 0:
                    if limit is None:
                        query += " LIMIT -1"
                    query += " OFFSET ?"
                    params.append(offset)

                cursor = conn.cursor()
                cursor.execute(query, params)
                rows = cursor.fetchall()
        except sqlite3.OperationalError as e:
            if "no such table: traces" in str(e):
                return []
            raise

        return [
            {
                "id": row["id"],
                "key": row["key"],
                "index": row["trace_index"],
                "run": row["run_name"],
                "run_id": row["run_id"],
                "step": row["step"],
                "timestamp": row["timestamp"],
                "messages": deserialize_values(orjson.loads(row["messages"])),
                "metadata": deserialize_values(orjson.loads(row["metadata"])),
            }
            for row in rows
        ]

    @staticmethod
    def get_trace_steps(
        project: str,
        run: str | None = None,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        """Return per-step trace counts and total for a run.

        Returns: {"total": int, "steps": [{"step": int, "count": int}, ...]}
        Steps are returned in ascending order.
        """
        db_path = SQLiteStorage.get_project_db_path(project)
        if not db_path.exists():
            return {"total": 0, "steps": []}

        try:
            with SQLiteStorage._get_connection(db_path) as conn:
                run_identity = SQLiteStorage._resolve_run_identity(
                    conn, run_name=run, run_id=run_id, table="traces"
                )
                if run_identity is None:
                    return {"total": 0, "steps": []}
                cursor = conn.cursor()
                cursor.execute(
                    f"""
                    SELECT step, COUNT(*) AS c
                    FROM traces
                    WHERE {run_identity[0]} = ?
                    GROUP BY step
                    ORDER BY step ASC
                    """,
                    (run_identity[1],),
                )
                rows = cursor.fetchall()
        except sqlite3.OperationalError as e:
            if "no such table: traces" in str(e):
                return {"total": 0, "steps": []}
            raise

        steps = [{"step": row["step"], "count": row["c"]} for row in rows]
        total = sum(item["count"] for item in steps)
        return {"total": total, "steps": steps}

    @staticmethod
    def load_from_dataset():
        """Hydrate the local trackio dir from the configured remote.

        Wrapped in a per-thread reentrancy guard (`_dataset_loading.active`)
        because the import path re-enters via `import_from_parquet` ->
        `init_db` -> `_ensure_hub_loaded`, and the scheduler lock held during
        import is not reentrant.
        """
        if getattr(SQLiteStorage._dataset_loading, "active", False):
            return
        SQLiteStorage._dataset_loading.active = True
        try:
            SQLiteStorage._load_from_dataset_impl()
        finally:
            SQLiteStorage._dataset_loading.active = False

    @staticmethod
    def _load_from_dataset_impl():
        """Download the remote files, then import them, at most once each.

        Three class flags coordinate this across calls:
        - `_dataset_remote_synced`: the remote listing + download has run; kept
          across calls so a retry never re-hits the Hub.
        - `_dataset_import_pending`: files were downloaded but not yet imported
          into SQLite; stays True until `import_from_parquet` succeeds, so a
          transient import failure is retried on the next access.
        - `_dataset_import_attempted`: the load has run to completion (or been
          short-circuited); gates `_ensure_hub_loaded` and `export_to_parquet`.
        """
        bucket_id = os.environ.get("TRACKIO_BUCKET_ID")
        if bucket_id is not None:
            if not SQLiteStorage._dataset_import_attempted:
                SQLiteStorage._dataset_import_attempted = True
                from trackio import fragments
                from trackio.bucket_storage import download_bucket_to_trackio_dir

                try:
                    download_bucket_to_trackio_dir(bucket_id)
                except Exception:
                    pass
                try:
                    fragments.import_inbox_from_bucket(bucket_id)
                except Exception:
                    pass
                try:
                    fragments.import_inbox_dir()
                except Exception:
                    pass
            return
        dataset_id = os.environ.get("TRACKIO_DATASET_ID")
        space_repo_name = os.environ.get("SPACE_REPO_NAME")
        if dataset_id is not None and space_repo_name is not None:
            hfapi = hf.HfApi()
            if not TRACKIO_DIR.exists():
                TRACKIO_DIR.mkdir(parents=True, exist_ok=True)
            with SQLiteStorage.get_scheduler().lock:
                if not SQLiteStorage._dataset_remote_synced:
                    try:
                        files = hfapi.list_repo_files(dataset_id, repo_type="dataset")
                        for file in files:
                            if not (
                                file.endswith(".parquet")
                                or file.startswith("media/")
                                or file.startswith("artifacts/")
                            ):
                                continue
                            if (TRACKIO_DIR / file).exists():
                                continue
                            hf.hf_hub_download(
                                dataset_id,
                                file,
                                repo_type="dataset",
                                local_dir=TRACKIO_DIR,
                            )
                            SQLiteStorage._dataset_import_pending = True
                    except hf.errors.EntryNotFoundError:
                        pass
                    except hf.errors.RepositoryNotFoundError:
                        pass
                    SQLiteStorage._dataset_remote_synced = True
                if SQLiteStorage._dataset_import_pending:
                    try:
                        SQLiteStorage.import_from_parquet()
                        SQLiteStorage._dataset_import_pending = False
                    except Exception as e:
                        _emit_nonfatal_warning(
                            f"trackio could not import downloaded dataset files; "
                            f"will retry on the next access: {e}"
                        )
                        return
        SQLiteStorage._dataset_import_attempted = True

    @staticmethod
    def _ensure_hub_loaded():
        if not SQLiteStorage._dataset_import_attempted:
            SQLiteStorage.load_from_dataset()

    @staticmethod
    def get_projects() -> list[str]:
        """
        Get list of all projects by scanning the database files in the trackio directory.
        """
        SQLiteStorage._ensure_hub_loaded()

        projects: set[str] = set()
        if not TRACKIO_DIR.exists():
            return []

        for db_file in TRACKIO_DIR.glob(f"*{DB_EXT}"):
            project_name = db_file.stem
            projects.add(project_name)
        return sorted(projects)

    @staticmethod
    def get_runs(project: str) -> list[str]:
        """Get list of all runs for a project, ordered by creation time."""
        return [record["name"] for record in SQLiteStorage.get_run_records(project)]

    @staticmethod
    def _validate_read_only_query(query: str) -> str:
        normalized = query.strip().rstrip(";").strip()
        if not normalized:
            raise ValueError("Query cannot be empty.")
        if not normalized.lower().startswith(_READ_ONLY_QUERY_PREFIXES):
            raise ValueError(
                "Only read-only SELECT, WITH, and safe PRAGMA queries are supported."
            )
        return normalized

    @staticmethod
    def _query_authorizer(
        action_code: int,
        arg1: str | None,
        arg2: str | None,
        db_name: str | None,
        source: str | None,
    ) -> int:
        del arg2, db_name, source
        if action_code in {
            sqlite3.SQLITE_SELECT,
            sqlite3.SQLITE_READ,
            sqlite3.SQLITE_FUNCTION,
        }:
            return sqlite3.SQLITE_OK
        pragma_code = getattr(sqlite3, "SQLITE_PRAGMA", None)
        if action_code == pragma_code:
            pragma_name = (arg1 or "").lower()
            if pragma_name in _READ_ONLY_PRAGMAS:
                return sqlite3.SQLITE_OK
        return sqlite3.SQLITE_DENY

    @staticmethod
    def _normalize_query_value(value: Any) -> Any:
        if isinstance(value, (bytes, bytearray, memoryview)):
            return bytes(value).hex()
        return value

    @staticmethod
    def query_project(
        project: str, query: str, max_rows: int = _QUERY_MAX_ROWS
    ) -> dict[str, Any]:
        SQLiteStorage._ensure_hub_loaded()
        db_path = SQLiteStorage.get_project_db_path(project)
        if not db_path.exists():
            raise FileNotFoundError(f"Project '{project}' not found.")

        normalized_query = SQLiteStorage._validate_read_only_query(query)
        with SQLiteStorage._get_connection(db_path) as conn:
            conn.set_authorizer(SQLiteStorage._query_authorizer)
            try:
                cursor = conn.cursor()
                cursor.execute(normalized_query)
                description = cursor.description or []
                columns = [column[0] for column in description]
                fetched = cursor.fetchmany(max_rows + 1)
                if len(fetched) > max_rows:
                    raise ValueError(
                        f"Query returned more than {max_rows} rows. "
                        "Refine the query or add a LIMIT clause."
                    )
                rows = [
                    {
                        column: SQLiteStorage._normalize_query_value(row[column])
                        for column in columns
                    }
                    for row in fetched
                ]
            except sqlite3.DatabaseError as e:
                raise ValueError(str(e)) from e
            finally:
                conn.set_authorizer(None)

        return {
            "project": project,
            "query": normalized_query,
            "columns": columns,
            "rows": rows,
            "row_count": len(rows),
        }

    @staticmethod
    def get_max_steps_for_runs(project: str) -> dict[str, int]:
        """Get the maximum step for each run in a project."""
        db_path = SQLiteStorage.get_project_db_path(project)
        if not db_path.exists():
            return {}

        try:
            with SQLiteStorage._get_connection(db_path) as conn:
                cursor = conn.cursor()
                if SQLiteStorage._supports_run_ids(conn):
                    cursor.execute(
                        """
                        SELECT run_name, run_id, MAX(step) as max_step
                        FROM metrics
                        GROUP BY run_id, run_name
                        """
                    )
                    results = {}
                    for row in cursor.fetchall():
                        results[row["run_id"]] = row["max_step"]
                    return results

                cursor.execute(
                    """
                    SELECT run_name, MAX(step) as max_step
                    FROM metrics
                    GROUP BY run_name
                    """
                )

                results = {}
                for row in cursor.fetchall():
                    results[row["run_name"]] = row["max_step"]

                return results
        except sqlite3.OperationalError as e:
            if "no such table: metrics" in str(e):
                return {}
            raise

    @staticmethod
    def get_max_step_for_run(
        project: str, run: str | None = None, run_id: str | None = None
    ) -> int | None:
        """Get the maximum step for a specific run, or None if no logs exist."""
        db_path = SQLiteStorage.get_project_db_path(project)
        if not db_path.exists():
            return None

        try:
            with SQLiteStorage._get_connection(db_path) as conn:
                cursor = conn.cursor()
                run_identity = SQLiteStorage._resolve_run_identity(
                    conn, run_name=run, run_id=run_id
                )
                if run_identity is None:
                    return None
                cursor.execute(
                    f"SELECT MAX(step) FROM metrics WHERE {run_identity[0]} = ?",
                    (run_identity[1],),
                )
                result = cursor.fetchone()[0]
                return result
        except sqlite3.OperationalError as e:
            if "no such table: metrics" in str(e):
                return None
            raise

    @staticmethod
    def get_run_config(
        project: str, run: str | None = None, run_id: str | None = None
    ) -> dict | None:
        """Get configuration for a specific run."""
        db_path = SQLiteStorage.get_project_db_path(project)
        if not db_path.exists():
            return None

        with SQLiteStorage._get_connection(db_path) as conn:
            cursor = conn.cursor()
            try:
                run_identity = SQLiteStorage._resolve_run_identity(
                    conn, run_name=run, run_id=run_id, table="metrics"
                )
                if run_identity is None:
                    return None
                config_col = (
                    "run_id"
                    if "run_id" in SQLiteStorage._table_columns(conn, "configs")
                    else "run_name"
                )
                cursor.execute(
                    f"""
                    SELECT config FROM configs WHERE {config_col} = ?
                    """,
                    (run_identity[1],),
                )

                row = cursor.fetchone()
                if row:
                    config = orjson.loads(row["config"])
                    return deserialize_values(config)
                return None
            except sqlite3.OperationalError as e:
                if "no such table: configs" in str(e):
                    return None
                raise

    @staticmethod
    def delete_run(project: str, run: str, run_id: str | None = None) -> bool:
        """Delete a run from the database (metrics, config, and system_metrics)."""
        db_path = SQLiteStorage.get_project_db_path(project)
        if not db_path.exists():
            return False

        with SQLiteStorage._get_process_lock(project):
            with SQLiteStorage._get_connection(db_path) as conn:
                cursor = conn.cursor()
                try:
                    run_identity = SQLiteStorage._resolve_run_identity(
                        conn, run_name=run, run_id=run_id
                    )
                    if run_identity is None:
                        return False
                    cursor.execute(
                        f"DELETE FROM metrics WHERE {run_identity[0]} = ?",
                        (run_identity[1],),
                    )
                    config_identity = SQLiteStorage._resolve_run_identity(
                        conn, run_name=run, run_id=run_id, table="configs"
                    )
                    if config_identity is not None:
                        cursor.execute(
                            f"DELETE FROM configs WHERE {config_identity[0]} = ?",
                            (config_identity[1],),
                        )
                    try:
                        cursor.execute(
                            f"DELETE FROM system_metrics WHERE {run_identity[0]} = ?",
                            (run_identity[1],),
                        )
                    except sqlite3.OperationalError:
                        pass
                    try:
                        cursor.execute(
                            f"DELETE FROM alerts WHERE {run_identity[0]} = ?",
                            (run_identity[1],),
                        )
                    except sqlite3.OperationalError:
                        pass
                    try:
                        trace_identity = SQLiteStorage._resolve_run_identity(
                            conn, run_name=run, run_id=run_id, table="traces"
                        )
                        if trace_identity is not None:
                            cursor.execute(
                                f"DELETE FROM traces WHERE {trace_identity[0]} = ?",
                                (trace_identity[1],),
                            )
                    except sqlite3.OperationalError:
                        pass
                    conn.commit()
                    return True
                except sqlite3.Error:
                    return False

    @staticmethod
    def _update_media_paths(obj, old_prefix, new_prefix):
        """Update media file paths in nested data structures."""
        if isinstance(obj, dict):
            if obj.get("_type") in [
                "trackio.image",
                "trackio.video",
                "trackio.audio",
            ]:
                old_path = obj.get("file_path", "")
                if isinstance(old_path, str):
                    normalized_path = old_path.replace("\\", "/")
                    if normalized_path.startswith(old_prefix):
                        new_path = normalized_path.replace(old_prefix, new_prefix, 1)
                        return {**obj, "file_path": new_path}
            return {
                key: SQLiteStorage._update_media_paths(value, old_prefix, new_prefix)
                for key, value in obj.items()
            }
        elif isinstance(obj, list):
            return [
                SQLiteStorage._update_media_paths(item, old_prefix, new_prefix)
                for item in obj
            ]
        return obj

    @staticmethod
    def _rewrite_metrics_rows(
        metrics_rows, new_run_name, old_prefix, new_prefix, include_run_id=False
    ):
        """Deserialize metrics rows, update media paths, and reserialize."""
        result = []
        for row in metrics_rows:
            metrics_data = orjson.loads(row["metrics"])
            metrics_deserialized = deserialize_values(metrics_data)
            updated = SQLiteStorage._update_media_paths(
                metrics_deserialized, old_prefix, new_prefix
            )
            values = (
                row["timestamp"],
                new_run_name,
                row["step"],
                orjson.dumps(serialize_values(updated)),
            )
            if include_run_id:
                values = values + (row["run_id"],)
            result.append(values)
        return result

    @staticmethod
    def _rewrite_trace_rows(
        trace_rows,
        new_run_name,
        old_prefix,
        new_prefix,
        *,
        run_id: str | None = None,
    ):
        result = []
        for row in trace_rows:
            messages = deserialize_values(orjson.loads(row["messages"]))
            metadata = deserialize_values(orjson.loads(row["metadata"]))
            messages = SQLiteStorage._update_media_paths(
                messages, old_prefix, new_prefix
            )
            metadata = SQLiteStorage._update_media_paths(
                metadata, old_prefix, new_prefix
            )
            result.append(
                (
                    row["id"],
                    run_id if run_id is not None else row["run_id"],
                    row["timestamp"],
                    new_run_name,
                    row["step"],
                    row["key"],
                    row["trace_index"],
                    orjson.dumps(serialize_values(messages)),
                    orjson.dumps(serialize_values(metadata)),
                    row["search_text"],
                    row["log_id"],
                    row["space_id"],
                )
            )
        return result

    @staticmethod
    def _move_media_dir(source: Path, target: Path):
        """Move a media directory from source to target."""
        if source.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                shutil.rmtree(target)
            shutil.move(str(source), str(target))

    @staticmethod
    def rename_run(
        project: str, old_name: str, new_name: str, run_id: str | None = None
    ) -> None:
        """Rename a run within the same project.

        Raises:
            ValueError: If the new name is empty, the old run doesn't exist,
                        or a run with the new name already exists.
            RuntimeError: If the database operation fails.
        """
        if not new_name or not new_name.strip():
            raise ValueError("New run name cannot be empty")

        new_name = new_name.strip()

        db_path = SQLiteStorage.get_project_db_path(project)
        if not db_path.exists():
            raise ValueError(f"Project '{project}' does not exist")

        with SQLiteStorage._get_process_lock(project):
            with SQLiteStorage._get_connection(db_path) as conn:
                cursor = conn.cursor()
                supports_run_ids = SQLiteStorage._supports_run_ids(conn)
                run_identity = SQLiteStorage._resolve_run_identity(
                    conn, run_name=old_name, run_id=run_id
                )
                if run_identity is None:
                    raise ValueError(
                        f"Run '{old_name}' does not exist in project '{project}'"
                    )

                run_col, run_value = run_identity

                if not supports_run_ids:
                    cursor.execute(
                        "SELECT COUNT(*) FROM metrics WHERE run_name = ?", (new_name,)
                    )
                    if cursor.fetchone()[0] > 0:
                        raise ValueError(
                            f"A run named '{new_name}' already exists in project '{project}'"
                        )

                try:
                    select_cols = (
                        "run_id, timestamp, step, metrics"
                        if supports_run_ids
                        else "timestamp, step, metrics"
                    )
                    cursor.execute(
                        f"SELECT {select_cols} FROM metrics WHERE {run_col} = ?",
                        (run_value,),
                    )
                    metrics_rows = cursor.fetchall()

                    old_prefix = f"{project}/{old_name}/"
                    new_prefix = f"{project}/{new_name}/"

                    updated_rows = []
                    for row in metrics_rows:
                        metrics_data = orjson.loads(row["metrics"])
                        metrics_deserialized = deserialize_values(metrics_data)
                        updated = SQLiteStorage._update_media_paths(
                            metrics_deserialized, old_prefix, new_prefix
                        )
                        if supports_run_ids:
                            updated_rows.append(
                                (
                                    row["run_id"],
                                    row["timestamp"],
                                    new_name,
                                    row["step"],
                                    orjson.dumps(serialize_values(updated)),
                                )
                            )
                        else:
                            updated_rows.append(
                                (
                                    row["timestamp"],
                                    new_name,
                                    row["step"],
                                    orjson.dumps(serialize_values(updated)),
                                )
                            )

                    cursor.execute(
                        f"DELETE FROM metrics WHERE {run_col} = ?", (run_value,)
                    )
                    if supports_run_ids:
                        cursor.executemany(
                            "INSERT INTO metrics (run_id, timestamp, run_name, step, metrics) VALUES (?, ?, ?, ?, ?)",
                            updated_rows,
                        )
                    else:
                        cursor.executemany(
                            "INSERT INTO metrics (timestamp, run_name, step, metrics) VALUES (?, ?, ?, ?)",
                            updated_rows,
                        )

                    config_col = (
                        "run_id"
                        if "run_id" in SQLiteStorage._table_columns(conn, "configs")
                        else "run_name"
                    )
                    cursor.execute(
                        f"UPDATE configs SET run_name = ? WHERE {config_col} = ?",
                        (new_name, run_value),
                    )

                    try:
                        cursor.execute(
                            f"UPDATE system_metrics SET run_name = ? WHERE {run_col} = ?",
                            (new_name, run_value),
                        )
                    except sqlite3.OperationalError:
                        pass

                    try:
                        cursor.execute(
                            f"UPDATE alerts SET run_name = ? WHERE {run_col} = ?",
                            (new_name, run_value),
                        )
                    except sqlite3.OperationalError:
                        pass

                    try:
                        cursor.execute(
                            f"""
                            SELECT id, run_id, timestamp, step, key, trace_index, messages, metadata, search_text, log_id, space_id
                            FROM traces WHERE {run_col} = ?
                            """,
                            (run_value,),
                        )
                        trace_rows = cursor.fetchall()
                        updated_trace_rows = SQLiteStorage._rewrite_trace_rows(
                            trace_rows,
                            new_name,
                            old_prefix,
                            new_prefix,
                            run_id=new_name if not supports_run_ids else None,
                        )
                        cursor.execute(
                            f"DELETE FROM traces WHERE {run_col} = ?", (run_value,)
                        )
                        cursor.executemany(
                            """
                            INSERT INTO traces
                            (id, run_id, timestamp, run_name, step, key, trace_index, messages, metadata, search_text, log_id, space_id)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            updated_trace_rows,
                        )
                    except sqlite3.OperationalError:
                        pass

                    conn.commit()

                    SQLiteStorage._move_media_dir(
                        project_media_dir(project) / old_name,
                        project_media_dir(project) / new_name,
                    )
                except sqlite3.Error as e:
                    raise RuntimeError(
                        f"Database error while renaming run '{old_name}' to '{new_name}': {e}"
                    ) from e

    @staticmethod
    def move_run(
        project: str, run: str, new_project: str, run_id: str | None = None
    ) -> bool:
        """Move a run from one project to another.

        When the source DB supports run_ids, ``run_id`` uniquely identifies the
        run being moved; only that run is touched even when other runs share
        the same ``run`` name.
        """
        source_db_path = SQLiteStorage.get_project_db_path(project)
        if not source_db_path.exists():
            return False

        target_db_path = SQLiteStorage.init_db(new_project)

        with SQLiteStorage._get_process_lock(project):
            with SQLiteStorage._get_process_lock(new_project):
                with SQLiteStorage._get_connection(source_db_path) as source_conn:
                    source_cursor = source_conn.cursor()

                    metrics_has_run_id = SQLiteStorage._supports_run_ids(
                        source_conn, "metrics"
                    )
                    configs_has_run_id = SQLiteStorage._supports_run_ids(
                        source_conn, "configs"
                    )
                    system_has_run_id = SQLiteStorage._supports_run_ids(
                        source_conn, "system_metrics"
                    )
                    alerts_has_run_id = SQLiteStorage._supports_run_ids(
                        source_conn, "alerts"
                    )

                    metrics_identity = SQLiteStorage._resolve_run_identity(
                        source_conn, run_name=run, run_id=run_id, table="metrics"
                    )
                    if metrics_identity is None:
                        return False
                    metrics_col, metrics_val = metrics_identity

                    configs_identity = SQLiteStorage._resolve_run_identity(
                        source_conn, run_name=run, run_id=run_id, table="configs"
                    )
                    system_identity = SQLiteStorage._resolve_run_identity(
                        source_conn,
                        run_name=run,
                        run_id=run_id,
                        table="system_metrics",
                    )
                    alerts_identity = SQLiteStorage._resolve_run_identity(
                        source_conn, run_name=run, run_id=run_id, table="alerts"
                    )
                    traces_identity = SQLiteStorage._resolve_run_identity(
                        source_conn, run_name=run, run_id=run_id, table="traces"
                    )

                    metrics_select = (
                        "SELECT timestamp, step, metrics"
                        + (", run_id" if metrics_has_run_id else "")
                        + f" FROM metrics WHERE {metrics_col} = ?"
                    )
                    source_cursor.execute(metrics_select, (metrics_val,))
                    metrics_rows = source_cursor.fetchall()

                    config_row = None
                    if configs_identity is not None:
                        configs_col, configs_val = configs_identity
                        configs_select = (
                            "SELECT config, created_at"
                            + (", run_id" if configs_has_run_id else "")
                            + f" FROM configs WHERE {configs_col} = ?"
                        )
                        source_cursor.execute(configs_select, (configs_val,))
                        config_row = source_cursor.fetchone()

                    system_metrics_rows = []
                    if system_identity is not None:
                        try:
                            system_col, system_val = system_identity
                            system_select = (
                                "SELECT timestamp, metrics"
                                + (", run_id" if system_has_run_id else "")
                                + f" FROM system_metrics WHERE {system_col} = ?"
                            )
                            source_cursor.execute(system_select, (system_val,))
                            system_metrics_rows = source_cursor.fetchall()
                        except sqlite3.OperationalError:
                            system_metrics_rows = []

                    alert_rows = []
                    if alerts_identity is not None:
                        try:
                            alerts_col, alerts_val = alerts_identity
                            alerts_select = (
                                "SELECT timestamp, title, text, level, step, alert_id"
                                + (", run_id" if alerts_has_run_id else "")
                                + f" FROM alerts WHERE {alerts_col} = ?"
                            )
                            source_cursor.execute(alerts_select, (alerts_val,))
                            alert_rows = source_cursor.fetchall()
                        except sqlite3.OperationalError:
                            alert_rows = []

                    trace_rows = []
                    if traces_identity is not None:
                        try:
                            traces_col, traces_val = traces_identity
                            source_cursor.execute(
                                f"""
                                SELECT id, run_id, timestamp, step, key, trace_index, messages, metadata, search_text, log_id, space_id
                                FROM traces WHERE {traces_col} = ?
                                """,
                                (traces_val,),
                            )
                            trace_rows = source_cursor.fetchall()
                        except sqlite3.OperationalError:
                            trace_rows = []

                    if (
                        not metrics_rows
                        and not config_row
                        and not system_metrics_rows
                        and not trace_rows
                    ):
                        return False

                    with SQLiteStorage._get_connection(target_db_path) as target_conn:
                        target_cursor = target_conn.cursor()

                        old_prefix = f"{project}/{run}/"
                        new_prefix = f"{new_project}/{run}/"
                        target_metrics_run_id = SQLiteStorage._supports_run_ids(
                            target_conn, "metrics"
                        )
                        target_configs_run_id = SQLiteStorage._supports_run_ids(
                            target_conn, "configs"
                        )
                        target_system_run_id = SQLiteStorage._supports_run_ids(
                            target_conn, "system_metrics"
                        )
                        target_alerts_run_id = SQLiteStorage._supports_run_ids(
                            target_conn, "alerts"
                        )
                        target_traces_run_id = SQLiteStorage._supports_run_ids(
                            target_conn, "traces"
                        )

                        needs_generated_run_id = (
                            target_metrics_run_id
                            or target_configs_run_id
                            or target_system_run_id
                            or target_alerts_run_id
                            or target_traces_run_id
                        ) and not (
                            metrics_has_run_id
                            or configs_has_run_id
                            or system_has_run_id
                            or alerts_has_run_id
                        )
                        generated_run_id = (
                            uuid.uuid4().hex if needs_generated_run_id else None
                        )

                        use_metrics_run_id = (
                            metrics_has_run_id and target_metrics_run_id
                        )
                        updated_rows = SQLiteStorage._rewrite_metrics_rows(
                            metrics_rows,
                            run,
                            old_prefix,
                            new_prefix,
                            include_run_id=use_metrics_run_id,
                        )

                        if use_metrics_run_id:
                            target_cursor.executemany(
                                "INSERT INTO metrics (timestamp, run_name, step, metrics, run_id) VALUES (?, ?, ?, ?, ?)",
                                updated_rows,
                            )
                        elif target_metrics_run_id and generated_run_id is not None:
                            target_cursor.executemany(
                                "INSERT INTO metrics (timestamp, run_name, step, metrics, run_id) VALUES (?, ?, ?, ?, ?)",
                                [row + (generated_run_id,) for row in updated_rows],
                            )
                        else:
                            target_cursor.executemany(
                                "INSERT INTO metrics (timestamp, run_name, step, metrics) VALUES (?, ?, ?, ?)",
                                updated_rows,
                            )

                        if config_row:
                            if (
                                configs_has_run_id
                                and target_configs_run_id
                                and "run_id" in config_row.keys()
                            ):
                                target_cursor.execute(
                                    """
                                    INSERT OR REPLACE INTO configs (run_name, config, created_at, run_id)
                                    VALUES (?, ?, ?, ?)
                                    """,
                                    (
                                        run,
                                        config_row["config"],
                                        config_row["created_at"],
                                        config_row["run_id"],
                                    ),
                                )
                            elif target_configs_run_id and generated_run_id is not None:
                                target_cursor.execute(
                                    """
                                    INSERT OR REPLACE INTO configs (run_name, config, created_at, run_id)
                                    VALUES (?, ?, ?, ?)
                                    """,
                                    (
                                        run,
                                        config_row["config"],
                                        config_row["created_at"],
                                        generated_run_id,
                                    ),
                                )
                            else:
                                target_cursor.execute(
                                    """
                                    INSERT OR REPLACE INTO configs (run_name, config, created_at)
                                    VALUES (?, ?, ?)
                                    """,
                                    (
                                        run,
                                        config_row["config"],
                                        config_row["created_at"],
                                    ),
                                )

                        for row in system_metrics_rows:
                            try:
                                if (
                                    system_has_run_id
                                    and target_system_run_id
                                    and "run_id" in row.keys()
                                ):
                                    target_cursor.execute(
                                        """
                                        INSERT INTO system_metrics (timestamp, run_name, metrics, run_id)
                                        VALUES (?, ?, ?, ?)
                                        """,
                                        (
                                            row["timestamp"],
                                            run,
                                            row["metrics"],
                                            row["run_id"],
                                        ),
                                    )
                                elif (
                                    target_system_run_id
                                    and generated_run_id is not None
                                ):
                                    target_cursor.execute(
                                        """
                                        INSERT INTO system_metrics (timestamp, run_name, metrics, run_id)
                                        VALUES (?, ?, ?, ?)
                                        """,
                                        (
                                            row["timestamp"],
                                            run,
                                            row["metrics"],
                                            generated_run_id,
                                        ),
                                    )
                                else:
                                    target_cursor.execute(
                                        """
                                        INSERT INTO system_metrics (timestamp, run_name, metrics)
                                        VALUES (?, ?, ?)
                                        """,
                                        (row["timestamp"], run, row["metrics"]),
                                    )
                            except sqlite3.OperationalError:
                                pass

                        for row in alert_rows:
                            try:
                                if (
                                    alerts_has_run_id
                                    and target_alerts_run_id
                                    and "run_id" in row.keys()
                                ):
                                    target_cursor.execute(
                                        """
                                        INSERT OR IGNORE INTO alerts (timestamp, run_name, title, text, level, step, alert_id, run_id)
                                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                                        """,
                                        (
                                            row["timestamp"],
                                            run,
                                            row["title"],
                                            row["text"],
                                            row["level"],
                                            row["step"],
                                            row["alert_id"],
                                            row["run_id"],
                                        ),
                                    )
                                elif (
                                    target_alerts_run_id
                                    and generated_run_id is not None
                                ):
                                    target_cursor.execute(
                                        """
                                        INSERT OR IGNORE INTO alerts (timestamp, run_name, title, text, level, step, alert_id, run_id)
                                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                                        """,
                                        (
                                            row["timestamp"],
                                            run,
                                            row["title"],
                                            row["text"],
                                            row["level"],
                                            row["step"],
                                            row["alert_id"],
                                            generated_run_id,
                                        ),
                                    )
                                else:
                                    target_cursor.execute(
                                        """
                                        INSERT OR IGNORE INTO alerts (timestamp, run_name, title, text, level, step, alert_id)
                                        VALUES (?, ?, ?, ?, ?, ?, ?)
                                        """,
                                        (
                                            row["timestamp"],
                                            run,
                                            row["title"],
                                            row["text"],
                                            row["level"],
                                            row["step"],
                                            row["alert_id"],
                                        ),
                                    )
                            except sqlite3.OperationalError:
                                pass

                        if trace_rows:
                            trace_run_id = None
                            if target_traces_run_id:
                                if generated_run_id is not None:
                                    trace_run_id = generated_run_id
                                elif traces_identity is not None and trace_rows:
                                    trace_run_id = trace_rows[0]["run_id"]
                            updated_trace_rows = SQLiteStorage._rewrite_trace_rows(
                                trace_rows,
                                run,
                                old_prefix,
                                new_prefix,
                                run_id=trace_run_id,
                            )
                            try:
                                target_cursor.executemany(
                                    """
                                    INSERT OR IGNORE INTO traces
                                    (id, run_id, timestamp, run_name, step, key, trace_index, messages, metadata, search_text, log_id, space_id)
                                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                    """,
                                    updated_trace_rows,
                                )
                            except sqlite3.OperationalError:
                                pass

                        target_conn.commit()

                        SQLiteStorage._move_media_dir(
                            project_media_dir(project) / run,
                            project_media_dir(new_project) / run,
                        )

                        source_cursor.execute(
                            f"DELETE FROM metrics WHERE {metrics_col} = ?",
                            (metrics_val,),
                        )
                        if configs_identity is not None:
                            configs_col, configs_val = configs_identity
                            source_cursor.execute(
                                f"DELETE FROM configs WHERE {configs_col} = ?",
                                (configs_val,),
                            )
                        if system_identity is not None:
                            try:
                                system_col, system_val = system_identity
                                source_cursor.execute(
                                    f"DELETE FROM system_metrics WHERE {system_col} = ?",
                                    (system_val,),
                                )
                            except sqlite3.OperationalError:
                                pass
                        if alerts_identity is not None:
                            try:
                                alerts_col, alerts_val = alerts_identity
                                source_cursor.execute(
                                    f"DELETE FROM alerts WHERE {alerts_col} = ?",
                                    (alerts_val,),
                                )
                            except sqlite3.OperationalError:
                                pass
                        if traces_identity is not None:
                            try:
                                traces_col, traces_val = traces_identity
                                source_cursor.execute(
                                    f"DELETE FROM traces WHERE {traces_col} = ?",
                                    (traces_val,),
                                )
                            except sqlite3.OperationalError:
                                pass
                        source_conn.commit()

                        return True

    @staticmethod
    def get_all_run_configs(project: str) -> dict[str, dict]:
        """Get configurations for all runs in a project."""
        db_path = SQLiteStorage.get_project_db_path(project)
        if not db_path.exists():
            return {}

        with SQLiteStorage._get_connection(db_path) as conn:
            cursor = conn.cursor()
            try:
                config_col = (
                    "run_id"
                    if SQLiteStorage._supports_run_ids(conn, "configs")
                    else "run_name"
                )
                cursor.execute(f"SELECT {config_col}, config FROM configs")

                results = {}
                for row in cursor.fetchall():
                    config = orjson.loads(row["config"])
                    results[row[config_col]] = deserialize_values(config)
                return results
            except sqlite3.OperationalError as e:
                if "no such table: configs" in str(e):
                    return {}
                raise

    @staticmethod
    def get_metric_values(
        project: str,
        run: str | None,
        metric_name: str,
        step: int | None = None,
        around_step: int | None = None,
        at_time: str | None = None,
        window: int | float | None = None,
        run_id: str | None = None,
    ) -> list[dict]:
        """Get values for a specific metric in a project/run with optional filtering.

        Filtering modes:
          - step: return the single row at exactly this step
          - around_step + window: return rows where step is in [around_step - window, around_step + window]
          - at_time + window: return rows within ±window seconds of the ISO timestamp
          - No filters: return all rows
        """
        db_path = SQLiteStorage.get_project_db_path(project)
        if not db_path.exists():
            return []

        with SQLiteStorage._get_connection(db_path) as conn:
            cursor = conn.cursor()
            run_identity = SQLiteStorage._resolve_run_identity(
                conn, run_name=run, run_id=run_id, table="metrics"
            )
            if run_identity is None:
                return []

            query = f"SELECT timestamp, step, metrics FROM metrics WHERE {run_identity[0]} = ?"
            params: list = [run_identity[1]]

            if step is not None:
                query += " AND step = ?"
                params.append(step)
            elif around_step is not None and window is not None:
                query += " AND step >= ? AND step <= ?"
                params.extend([around_step - int(window), around_step + int(window)])
            elif at_time is not None and window is not None:
                query += (
                    " AND timestamp >= datetime(?, '-' || ? || ' seconds')"
                    " AND timestamp <= datetime(?, '+' || ? || ' seconds')"
                )
                params.extend([at_time, int(window), at_time, int(window)])

            query += " ORDER BY timestamp"
            cursor.execute(query, params)

            rows = cursor.fetchall()
            results = []
            for row in rows:
                metrics = orjson.loads(row["metrics"])
                metrics = deserialize_values(metrics)
                if metric_name in metrics:
                    results.append(
                        {
                            "timestamp": row["timestamp"],
                            "step": row["step"],
                            "value": metrics[metric_name],
                        }
                    )
            return results

    @staticmethod
    def get_snapshot(
        project: str,
        run: str | None = None,
        step: int | None = None,
        around_step: int | None = None,
        at_time: str | None = None,
        window: int | float | None = None,
        run_id: str | None = None,
    ) -> dict[str, list[dict]]:
        """Get all metrics at/around a point in time or step.

        Returns a dict mapping metric names to lists of {timestamp, step, value}.
        """
        db_path = SQLiteStorage.get_project_db_path(project)
        if not db_path.exists():
            return {}

        with SQLiteStorage._get_connection(db_path) as conn:
            cursor = conn.cursor()
            run_identity = SQLiteStorage._resolve_run_identity(
                conn, run_name=run, run_id=run_id, table="metrics"
            )
            if run_identity is None:
                return {}
            query = f"SELECT timestamp, step, metrics FROM metrics WHERE {run_identity[0]} = ?"
            params: list = [run_identity[1]]

            if step is not None:
                query += " AND step = ?"
                params.append(step)
            elif around_step is not None and window is not None:
                query += " AND step >= ? AND step <= ?"
                params.extend([around_step - int(window), around_step + int(window)])
            elif at_time is not None and window is not None:
                query += (
                    " AND timestamp >= datetime(?, '-' || ? || ' seconds')"
                    " AND timestamp <= datetime(?, '+' || ? || ' seconds')"
                )
                params.extend([at_time, int(window), at_time, int(window)])

            query += " ORDER BY timestamp"
            cursor.execute(query, params)

            result: dict[str, list[dict]] = {}
            for row in cursor.fetchall():
                metrics = orjson.loads(row["metrics"])
                metrics = deserialize_values(metrics)
                for key, value in metrics.items():
                    if key not in result:
                        result[key] = []
                    result[key].append(
                        {
                            "timestamp": row["timestamp"],
                            "step": row["step"],
                            "value": value,
                        }
                    )
            return result

    @staticmethod
    def get_all_metrics_for_run(
        project: str, run: str | None = None, run_id: str | None = None
    ) -> list[str]:
        """Get all metric names for a specific project/run."""
        return SQLiteStorage._get_metric_names(
            project,
            run,
            "metrics",
            exclude_keys={"timestamp", "step"},
            run_id=run_id,
        )

    @staticmethod
    def _get_metric_names(
        project: str,
        run: str | None,
        table: str,
        exclude_keys: set[str],
        run_id: str | None = None,
    ) -> list[str]:
        db_path = SQLiteStorage.get_project_db_path(project)
        if not db_path.exists():
            return []

        with SQLiteStorage._get_connection(db_path) as conn:
            cursor = conn.cursor()
            try:
                run_identity = SQLiteStorage._resolve_run_identity(
                    conn, run_name=run, run_id=run_id, table=table
                )
                if run_identity is None:
                    return []
                cursor.execute(
                    f"""
                    SELECT metrics
                    FROM {table}
                    WHERE {run_identity[0]} = ?
                    ORDER BY timestamp
                    """,
                    (run_identity[1],),
                )

                rows = cursor.fetchall()
                all_metrics = set()
                for row in rows:
                    metrics = orjson.loads(row["metrics"])
                    metrics = deserialize_values(metrics)
                    for key in metrics.keys():
                        if key not in exclude_keys:
                            all_metrics.add(key)
                return sorted(list(all_metrics))
            except sqlite3.OperationalError as e:
                if f"no such table: {table}" in str(e):
                    return []
                raise

    @staticmethod
    def set_project_metadata(project: str, key: str, value: str) -> None:
        db_path = SQLiteStorage.init_db(project)
        with SQLiteStorage._get_process_lock(project):
            with SQLiteStorage._get_connection(db_path) as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO project_metadata (key, value) VALUES (?, ?)",
                    (key, value),
                )
                conn.commit()

    @staticmethod
    def get_project_metadata(project: str, key: str) -> str | None:
        db_path = SQLiteStorage.get_project_db_path(project)
        if not db_path.exists():
            return None
        with SQLiteStorage._get_connection(db_path) as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(
                    "SELECT value FROM project_metadata WHERE key = ?", (key,)
                )
                row = cursor.fetchone()
                return row[0] if row else None
            except sqlite3.OperationalError:
                return None

    @staticmethod
    def get_space_id(project: str) -> str | None:
        return SQLiteStorage.get_project_metadata(project, "space_id")

    @staticmethod
    def has_pending_data(project: str) -> bool:
        db_path = SQLiteStorage.get_project_db_path(project)
        if not db_path.exists():
            return False
        with SQLiteStorage._get_connection(db_path) as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(
                    "SELECT EXISTS(SELECT 1 FROM metrics WHERE space_id IS NOT NULL LIMIT 1)"
                )
                if cursor.fetchone()[0]:
                    return True
            except sqlite3.OperationalError:
                pass
            try:
                cursor.execute(
                    "SELECT EXISTS(SELECT 1 FROM system_metrics WHERE space_id IS NOT NULL LIMIT 1)"
                )
                if cursor.fetchone()[0]:
                    return True
            except sqlite3.OperationalError:
                pass
            try:
                cursor.execute("SELECT EXISTS(SELECT 1 FROM pending_uploads LIMIT 1)")
                if cursor.fetchone()[0]:
                    return True
            except sqlite3.OperationalError:
                pass
            return False

    @staticmethod
    def get_pending_logs(project: str) -> dict | None:
        return SQLiteStorage._get_pending(
            project, "metrics", extra_fields=["step"], include_config=True
        )

    @staticmethod
    def clear_pending_logs(project: str, metric_ids: list[int]) -> None:
        SQLiteStorage._clear_pending(project, "metrics", metric_ids)

    @staticmethod
    def get_pending_system_logs(project: str) -> dict | None:
        return SQLiteStorage._get_pending(project, "system_metrics")

    @staticmethod
    def _get_pending(
        project: str,
        table: str,
        extra_fields: list[str] | None = None,
        include_config: bool = False,
    ) -> dict | None:
        db_path = SQLiteStorage.get_project_db_path(project)
        if not db_path.exists():
            return None
        extra_cols = ", ".join(extra_fields) + ", " if extra_fields else ""
        with SQLiteStorage._get_connection(db_path) as conn:
            cursor = conn.cursor()
            try:
                run_id_col = (
                    "run_id, " if SQLiteStorage._supports_run_ids(conn, table) else ""
                )
                cursor.execute(
                    f"""SELECT id, timestamp, {run_id_col}run_name, {extra_cols}metrics, log_id, space_id
                    FROM {table} WHERE space_id IS NOT NULL"""
                )
            except sqlite3.OperationalError:
                return None
            rows = cursor.fetchall()
            if not rows:
                return None
            logs = []
            ids = []
            for row in rows:
                metrics = deserialize_values(orjson.loads(row["metrics"]))
                entry = {
                    "project": project,
                    "run": row["run_name"],
                    "run_id": row["run_name"],
                    "metrics": metrics,
                    "timestamp": row["timestamp"],
                    "log_id": row["log_id"],
                }
                if "run_id" in row.keys():
                    entry["run_id"] = row["run_id"]
                for field in extra_fields or []:
                    entry[field] = row[field]
                if include_config:
                    entry["config"] = None
                logs.append(entry)
                ids.append(row["id"])
            return {"logs": logs, "ids": ids, "space_id": rows[0]["space_id"]}

    @staticmethod
    def clear_pending_system_logs(project: str, metric_ids: list[int]) -> None:
        SQLiteStorage._clear_pending(project, "system_metrics", metric_ids)

    @staticmethod
    def _clear_pending(project: str, table: str, ids: list[int]) -> None:
        if not ids:
            return
        db_path = SQLiteStorage.get_project_db_path(project)
        if not db_path.exists():
            return
        with SQLiteStorage._get_process_lock(project):
            with SQLiteStorage._get_connection(db_path) as conn:
                placeholders = ",".join("?" * len(ids))
                conn.execute(
                    f"UPDATE {table} SET space_id = NULL WHERE id IN ({placeholders})",
                    ids,
                )
                conn.commit()

    @staticmethod
    def get_pending_uploads(project: str) -> dict | None:
        db_path = SQLiteStorage.get_project_db_path(project)
        if not db_path.exists():
            return None
        with SQLiteStorage._get_connection(db_path) as conn:
            cursor = conn.cursor()
            try:
                columns = SQLiteStorage._table_columns(conn, "pending_uploads")
                select_cols = [
                    "id",
                    "space_id",
                    "run_name",
                    "step",
                    "file_path",
                    "relative_path",
                ]
                if "run_id" in columns:
                    select_cols.insert(2, "run_id")
                if "kind" in columns:
                    select_cols.append("kind")
                if "digest" in columns:
                    select_cols.append("digest")
                cursor.execute(f"SELECT {', '.join(select_cols)} FROM pending_uploads")
            except sqlite3.OperationalError:
                return None
            rows = cursor.fetchall()
            if not rows:
                return None
            uploads = []
            ids = []
            for row in rows:
                keys = row.keys()
                uploads.append(
                    {
                        "project": project,
                        "run": row["run_name"],
                        "run_id": (
                            row["run_id"] if "run_id" in keys else row["run_name"]
                        )
                        or row["run_name"],
                        "step": row["step"],
                        "file_path": row["file_path"],
                        "relative_path": row["relative_path"],
                        "kind": row["kind"] if "kind" in keys else "media",
                        "digest": row["digest"] if "digest" in keys else None,
                    }
                )
                ids.append(row["id"])
            return {"uploads": uploads, "ids": ids, "space_id": rows[0]["space_id"]}

    @staticmethod
    def clear_pending_uploads(project: str, upload_ids: list[int]) -> None:
        if not upload_ids:
            return
        db_path = SQLiteStorage.get_project_db_path(project)
        if not db_path.exists():
            return
        with SQLiteStorage._get_process_lock(project):
            with SQLiteStorage._get_connection(db_path) as conn:
                placeholders = ",".join("?" * len(upload_ids))
                conn.execute(
                    f"DELETE FROM pending_uploads WHERE id IN ({placeholders})",
                    upload_ids,
                )
                conn.commit()

    @staticmethod
    def add_pending_upload(
        project: str,
        space_id: str,
        run_id: str | None,
        run_name: str | None,
        step: int | None,
        file_path: str,
        relative_path: str | None,
        *,
        kind: str = "media",
        digest: Sha256Digest | None = None,
    ) -> None:
        db_path = SQLiteStorage.init_db(project)
        now = datetime.now(timezone.utc).isoformat()
        with SQLiteStorage._get_process_lock(project):
            with SQLiteStorage._get_connection(db_path) as conn:
                cols, vals = SQLiteStorage._pending_upload_cols_vals(
                    include_run_id=SQLiteStorage._supports_run_ids(
                        conn, "pending_uploads"
                    ),
                    space_id=space_id,
                    run_id=run_id,
                    run_name=run_name,
                    step=step,
                    file_path=file_path,
                    relative_path=relative_path,
                    kind=kind,
                    digest=digest,
                    created_at=now,
                )
                placeholders = ", ".join("?" for _ in cols)
                conn.execute(
                    f"INSERT INTO pending_uploads ({', '.join(cols)}) VALUES ({placeholders})",
                    vals,
                )
                conn.commit()

    @staticmethod
    def _pending_upload_cols_vals(
        *,
        include_run_id: bool,
        space_id: str,
        run_id: str | None,
        run_name: str | None,
        step: int | None,
        file_path: str,
        relative_path: str | None,
        kind: str,
        digest: Sha256Digest | None,
        created_at: str,
    ) -> tuple[list[str], list]:
        """Build the (columns, values) for one pending_uploads row. `run_id` is
        detected at runtime rather than backfilled, so it is dropped on legacy
        DBs whose pending_uploads table predates the column."""
        fields = [
            ("space_id", space_id, True),
            ("run_id", run_id, include_run_id),
            ("run_name", run_name, True),
            ("step", step, True),
            ("file_path", file_path, True),
            ("relative_path", relative_path, True),
            ("kind", kind, True),
            ("digest", digest, True),
            ("created_at", created_at, True),
        ]
        cols = [col for col, _, include in fields if include]
        vals = [val for _, val, include in fields if include]
        return cols, vals

    @staticmethod
    def _canonical_manifest(
        manifest: Manifest,
    ) -> tuple[Manifest, Sha256Digest, int]:
        canonical: Manifest = []
        size_bytes = 0
        for entry in manifest:
            path = entry["path"]
            digest = Sha256Digest(entry["digest"])
            size = int(entry["size"])
            canonical.append({"path": path, "digest": digest, "size": size})
            size_bytes += size
        canonical.sort(key=lambda e: e["path"])
        payload = orjson.dumps(canonical, option=orjson.OPT_SORT_KEYS)
        manifest_digest = Sha256Digest(hashlib.sha256(payload).hexdigest())
        return canonical, manifest_digest, size_bytes

    @staticmethod
    def _create_or_get_artifact_cursor(
        conn: sqlite3.Connection,
        name: str,
        type: str,
        description: str | None,
        now: str,
    ) -> int:
        """Return the id of the artifact named `name`, creating it if absent.
        For an existing artifact a non-None `description` is applied in place
        (the type is immutable and a mismatch raises)."""
        cursor = conn.cursor()
        row = cursor.execute(
            "SELECT id, type FROM artifacts WHERE name = ?", (name,)
        ).fetchone()
        if row is not None:
            if row["type"] != type:
                raise ValueError(
                    f"Artifact '{name}' already exists with type "
                    f"'{row['type']}'; cannot relog with type '{type}'."
                )
            if description is not None:
                cursor.execute(
                    "UPDATE artifacts SET description = ? WHERE id = ?",
                    (description, int(row["id"])),
                )
            return int(row["id"])
        cursor.execute(
            """INSERT INTO artifacts (name, type, description, created_at)
            VALUES (?, ?, ?, ?)""",
            (name, type, description, now),
        )
        return int(cursor.lastrowid)

    @staticmethod
    def create_or_get_artifact(
        project: str,
        name: str,
        type: str,
        description: str | None,
    ) -> int:
        db_path = SQLiteStorage.init_db(project)
        now = datetime.now(timezone.utc).isoformat()
        with SQLiteStorage._get_process_lock(project):
            with SQLiteStorage._get_connection(db_path) as conn:
                artifact_id = SQLiteStorage._create_or_get_artifact_cursor(
                    conn, name, type, description, now
                )
                conn.commit()
                return artifact_id

    @staticmethod
    def _insert_artifact_version_cursor(
        conn: sqlite3.Connection,
        artifact_id: int,
        manifest: Manifest,
        metadata: dict | None,
        producer_run_id: str | None,
        producer_run_name: str | None,
        now: str,
    ) -> tuple[int, int, bool]:
        canonical, manifest_digest, size_bytes = SQLiteStorage._canonical_manifest(
            manifest
        )
        manifest_json = orjson.dumps(canonical).decode("utf-8")
        metadata_json = orjson.dumps(metadata).decode("utf-8") if metadata else None
        cursor = conn.cursor()
        existing = cursor.execute(
            """SELECT id, version FROM artifact_versions
            WHERE artifact_id = ? AND manifest_digest = ?""",
            (artifact_id, manifest_digest),
        ).fetchone()
        if existing is not None:
            if metadata:
                cursor.execute(
                    "UPDATE artifact_versions SET metadata = ? WHERE id = ?",
                    (metadata_json, int(existing["id"])),
                )
            return int(existing["id"]), int(existing["version"]), False
        row = cursor.execute(
            "SELECT MAX(version) AS m FROM artifact_versions WHERE artifact_id = ?",
            (artifact_id,),
        ).fetchone()
        next_version = 0 if row["m"] is None else int(row["m"]) + 1
        cursor.execute(
            """INSERT INTO artifact_versions
            (artifact_id, version, manifest_digest, manifest, metadata,
             size_bytes, producer_run_id, producer_run_name, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                artifact_id,
                next_version,
                manifest_digest,
                manifest_json,
                metadata_json,
                size_bytes,
                producer_run_id,
                producer_run_name,
                now,
            ),
        )
        return int(cursor.lastrowid), next_version, True

    @staticmethod
    def insert_artifact_version(
        project: str,
        artifact_id: int,
        manifest: Manifest,
        metadata: dict | None,
        producer_run_id: str | None,
        producer_run_name: str | None,
    ) -> tuple[int, int, bool]:
        """Returns `(version_id, version, created)`. `created` is False when an
        identical-content version already existed; its `metadata` is refreshed
        in place from the new call (when non-empty) before it is returned."""
        db_path = SQLiteStorage.init_db(project)
        now = datetime.now(timezone.utc).isoformat()
        with SQLiteStorage._get_process_lock(project):
            with SQLiteStorage._get_connection(db_path) as conn:
                result = SQLiteStorage._insert_artifact_version_cursor(
                    conn,
                    artifact_id,
                    manifest,
                    metadata,
                    producer_run_id,
                    producer_run_name,
                    now,
                )
                conn.commit()
                return result

    @staticmethod
    def _reassign_alias_cursor(
        conn: sqlite3.Connection,
        artifact_id: int,
        alias: str,
        version_id: int,
    ) -> None:
        if cas.ARTIFACT_VERSION_SPEC_RE.match(alias):
            raise ValueError(
                f"Alias '{alias}' is reserved for version pointers (vN); choose another."
            )
        conn.execute(
            """INSERT INTO artifact_aliases (artifact_id, alias, artifact_version_id)
            VALUES (?, ?, ?)
            ON CONFLICT(artifact_id, alias) DO UPDATE SET
                artifact_version_id = excluded.artifact_version_id""",
            (artifact_id, alias, version_id),
        )

    @staticmethod
    def _reassign_alias_forward_cursor(
        conn: sqlite3.Connection,
        artifact_id: int,
        alias: str,
        version_id: int,
        version_int: int,
    ) -> None:
        """Reassign `alias` only when it does not move backward."""
        current = conn.execute(
            """SELECT av.version FROM artifact_aliases aa
            JOIN artifact_versions av ON av.id = aa.artifact_version_id
            WHERE aa.artifact_id = ? AND aa.alias = ?""",
            (artifact_id, alias),
        ).fetchone()
        if current is not None and int(current["version"]) > version_int:
            return
        SQLiteStorage._reassign_alias_cursor(conn, artifact_id, alias, version_id)

    @staticmethod
    def reassign_alias(
        project: str,
        artifact_id: int,
        alias: str,
        version_id: int,
    ) -> None:
        db_path = SQLiteStorage.init_db(project)
        with SQLiteStorage._get_process_lock(project):
            with SQLiteStorage._get_connection(db_path) as conn:
                SQLiteStorage._reassign_alias_cursor(
                    conn, artifact_id, alias, version_id
                )
                conn.commit()

    @staticmethod
    def _resolve_artifact_version_cursor(
        conn: sqlite3.Connection,
        name: str,
        spec: str | None,
    ) -> dict | None:
        cursor = conn.cursor()
        art = cursor.execute(
            "SELECT id FROM artifacts WHERE name = ?", (name,)
        ).fetchone()
        if art is None:
            return None
        artifact_id = int(art["id"])
        spec = spec if spec else "latest"
        m = cas.ARTIFACT_VERSION_SPEC_RE.match(spec)
        if m:
            version_int = int(m.group(1))
            ver = cursor.execute(
                """SELECT id, version FROM artifact_versions
                WHERE artifact_id = ? AND version = ?""",
                (artifact_id, version_int),
            ).fetchone()
        else:
            ver = cursor.execute(
                """SELECT av.id, av.version FROM artifact_versions av
                JOIN artifact_aliases aa ON aa.artifact_version_id = av.id
                WHERE aa.artifact_id = ? AND aa.alias = ?""",
                (artifact_id, spec),
            ).fetchone()
        if ver is None:
            return None
        return {
            "artifact_id": artifact_id,
            "version_id": int(ver["id"]),
            "version": int(ver["version"]),
        }

    @staticmethod
    def resolve_artifact_version(
        project: str,
        name: str,
        spec: str | None,
    ) -> dict | None:
        SQLiteStorage._ensure_hub_loaded()
        db_path = SQLiteStorage.get_project_db_path(project)
        if not db_path.exists():
            return None
        with SQLiteStorage._get_connection(db_path) as conn:
            return SQLiteStorage._resolve_artifact_version_cursor(conn, name, spec)

    @staticmethod
    def _insert_run_artifact_link_cursor(
        conn: sqlite3.Connection,
        run_name: str | None,
        run_id: str | None,
        version_id: int,
        direction: str,
        now: str,
    ) -> None:
        if direction not in ("input", "output"):
            raise ValueError(
                f"direction must be 'input' or 'output', got {direction!r}"
            )
        conn.execute(
            """INSERT OR IGNORE INTO run_artifact_links
            (run_id, run_name, artifact_version_id, direction, created_at)
            VALUES (?, ?, ?, ?, ?)""",
            (run_id, run_name, version_id, direction, now),
        )

    @staticmethod
    def insert_run_artifact_link(
        project: str,
        run_name: str | None,
        run_id: str | None,
        version_id: int,
        direction: str,
    ) -> None:
        db_path = SQLiteStorage.init_db(project)
        now = datetime.now(timezone.utc).isoformat()
        with SQLiteStorage._get_process_lock(project):
            with SQLiteStorage._get_connection(db_path) as conn:
                SQLiteStorage._insert_run_artifact_link_cursor(
                    conn, run_name, run_id, version_id, direction, now
                )
                conn.commit()

    @staticmethod
    def commit_artifact_version(
        project: str,
        name: str,
        type: str,
        description: str | None,
        manifest: Manifest,
        metadata: dict | None,
        aliases: list[str] | None,
        run_name: str | None,
        run_id: str | None,
    ) -> dict:
        """Commit a new artifact version and return its full manifest record.
        `latest` advances only when a new version is created, so re-logging
        identical or older content never regresses `latest`. Moving aliases are
        reassigned the same way: a content-dedup hit to an older version never
        drags an existing alias backward, but a first-time or forward tag lands.
        """
        db_path = SQLiteStorage.init_db(project)
        now = datetime.now(timezone.utc).isoformat()
        with SQLiteStorage._get_process_lock(project):
            with SQLiteStorage._get_connection(db_path) as conn:
                artifact_id = SQLiteStorage._create_or_get_artifact_cursor(
                    conn, name, type, description, now
                )
                version_id, version_int, created = (
                    SQLiteStorage._insert_artifact_version_cursor(
                        conn, artifact_id, manifest, metadata, run_id, run_name, now
                    )
                )
                if created:
                    SQLiteStorage._reassign_alias_cursor(
                        conn, artifact_id, "latest", version_id
                    )
                for alias in aliases or []:
                    SQLiteStorage._reassign_alias_forward_cursor(
                        conn, artifact_id, alias, version_id, version_int
                    )
                SQLiteStorage._insert_run_artifact_link_cursor(
                    conn, run_name, run_id, version_id, "output", now
                )
                conn.commit()
                return SQLiteStorage._get_artifact_manifest_cursor(
                    conn, name, f"v{version_int}"
                )

    @staticmethod
    def _get_artifact_manifest_cursor(
        conn: sqlite3.Connection,
        name: str,
        spec: str | None,
    ) -> dict | None:
        resolved = SQLiteStorage._resolve_artifact_version_cursor(conn, name, spec)
        if resolved is None:
            return None
        cursor = conn.cursor()
        row = cursor.execute(
            """SELECT av.id, av.version, av.manifest, av.manifest_digest,
                   av.metadata, av.size_bytes, av.producer_run_id,
                   av.producer_run_name, av.created_at,
                   a.name, a.type, a.description
            FROM artifact_versions av
            JOIN artifacts a ON a.id = av.artifact_id
            WHERE av.id = ?""",
            (resolved["version_id"],),
        ).fetchone()
        if row is None:
            return None
        alias_rows = cursor.execute(
            """SELECT alias FROM artifact_aliases
            WHERE artifact_version_id = ?""",
            (resolved["version_id"],),
        ).fetchall()
        return {
            "artifact_id": resolved["artifact_id"],
            "version_id": int(row["id"]),
            "version": int(row["version"]),
            "name": row["name"],
            "type": row["type"],
            "description": row["description"],
            "manifest": orjson.loads(row["manifest"]),
            "manifest_digest": row["manifest_digest"],
            "metadata": (
                orjson.loads(row["metadata"]) if row["metadata"] is not None else None
            ),
            "size_bytes": int(row["size_bytes"]),
            "producer_run_id": row["producer_run_id"],
            "producer_run_name": row["producer_run_name"],
            "created_at": row["created_at"],
            "aliases": [r["alias"] for r in alias_rows],
        }

    @staticmethod
    def get_artifact_manifest(
        project: str,
        name: str,
        spec: str | None,
    ) -> dict | None:
        SQLiteStorage._ensure_hub_loaded()
        db_path = SQLiteStorage.get_project_db_path(project)
        if not db_path.exists():
            return None
        with SQLiteStorage._get_connection(db_path) as conn:
            return SQLiteStorage._get_artifact_manifest_cursor(conn, name, spec)

    @staticmethod
    def get_run_artifacts(
        project: str,
        run_name: str | None,
        run_id: str | None,
    ) -> dict[str, list[dict]]:
        SQLiteStorage._ensure_hub_loaded()
        empty = {"input": [], "output": []}
        db_path = SQLiteStorage.get_project_db_path(project)
        if not db_path.exists():
            return empty
        with SQLiteStorage._get_connection(db_path) as conn:
            identity = SQLiteStorage._resolve_run_identity(
                conn, run_name=run_name, run_id=run_id, table="run_artifact_links"
            )
            if identity is None:
                col, val = (
                    ("run_id", run_id) if run_id is not None else ("run_name", run_name)
                )
            else:
                col, val = identity
            if val is None:
                return empty
            cursor = conn.cursor()
            rows = cursor.execute(
                f"""SELECT ral.direction, ral.created_at,
                       av.id AS version_id, av.version, av.size_bytes,
                       a.name, a.type
                FROM run_artifact_links ral
                JOIN artifact_versions av ON av.id = ral.artifact_version_id
                JOIN artifacts a ON a.id = av.artifact_id
                WHERE ral.{col} = ?
                ORDER BY ral.created_at""",
                (val,),
            ).fetchall()
            result: dict[str, list[dict]] = {"input": [], "output": []}
            for row in rows:
                result[row["direction"]].append(
                    {
                        "version_id": int(row["version_id"]),
                        "name": row["name"],
                        "type": row["type"],
                        "version": int(row["version"]),
                        "size_bytes": int(row["size_bytes"]),
                        "created_at": row["created_at"],
                    }
                )
            return result

    @staticmethod
    def enqueue_artifact_blob_uploads(
        project: str,
        space_id: str,
        blobs: list[tuple[Sha256Digest, str]],
        run_name: str | None,
        run_id: str | None,
    ) -> None:
        """Enqueue one pending_uploads row per `(digest, local_blob_path)` in
        a single connection/transaction."""
        if not blobs:
            return
        db_path = SQLiteStorage.init_db(project)
        now = datetime.now(timezone.utc).isoformat()
        with SQLiteStorage._get_process_lock(project):
            with SQLiteStorage._get_connection(db_path) as conn:
                include_run_id = SQLiteStorage._supports_run_ids(
                    conn, "pending_uploads"
                )
                rows = [
                    SQLiteStorage._pending_upload_cols_vals(
                        include_run_id=include_run_id,
                        space_id=space_id,
                        run_id=run_id,
                        run_name=run_name,
                        step=None,
                        file_path=file_path,
                        relative_path=None,
                        kind="artifact_blob",
                        digest=digest,
                        created_at=now,
                    )
                    for digest, file_path in blobs
                ]
                cols = rows[0][0]
                placeholders = ", ".join("?" for _ in cols)
                conn.executemany(
                    f"INSERT INTO pending_uploads ({', '.join(cols)}) VALUES ({placeholders})",
                    [vals for _, vals in rows],
                )
                conn.commit()

    @staticmethod
    def list_artifact_blobs_present(
        project: str,
        digests: list[Sha256Digest],
    ) -> set[Sha256Digest]:
        SQLiteStorage._ensure_hub_loaded()
        present: set[Sha256Digest] = set()
        for digest in digests:
            if not cas.SHA256_DIGEST_RE.match(digest):
                continue
            if cas.blob_path(project, digest).is_file():
                present.add(digest)
        return present

    @staticmethod
    def get_all_logs_for_sync(project: str) -> list[dict]:
        return SQLiteStorage._get_all_for_sync(
            project,
            "metrics",
            order_by="run_name, step",
            extra_fields=["step"],
            include_config=True,
        )

    @staticmethod
    def get_all_system_logs_for_sync(project: str) -> list[dict]:
        return SQLiteStorage._get_all_for_sync(
            project, "system_metrics", order_by="run_name, timestamp"
        )

    @staticmethod
    def _get_all_for_sync(
        project: str,
        table: str,
        order_by: str,
        extra_fields: list[str] | None = None,
        include_config: bool = False,
    ) -> list[dict]:
        db_path = SQLiteStorage.get_project_db_path(project)
        if not db_path.exists():
            return []
        extra_cols = ", ".join(extra_fields) + ", " if extra_fields else ""
        with SQLiteStorage._get_connection(db_path) as conn:
            cursor = conn.cursor()
            try:
                run_id_col = (
                    "run_id, " if SQLiteStorage._supports_run_ids(conn, table) else ""
                )
                cursor.execute(
                    f"""SELECT timestamp, {run_id_col}run_name, {extra_cols}metrics, log_id
                    FROM {table} ORDER BY {order_by}"""
                )
            except sqlite3.OperationalError:
                return []
            rows = cursor.fetchall()
            results = []
            for row in rows:
                metrics = deserialize_values(orjson.loads(row["metrics"]))
                entry = {
                    "project": project,
                    "run": row["run_name"],
                    "run_id": row["run_name"],
                    "metrics": metrics,
                    "timestamp": row["timestamp"],
                    "log_id": row["log_id"],
                }
                if "run_id" in row.keys():
                    entry["run_id"] = row["run_id"]
                for field in extra_fields or []:
                    entry[field] = row[field]
                if include_config:
                    entry["config"] = None
                results.append(entry)
            return results
