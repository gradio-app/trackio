import os
import platform
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from threading import Lock

try:
    import fcntl
except ImportError:  # fcntl is not available on Windows
    fcntl = None

import huggingface_hub as hf
import orjson
import pandas as pd

try:  # absolute imports when installed from PyPI
    from trackio.commit_scheduler import CommitScheduler
    from trackio.dummy_commit_scheduler import DummyCommitScheduler
    from trackio.utils import (
        TRACKIO_DIR,
        deserialize_values,
        serialize_values,
    )
except ImportError:  # relative imports when installed from source on Spaces
    from commit_scheduler import CommitScheduler
    from dummy_commit_scheduler import DummyCommitScheduler
    from utils import TRACKIO_DIR, deserialize_values, serialize_values

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
                conn.commit()
        return db_path

    @staticmethod
    def export_to_parquet():
        """
        Exports all projects' DB files as Parquet under the same path but with extension ".parquet".
        """
        # don't attempt to export (potentially wrong/blank) data before importing for the first time
        if not SQLiteStorage._dataset_import_attempted:
            return
        if not TRACKIO_DIR.exists():
            return

        all_paths = os.listdir(TRACKIO_DIR)
        db_names = [f for f in all_paths if f.endswith(DB_EXT)]
        for db_name in db_names:
            db_path = TRACKIO_DIR / db_name
            parquet_path = db_path.with_suffix(".parquet")
            if (not parquet_path.exists()) or (
                db_path.stat().st_mtime > parquet_path.stat().st_mtime
            ):
                with sqlite3.connect(str(db_path)) as conn:
                    df = pd.read_sql("SELECT * FROM metrics", conn)
                # break out the single JSON metrics column into individual columns
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

                df.to_parquet(parquet_path)

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
        """
        if not TRACKIO_DIR.exists():
            return

        all_paths = os.listdir(TRACKIO_DIR)
        parquet_names = [f for f in all_paths if f.endswith(".parquet")]
        for pq_name in parquet_names:
            parquet_path = TRACKIO_DIR / pq_name
            db_path = parquet_path.with_suffix(DB_EXT)

            SQLiteStorage._cleanup_wal_sidecars(db_path)

            df = pd.read_parquet(parquet_path)
            # fix up df to have a single JSON metrics column
            if "metrics" not in df.columns:
                # separate other columns from metrics
                metrics = df.copy()
                other_cols = ["id", "timestamp", "run_name", "step"]
                df = df[other_cols]
                for col in other_cols:
                    del metrics[col]
                # combine them all into a single metrics col
                metrics = orjson.loads(metrics.to_json(orient="records"))
                df["metrics"] = [orjson.dumps(serialize_values(row)) for row in metrics]

            with sqlite3.connect(str(db_path), timeout=30.0) as conn:
                df.to_sql("metrics", conn, if_exists="replace", index=False)
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
                    allow_patterns=["*.parquet", "media/**/*"],
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
                current_timestamp = datetime.now().isoformat()
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
    ):
        """
        Safely log bulk metrics to the database. Before logging, this method will ensure the database exists
        and is set up with the correct tables. It also uses a cross-process lock to prevent
        database locking errors when multiple processes access the same database.
        """
        if not metrics_list:
            return

        if timestamps is None:
            timestamps = [datetime.now().isoformat()] * len(metrics_list)

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
                    data.append(
                        (
                            timestamps[i],
                            run,
                            steps[i],
                            orjson.dumps(serialize_values(metrics)),
                        )
                    )

                cursor.executemany(
                    """
                    INSERT INTO metrics
                    (timestamp, run_name, step, metrics)
                    VALUES (?, ?, ?, ?)
                    """,
                    data,
                )

                if config:
                    current_timestamp = datetime.now().isoformat()
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
        """Get list of all runs for a project."""
        db_path = SQLiteStorage.get_project_db_path(project)
        if not db_path.exists():
            return []

        with SQLiteStorage._get_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT DISTINCT run_name FROM metrics",
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
    def store_config(project: str, run: str, config: dict) -> None:
        """Store configuration for a run."""
        db_path = SQLiteStorage.init_db(project)

        with SQLiteStorage._get_process_lock(project):
            with SQLiteStorage._get_connection(db_path) as conn:
                cursor = conn.cursor()
                current_timestamp = datetime.now().isoformat()

                cursor.execute(
                    """
                    INSERT OR REPLACE INTO configs
                    (run_name, config, created_at)
                    VALUES (?, ?, ?)
                    """,
                    (run, orjson.dumps(serialize_values(config)), current_timestamp),
                )
                conn.commit()

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
        """Delete a run from the database (both metrics and config)."""
        db_path = SQLiteStorage.get_project_db_path(project)
        if not db_path.exists():
            return False

        with SQLiteStorage._get_process_lock(project):
            with SQLiteStorage._get_connection(db_path) as conn:
                cursor = conn.cursor()
                try:
                    cursor.execute("DELETE FROM metrics WHERE run_name = ?", (run,))
                    cursor.execute("DELETE FROM configs WHERE run_name = ?", (run,))
                    conn.commit()
                    return True
                except sqlite3.Error:
                    return False

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
        db_path = SQLiteStorage.get_project_db_path(project)
        if not db_path.exists():
            return []

        with SQLiteStorage._get_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT metrics
                FROM metrics
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
                    if key not in ["timestamp", "step"]:
                        all_metrics.add(key)
            return sorted(list(all_metrics))

    def finish(self):
        """Cleanup when run is finished."""
        pass
