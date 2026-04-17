import atexit
import json as json_mod
import os
import shutil
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
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

from trackio.commit_scheduler import CommitScheduler
from trackio.dummy_commit_scheduler import DummyCommitScheduler
from trackio.utils import (
    MEDIA_DIR,
    TRACKIO_DIR,
    deserialize_values,
    get_color_palette,
    on_spaces,
    serialize_values,
)

DB_EXT = ".db"

_JOURNAL_MODE_WHITELIST = frozenset(
    {"wal", "delete", "truncate", "persist", "memory", "off"}
)
_READ_ONLY_QUERY_PREFIXES = ("select", "with", "pragma")
_QUERY_MAX_ROWS = 10_000
_READ_ONLY_PRAGMAS = frozenset(
    {"table_info", "table_xinfo", "index_list", "index_info", "index_xinfo"}
)


def _configure_sqlite_pragmas(conn: sqlite3.Connection) -> None:
    override = os.environ.get("TRACKIO_SQLITE_JOURNAL_MODE", "").strip().lower()
    if override in _JOURNAL_MODE_WHITELIST:
        journal = override.upper()
    elif on_spaces():
        journal = "DELETE"
    else:
        journal = "WAL"
    conn.execute(f"PRAGMA journal_mode = {journal}")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA temp_store = MEMORY")
    conn.execute("PRAGMA cache_size = -20000")
    if on_spaces():
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


class SQLiteStorage:
    _dataset_import_attempted = False
    _current_scheduler: CommitScheduler | DummyCommitScheduler | None = None
    _scheduler_lock = Lock()

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
        lockfile_path = TRACKIO_DIR / f"{project}.lock"
        return ProcessLock(lockfile_path)

    @staticmethod
    def get_project_db_filename(project: str) -> str:
        """Get the database filename for a specific project."""
        safe_project_name = "".join(
            c for c in project if c.isalnum() or c in ("-", "_")
        ).rstrip()
        if not safe_project_name:
            safe_project_name = "default"
        return f"{safe_project_name}{DB_EXT}"

    @staticmethod
    def get_project_db_path(project: str) -> Path:
        """Get the database path for a specific project."""
        filename = SQLiteStorage.get_project_db_filename(project)
        return TRACKIO_DIR / filename

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
        table = pa.Table.from_pylist(rows)
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
        if (
            parquet_path.exists()
            and db_path.stat().st_mtime <= parquet_path.stat().st_mtime
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

        configs_rows = SQLiteStorage._read_table_rows(db_path, "configs")
        if configs_rows:
            flat = SQLiteStorage._flatten_json_rows(configs_rows, "config")
            SQLiteStorage._write_parquet_rows(aux_dir / "configs.parquet", flat)

        try:
            with SQLiteStorage._get_connection(db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """SELECT run_name, MAX(step) as last_step, COUNT(*) as log_count
                    FROM metrics GROUP BY run_name ORDER BY MIN(timestamp) ASC"""
                )
                rows = cursor.fetchall()
                runs_meta = [
                    {
                        "name": row["run_name"],
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
    def import_from_parquet():
        """
        Imports to all DB files that have matching files under the same path but with extension ".parquet".
        Also imports system_metrics from "_system.parquet" files.
        Also imports configs from "_configs.parquet" files.
        """
        if not TRACKIO_DIR.exists():
            return

        all_paths = os.listdir(TRACKIO_DIR)
        parquet_names = [
            f
            for f in all_paths
            if f.endswith(".parquet")
            and not f.endswith("_system.parquet")
            and not f.endswith("_configs.parquet")
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
                        "media/**/*",
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
                            orjson.dumps(serialize_values(metrics)),
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
                            orjson.dumps(serialize_values(metrics)),
                        ),
                    )
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
                for i, metrics in enumerate(metrics_list):
                    lid = log_ids[i] if log_ids else None
                    if supports_run_ids:
                        data.append(
                            (
                                timestamps[i],
                                resolved_run_id,
                                run,
                                steps[i],
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
                                steps[i],
                                orjson.dumps(serialize_values(metrics)),
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
    def get_system_logs(
        project: str, run: str | None = None, run_id: str | None = None
    ) -> list[dict]:
        """Retrieve system metrics for a specific run. Returns metrics with timestamps (no steps)."""
        db_path = SQLiteStorage.get_project_db_path(project)
        if not db_path.exists():
            return []

        with SQLiteStorage._get_connection(db_path) as conn:
            cursor = conn.cursor()
            try:
                run_identity = SQLiteStorage._resolve_run_identity(
                    conn, run_name=run, run_id=run_id, table="system_metrics"
                )
                if run_identity is None:
                    return []
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
                results = []
                for row in rows:
                    metrics = orjson.loads(row["metrics"])
                    metrics = deserialize_values(metrics)
                    metrics["timestamp"] = row["timestamp"]
                    results.append(metrics)
                return results
            except sqlite3.OperationalError as e:
                if "no such table: system_metrics" in str(e):
                    return []
                raise

    @staticmethod
    def get_all_system_metrics_for_run(project: str, run: str) -> list[str]:
        """Get all system metric names for a specific project/run."""
        return SQLiteStorage._get_metric_names(
            project, run, "system_metrics", exclude_keys={"timestamp"}
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

        try:
            with SQLiteStorage._get_connection(db_path) as conn:
                cursor = conn.cursor()
                run_identity = SQLiteStorage._resolve_run_identity(
                    conn, run_name=run, run_id=run_id
                )
                if run_identity is None:
                    return []
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
                if max_points is not None and len(rows) > max_points:
                    step = len(rows) / max_points
                    indices = {int(i * step) for i in range(max_points)}
                    indices.add(len(rows) - 1)
                    rows = [rows[i] for i in sorted(indices)]

                results = []
                for row in rows:
                    metrics = orjson.loads(row["metrics"])
                    metrics = deserialize_values(metrics)
                    metrics["timestamp"] = row["timestamp"]
                    metrics["step"] = row["step"]
                    results.append(metrics)
                return results
        except sqlite3.OperationalError as e:
            if "no such table: metrics" in str(e):
                return []
            raise

    @staticmethod
    def load_from_dataset():
        bucket_id = os.environ.get("TRACKIO_BUCKET_ID")
        if bucket_id is not None:
            if not SQLiteStorage._dataset_import_attempted:
                from trackio.bucket_storage import download_bucket_to_trackio_dir

                try:
                    download_bucket_to_trackio_dir(bucket_id)
                except Exception:
                    pass
            SQLiteStorage._dataset_import_attempted = True
            return
        dataset_id = os.environ.get("TRACKIO_DATASET_ID")
        space_repo_name = os.environ.get("SPACE_REPO_NAME")
        if dataset_id is not None and space_repo_name is not None:
            hfapi = hf.HfApi()
            updated = False
            if not TRACKIO_DIR.exists():
                TRACKIO_DIR.mkdir(parents=True, exist_ok=True)
            with SQLiteStorage.get_scheduler().lock:
                try:
                    files = hfapi.list_repo_files(dataset_id, repo_type="dataset")
                    for file in files:
                        # Download parquet and media assets
                        if not (file.endswith(".parquet") or file.startswith("media/")):
                            continue
                        if (TRACKIO_DIR / file).exists():
                            continue
                        hf.hf_hub_download(
                            dataset_id, file, repo_type="dataset", local_dir=TRACKIO_DIR
                        )
                        updated = True
                except hf.errors.EntryNotFoundError:
                    pass
                except hf.errors.RepositoryNotFoundError:
                    pass
                if updated:
                    SQLiteStorage.import_from_parquet()
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
    def _rewrite_metrics_rows(metrics_rows, new_run_name, old_prefix, new_prefix):
        """Deserialize metrics rows, update media paths, and reserialize."""
        result = []
        for row in metrics_rows:
            metrics_data = orjson.loads(row["metrics"])
            metrics_deserialized = deserialize_values(metrics_data)
            updated = SQLiteStorage._update_media_paths(
                metrics_deserialized, old_prefix, new_prefix
            )
            result.append(
                (
                    row["timestamp"],
                    new_run_name,
                    row["step"],
                    orjson.dumps(serialize_values(updated)),
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
    def rename_run(project: str, old_name: str, new_name: str) -> None:
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
                    conn, run_name=old_name
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

                    conn.commit()

                    SQLiteStorage._move_media_dir(
                        MEDIA_DIR / project / old_name,
                        MEDIA_DIR / project / new_name,
                    )
                except sqlite3.Error as e:
                    raise RuntimeError(
                        f"Database error while renaming run '{old_name}' to '{new_name}': {e}"
                    ) from e

    @staticmethod
    def move_run(project: str, run: str, new_project: str) -> bool:
        """Move a run from one project to another."""
        source_db_path = SQLiteStorage.get_project_db_path(project)
        if not source_db_path.exists():
            return False

        target_db_path = SQLiteStorage.init_db(new_project)

        with SQLiteStorage._get_process_lock(project):
            with SQLiteStorage._get_process_lock(new_project):
                with SQLiteStorage._get_connection(source_db_path) as source_conn:
                    source_cursor = source_conn.cursor()

                    source_cursor.execute(
                        "SELECT timestamp, step, metrics FROM metrics WHERE run_name = ?",
                        (run,),
                    )
                    metrics_rows = source_cursor.fetchall()

                    source_cursor.execute(
                        "SELECT config, created_at FROM configs WHERE run_name = ?",
                        (run,),
                    )
                    config_row = source_cursor.fetchone()

                    try:
                        source_cursor.execute(
                            "SELECT timestamp, metrics FROM system_metrics WHERE run_name = ?",
                            (run,),
                        )
                        system_metrics_rows = source_cursor.fetchall()
                    except sqlite3.OperationalError:
                        system_metrics_rows = []

                    try:
                        source_cursor.execute(
                            "SELECT timestamp, title, text, level, step, alert_id FROM alerts WHERE run_name = ?",
                            (run,),
                        )
                        alert_rows = source_cursor.fetchall()
                    except sqlite3.OperationalError:
                        alert_rows = []

                    if not metrics_rows and not config_row and not system_metrics_rows:
                        return False

                    with SQLiteStorage._get_connection(target_db_path) as target_conn:
                        target_cursor = target_conn.cursor()

                        old_prefix = f"{project}/{run}/"
                        new_prefix = f"{new_project}/{run}/"
                        updated_rows = SQLiteStorage._rewrite_metrics_rows(
                            metrics_rows, run, old_prefix, new_prefix
                        )

                        target_cursor.executemany(
                            "INSERT INTO metrics (timestamp, run_name, step, metrics) VALUES (?, ?, ?, ?)",
                            updated_rows,
                        )

                        if config_row:
                            target_cursor.execute(
                                """
                                INSERT OR REPLACE INTO configs (run_name, config, created_at)
                                VALUES (?, ?, ?)
                                """,
                                (run, config_row["config"], config_row["created_at"]),
                            )

                        for row in system_metrics_rows:
                            try:
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

                        target_conn.commit()

                        SQLiteStorage._move_media_dir(
                            MEDIA_DIR / project / run,
                            MEDIA_DIR / new_project / run,
                        )

                        source_cursor.execute(
                            "DELETE FROM metrics WHERE run_name = ?", (run,)
                        )
                        source_cursor.execute(
                            "DELETE FROM configs WHERE run_name = ?", (run,)
                        )
                        try:
                            source_cursor.execute(
                                "DELETE FROM system_metrics WHERE run_name = ?", (run,)
                            )
                        except sqlite3.OperationalError:
                            pass
                        try:
                            source_cursor.execute(
                                "DELETE FROM alerts WHERE run_name = ?", (run,)
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
                cursor.execute(
                    """
                    SELECT run_name, config FROM configs
                    """
                )

                results = {}
                for row in cursor.fetchall():
                    config = orjson.loads(row["config"])
                    results[row["run_name"]] = deserialize_values(config)
                return results
            except sqlite3.OperationalError as e:
                if "no such table: configs" in str(e):
                    return {}
                raise

    @staticmethod
    def get_metric_values(
        project: str,
        run: str,
        metric_name: str,
        step: int | None = None,
        around_step: int | None = None,
        at_time: str | None = None,
        window: int | float | None = None,
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
            query = "SELECT timestamp, step, metrics FROM metrics WHERE run_name = ?"
            params: list = [run]

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
        run: str,
        step: int | None = None,
        around_step: int | None = None,
        at_time: str | None = None,
        window: int | float | None = None,
    ) -> dict[str, list[dict]]:
        """Get all metrics at/around a point in time or step.

        Returns a dict mapping metric names to lists of {timestamp, step, value}.
        """
        db_path = SQLiteStorage.get_project_db_path(project)
        if not db_path.exists():
            return {}

        with SQLiteStorage._get_connection(db_path) as conn:
            cursor = conn.cursor()
            query = "SELECT timestamp, step, metrics FROM metrics WHERE run_name = ?"
            params: list = [run]

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
    def get_all_metrics_for_run(project: str, run: str) -> list[str]:
        """Get all metric names for a specific project/run."""
        return SQLiteStorage._get_metric_names(
            project, run, "metrics", exclude_keys={"timestamp", "step"}
        )

    @staticmethod
    def _get_metric_names(
        project: str, run: str, table: str, exclude_keys: set[str]
    ) -> list[str]:
        db_path = SQLiteStorage.get_project_db_path(project)
        if not db_path.exists():
            return []

        with SQLiteStorage._get_connection(db_path) as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(
                    f"""
                    SELECT metrics
                    FROM {table}
                    WHERE run_name = ?
                    ORDER BY timestamp
                    """,
                    (run,),
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
                run_id_col = "run_id, " if "run_id" in columns else ""
                cursor.execute(
                    f"""SELECT id, space_id, {run_id_col}run_name, step, file_path, relative_path
                    FROM pending_uploads"""
                )
            except sqlite3.OperationalError:
                return None
            rows = cursor.fetchall()
            if not rows:
                return None
            uploads = []
            ids = []
            for row in rows:
                uploads.append(
                    {
                        "project": project,
                        "run": row["run_name"],
                        "run_id": (
                            row["run_id"] if "run_id" in row.keys() else row["run_name"]
                        )
                        or row["run_name"],
                        "step": row["step"],
                        "file_path": row["file_path"],
                        "relative_path": row["relative_path"],
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
    ) -> None:
        db_path = SQLiteStorage.init_db(project)
        with SQLiteStorage._get_process_lock(project):
            with SQLiteStorage._get_connection(db_path) as conn:
                if SQLiteStorage._supports_run_ids(conn, "pending_uploads"):
                    conn.execute(
                        """INSERT INTO pending_uploads
                        (space_id, run_id, run_name, step, file_path, relative_path, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?)""",
                        (
                            space_id,
                            run_id,
                            run_name,
                            step,
                            file_path,
                            relative_path,
                            datetime.now(timezone.utc).isoformat(),
                        ),
                    )
                else:
                    conn.execute(
                        """INSERT INTO pending_uploads
                        (space_id, run_name, step, file_path, relative_path, created_at)
                        VALUES (?, ?, ?, ?, ?, ?)""",
                        (
                            space_id,
                            run_name,
                            step,
                            file_path,
                            relative_path,
                            datetime.now(timezone.utc).isoformat(),
                        ),
                    )
                conn.commit()

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
