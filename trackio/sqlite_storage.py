import os
import platform
import shutil
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock

try:
    import fcntl
except ImportError:  # fcntl is not available on Windows
    fcntl = None

import huggingface_hub as hf
import orjson
import pandas as pd

from trackio.commit_scheduler import CommitScheduler
from trackio.dummy_commit_scheduler import DummyCommitScheduler
from trackio.utils import (
    MEDIA_DIR,
    TRACKIO_DIR,
    deserialize_values,
    serialize_values,
)

DB_EXT = ".db"


class ProcessLock:
    """A file-based lock that works across processes. Is a no-op on Windows."""

    def __init__(self, lockfile_path: Path):
        self.lockfile_path = lockfile_path
        self.lockfile = None
        self.is_windows = platform.system() == "Windows"

    def __enter__(self):
        """Acquire the lock with retry logic."""
        if self.is_windows:
            return self
        self.lockfile_path.parent.mkdir(parents=True, exist_ok=True)
        self.lockfile = open(self.lockfile_path, "w")

        max_retries = 100
        for attempt in range(max_retries):
            try:
                fcntl.flock(self.lockfile.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                return self
            except IOError:
                if attempt < max_retries - 1:
                    time.sleep(0.1)
                else:
                    raise IOError("Could not acquire database lock after 10 seconds")

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Release the lock."""
        if self.is_windows:
            return

        if self.lockfile:
            fcntl.flock(self.lockfile.fileno(), fcntl.LOCK_UN)
            self.lockfile.close()


class SQLiteStorage:
    _dataset_import_attempted = False
    _current_scheduler: CommitScheduler | DummyCommitScheduler | None = None
    _scheduler_lock = Lock()

    @staticmethod
    def _get_connection(db_path: Path) -> sqlite3.Connection:
        conn = sqlite3.connect(str(db_path), timeout=30.0)
        # Keep WAL for concurrency + performance on many small writes
        conn.execute("PRAGMA journal_mode = WAL")
        # ---- Minimal perf tweaks for many tiny transactions ----
        # NORMAL = fsync at critical points only (safer than OFF, much faster than FULL)
        conn.execute("PRAGMA synchronous = NORMAL")
        # Keep temp data in memory to avoid disk hits during small writes
        conn.execute("PRAGMA temp_store = MEMORY")
        # Give SQLite a bit more room for cache (negative = KB, engine-managed)
        conn.execute("PRAGMA cache_size = -20000")
        # --------------------------------------------------------
        conn.row_factory = sqlite3.Row
        return conn

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
        db_path = SQLiteStorage.get_project_db_path(project)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        with SQLiteStorage._get_process_lock(project):
            with sqlite3.connect(str(db_path), timeout=30.0) as conn:
                conn.execute("PRAGMA journal_mode = WAL")
                conn.execute("PRAGMA synchronous = NORMAL")
                conn.execute("PRAGMA temp_store = MEMORY")
                conn.execute("PRAGMA cache_size = -20000")
                cursor = conn.cursor()
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS metrics (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
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
                        run_name TEXT NOT NULL,
                        config TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        UNIQUE(run_name)
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_metrics_run_step
                    ON metrics(run_name, step)
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_configs_run_name
                    ON configs(run_name)
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_metrics_run_timestamp
                    ON metrics(run_name, timestamp)
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS system_metrics (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp TEXT NOT NULL,
                        run_name TEXT NOT NULL,
                        metrics TEXT NOT NULL
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_system_metrics_run_timestamp
                    ON system_metrics(run_name, timestamp)
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
                        run_name TEXT,
                        step INTEGER,
                        file_path TEXT NOT NULL,
                        relative_path TEXT,
                        created_at TEXT NOT NULL
                    )
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
            parquet_path = db_path.with_suffix(".parquet")
            system_parquet_path = db_path.with_suffix("") / ""
            system_parquet_path = TRACKIO_DIR / (db_path.stem + "_system.parquet")
            configs_parquet_path = TRACKIO_DIR / (db_path.stem + "_configs.parquet")
            if (not parquet_path.exists()) or (
                db_path.stat().st_mtime > parquet_path.stat().st_mtime
            ):
                with sqlite3.connect(str(db_path)) as conn:
                    df = pd.read_sql("SELECT * FROM metrics", conn)
                if not df.empty:
                    metrics = df["metrics"].copy()
                    metrics = pd.DataFrame(
                        metrics.apply(
                            lambda x: deserialize_values(orjson.loads(x))
                        ).values.tolist(),
                        index=df.index,
                    )
                    del df["metrics"]
                    for col in metrics.columns:
                        df[col] = metrics[col]
                    df.to_parquet(
                        parquet_path,
                        write_page_index=True,
                        use_content_defined_chunking=True,
                    )

            if (not system_parquet_path.exists()) or (
                db_path.stat().st_mtime > system_parquet_path.stat().st_mtime
            ):
                with sqlite3.connect(str(db_path)) as conn:
                    try:
                        sys_df = pd.read_sql("SELECT * FROM system_metrics", conn)
                    except Exception:
                        sys_df = pd.DataFrame()
                if not sys_df.empty:
                    sys_metrics = sys_df["metrics"].copy()
                    sys_metrics = pd.DataFrame(
                        sys_metrics.apply(
                            lambda x: deserialize_values(orjson.loads(x))
                        ).values.tolist(),
                        index=sys_df.index,
                    )
                    del sys_df["metrics"]
                    for col in sys_metrics.columns:
                        sys_df[col] = sys_metrics[col]
                    sys_df.to_parquet(
                        system_parquet_path,
                        write_page_index=True,
                        use_content_defined_chunking=True,
                    )

            if (not configs_parquet_path.exists()) or (
                db_path.stat().st_mtime > configs_parquet_path.stat().st_mtime
            ):
                with sqlite3.connect(str(db_path)) as conn:
                    try:
                        configs_df = pd.read_sql("SELECT * FROM configs", conn)
                    except Exception:
                        configs_df = pd.DataFrame()
                if not configs_df.empty:
                    config_data = configs_df["config"].copy()
                    config_data = pd.DataFrame(
                        config_data.apply(
                            lambda x: deserialize_values(orjson.loads(x))
                        ).values.tolist(),
                        index=configs_df.index,
                    )
                    del configs_df["config"]
                    for col in config_data.columns:
                        configs_df[col] = config_data[col]
                    configs_df.to_parquet(
                        configs_parquet_path,
                        write_page_index=True,
                        use_content_defined_chunking=True,
                    )

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
        for pq_name in parquet_names:
            parquet_path = TRACKIO_DIR / pq_name
            db_path = parquet_path.with_suffix(DB_EXT)

            SQLiteStorage._cleanup_wal_sidecars(db_path)

            df = pd.read_parquet(parquet_path)
            if "metrics" not in df.columns:
                metrics = df.copy()
                structural_cols = [
                    "id",
                    "timestamp",
                    "run_name",
                    "step",
                    "log_id",
                    "space_id",
                ]
                df = df[[c for c in structural_cols if c in df.columns]]
                for col in structural_cols:
                    if col in metrics.columns:
                        del metrics[col]
                metrics = orjson.loads(metrics.to_json(orient="records"))
                df["metrics"] = [orjson.dumps(serialize_values(row)) for row in metrics]

            with sqlite3.connect(str(db_path), timeout=30.0) as conn:
                df.to_sql("metrics", conn, if_exists="replace", index=False)
                conn.commit()

        system_parquet_names = [f for f in all_paths if f.endswith("_system.parquet")]
        for pq_name in system_parquet_names:
            parquet_path = TRACKIO_DIR / pq_name
            db_name = pq_name.replace("_system.parquet", DB_EXT)
            db_path = TRACKIO_DIR / db_name

            df = pd.read_parquet(parquet_path)
            if "metrics" not in df.columns:
                metrics = df.copy()
                other_cols = ["id", "timestamp", "run_name"]
                df = df[[c for c in other_cols if c in df.columns]]
                for col in other_cols:
                    if col in metrics.columns:
                        del metrics[col]
                metrics = orjson.loads(metrics.to_json(orient="records"))
                df["metrics"] = [orjson.dumps(serialize_values(row)) for row in metrics]

            with sqlite3.connect(str(db_path), timeout=30.0) as conn:
                df.to_sql("system_metrics", conn, if_exists="replace", index=False)
                conn.commit()

        configs_parquet_names = [f for f in all_paths if f.endswith("_configs.parquet")]
        for pq_name in configs_parquet_names:
            parquet_path = TRACKIO_DIR / pq_name
            db_name = pq_name.replace("_configs.parquet", DB_EXT)
            db_path = TRACKIO_DIR / db_name

            df = pd.read_parquet(parquet_path)
            if "config" not in df.columns:
                config_data = df.copy()
                other_cols = ["id", "run_name", "created_at"]
                df = df[[c for c in other_cols if c in df.columns]]
                for col in other_cols:
                    if col in config_data.columns:
                        del config_data[col]
                config_data = orjson.loads(config_data.to_json(orient="records"))
                df["config"] = [
                    orjson.dumps(serialize_values(row)) for row in config_data
                ]

            with sqlite3.connect(str(db_path), timeout=30.0) as conn:
                df.to_sql("configs", conn, if_exists="replace", index=False)
                conn.commit()

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
            if dataset_id is None or space_repo_name is None:
                scheduler = DummyCommitScheduler()
            else:
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
            SQLiteStorage._current_scheduler = scheduler
            return scheduler

    @staticmethod
    def log(project: str, run: str, metrics: dict, step: int | None = None):
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
                cursor.execute(
                    """
                    SELECT MAX(step) 
                    FROM metrics 
                    WHERE run_name = ?
                    """,
                    (run,),
                )
                last_step = cursor.fetchone()[0]
                current_step = (
                    0
                    if step is None and last_step is None
                    else (step if step is not None else last_step + 1)
                )
                current_timestamp = datetime.now(timezone.utc).isoformat()
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

                if steps is None:
                    steps = list(range(len(metrics_list)))
                elif any(s is None for s in steps):
                    cursor.execute(
                        "SELECT MAX(step) FROM metrics WHERE run_name = ?", (run,)
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
                data = []
                for i, metrics in enumerate(metrics_list):
                    lid = log_ids[i] if log_ids else None
                    data.append(
                        (
                            timestamps[i],
                            run,
                            orjson.dumps(serialize_values(metrics)),
                            lid,
                            space_id,
                        )
                    )

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
    def get_system_logs(project: str, run: str) -> list[dict]:
        """Retrieve system metrics for a specific run. Returns metrics with timestamps (no steps)."""
        db_path = SQLiteStorage.get_project_db_path(project)
        if not db_path.exists():
            return []

        with SQLiteStorage._get_connection(db_path) as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(
                    """
                    SELECT timestamp, metrics
                    FROM system_metrics
                    WHERE run_name = ?
                    ORDER BY timestamp
                    """,
                    (run,),
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
    def get_logs(project: str, run: str) -> list[dict]:
        """Retrieve logs for a specific run. Logs include the step count (int) and the timestamp (datetime object)."""
        db_path = SQLiteStorage.get_project_db_path(project)
        if not db_path.exists():
            return []

        with SQLiteStorage._get_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT timestamp, step, metrics
                FROM metrics
                WHERE run_name = ?
                ORDER BY timestamp
                """,
                (run,),
            )

            rows = cursor.fetchall()
            results = []
            for row in rows:
                metrics = orjson.loads(row["metrics"])
                metrics = deserialize_values(metrics)
                metrics["timestamp"] = row["timestamp"]
                metrics["step"] = row["step"]
                results.append(metrics)
            return results

    @staticmethod
    def load_from_dataset():
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
    def get_projects() -> list[str]:
        """
        Get list of all projects by scanning the database files in the trackio directory.
        """
        if not SQLiteStorage._dataset_import_attempted:
            SQLiteStorage.load_from_dataset()

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
        db_path = SQLiteStorage.get_project_db_path(project)
        if not db_path.exists():
            return []

        with SQLiteStorage._get_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT run_name
                FROM metrics
                GROUP BY run_name
                ORDER BY MIN(timestamp) ASC
                """,
            )
            return [row[0] for row in cursor.fetchall()]

    @staticmethod
    def get_max_steps_for_runs(project: str) -> dict[str, int]:
        """Get the maximum step for each run in a project."""
        db_path = SQLiteStorage.get_project_db_path(project)
        if not db_path.exists():
            return {}

        with SQLiteStorage._get_connection(db_path) as conn:
            cursor = conn.cursor()
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

    @staticmethod
    def get_max_step_for_run(project: str, run: str) -> int | None:
        """Get the maximum step for a specific run, or None if no logs exist."""
        db_path = SQLiteStorage.get_project_db_path(project)
        if not db_path.exists():
            return None

        with SQLiteStorage._get_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT MAX(step) FROM metrics WHERE run_name = ?", (run,))
            result = cursor.fetchone()[0]
            return result

    @staticmethod
    def get_run_config(project: str, run: str) -> dict | None:
        """Get configuration for a specific run."""
        db_path = SQLiteStorage.get_project_db_path(project)
        if not db_path.exists():
            return None

        with SQLiteStorage._get_connection(db_path) as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(
                    """
                    SELECT config FROM configs WHERE run_name = ?
                    """,
                    (run,),
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
    def delete_run(project: str, run: str) -> bool:
        """Delete a run from the database (metrics, config, and system_metrics)."""
        db_path = SQLiteStorage.get_project_db_path(project)
        if not db_path.exists():
            return False

        with SQLiteStorage._get_process_lock(project):
            with SQLiteStorage._get_connection(db_path) as conn:
                cursor = conn.cursor()
                try:
                    cursor.execute("DELETE FROM metrics WHERE run_name = ?", (run,))
                    cursor.execute("DELETE FROM configs WHERE run_name = ?", (run,))
                    try:
                        cursor.execute(
                            "DELETE FROM system_metrics WHERE run_name = ?", (run,)
                        )
                    except sqlite3.OperationalError:
                        pass
                    conn.commit()
                    return True
                except sqlite3.Error:
                    return False

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

                    if not metrics_rows and not config_row and not system_metrics_rows:
                        return False

                    with SQLiteStorage._get_connection(target_db_path) as target_conn:
                        target_cursor = target_conn.cursor()

                        def update_media_paths(obj, old_prefix, new_prefix):
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
                                            new_path = normalized_path.replace(
                                                old_prefix, new_prefix, 1
                                            )
                                            return {**obj, "file_path": new_path}
                                return {
                                    key: update_media_paths(
                                        value, old_prefix, new_prefix
                                    )
                                    for key, value in obj.items()
                                }
                            elif isinstance(obj, list):
                                return [
                                    update_media_paths(item, old_prefix, new_prefix)
                                    for item in obj
                                ]
                            return obj

                        updated_metrics_rows = []
                        old_prefix = f"{project}/{run}/"
                        new_prefix = f"{new_project}/{run}/"

                        for row in metrics_rows:
                            metrics_data = orjson.loads(row["metrics"])
                            metrics_deserialized = deserialize_values(metrics_data)
                            updated_metrics = update_media_paths(
                                metrics_deserialized, old_prefix, new_prefix
                            )

                            updated_metrics_rows.append(
                                (
                                    row["timestamp"],
                                    run,
                                    row["step"],
                                    orjson.dumps(serialize_values(updated_metrics)),
                                )
                            )

                        for row_data in updated_metrics_rows:
                            target_cursor.execute(
                                """
                                INSERT INTO metrics (timestamp, run_name, step, metrics)
                                VALUES (?, ?, ?, ?)
                                """,
                                row_data,
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

                        target_conn.commit()

                        source_media_dir = MEDIA_DIR / project / run
                        target_media_dir = MEDIA_DIR / new_project / run

                        if source_media_dir.exists():
                            target_media_dir.parent.mkdir(parents=True, exist_ok=True)
                            if target_media_dir.exists():
                                shutil.rmtree(target_media_dir)
                            shutil.move(str(source_media_dir), str(target_media_dir))

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
    def get_metric_values(project: str, run: str, metric_name: str) -> list[dict]:
        """Get all values for a specific metric in a project/run."""
        db_path = SQLiteStorage.get_project_db_path(project)
        if not db_path.exists():
            return []

        with SQLiteStorage._get_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT timestamp, step, metrics
                FROM metrics
                WHERE run_name = ?
                ORDER BY timestamp
                """,
                (run,),
            )

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
                cursor.execute(
                    f"""SELECT id, timestamp, run_name, {extra_cols}metrics, log_id, space_id
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
                    "metrics": metrics,
                    "timestamp": row["timestamp"],
                    "log_id": row["log_id"],
                }
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
                    f"DELETE FROM {table} WHERE id IN ({placeholders})",
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
                cursor.execute(
                    """SELECT id, space_id, run_name, step, file_path, relative_path
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
        run_name: str | None,
        step: int | None,
        file_path: str,
        relative_path: str | None,
    ) -> None:
        db_path = SQLiteStorage.init_db(project)
        with SQLiteStorage._get_process_lock(project):
            with SQLiteStorage._get_connection(db_path) as conn:
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
                cursor.execute(
                    f"""SELECT timestamp, run_name, {extra_cols}metrics, log_id
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
                    "metrics": metrics,
                    "timestamp": row["timestamp"],
                    "log_id": row["log_id"],
                }
                for field in extra_fields or []:
                    entry[field] = row[field]
                if include_config:
                    entry["config"] = None
                results.append(entry)
            return results
