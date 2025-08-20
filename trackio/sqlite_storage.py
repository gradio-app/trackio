import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from threading import Lock

import huggingface_hub as hf
import pandas as pd

try:  # absolute imports when installed
    from trackio.commit_scheduler import CommitScheduler
    from trackio.dummy_commit_scheduler import DummyCommitScheduler
    from trackio.utils import TRACKIO_DIR
except Exception:  # relative imports for local execution on Spaces
    from commit_scheduler import CommitScheduler
    from dummy_commit_scheduler import DummyCommitScheduler
    from utils import TRACKIO_DIR


class SQLiteStorage:
    _dataset_import_attempted = False
    _current_scheduler: CommitScheduler | DummyCommitScheduler | None = None
    _scheduler_lock = Lock()

    @staticmethod
    def _get_connection(db_path: Path) -> sqlite3.Connection:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def get_project_db_filename(project: str) -> Path:
        """Get the database filename for a specific project."""
        safe_project_name = "".join(
            c for c in project if c.isalnum() or c in ("-", "_")
        ).rstrip()
        if not safe_project_name:
            safe_project_name = "default"
        return f"{safe_project_name}.db"

    @staticmethod
    def get_project_db_path(project: str) -> Path:
        """Get the database path for a specific project."""
        filename = SQLiteStorage.get_project_db_filename(project)
        return TRACKIO_DIR / filename

    @staticmethod
    def init_db(project: str) -> Path:
        """
        Initialize the SQLite database with required tables.
        If there is a dataset ID provided, copies from that dataset instead.
        Returns the database path.
        """
        db_path = SQLiteStorage.get_project_db_path(project)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        with SQLiteStorage.get_scheduler().lock:
            with sqlite3.connect(db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS metrics (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp TEXT NOT NULL,
                        run_name TEXT NOT NULL,
                        step INTEGER NOT NULL,
                        metrics TEXT NOT NULL
                    )
                """)
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_metrics_run_step
                    ON metrics(run_name, step)
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
        all_paths = os.listdir(TRACKIO_DIR)
        db_paths = [f for f in all_paths if f.endswith(".db")]
        for db_path in db_paths:
            db_path = TRACKIO_DIR / db_path
            parquet_path = db_path.with_suffix(".parquet")
            if (not parquet_path.exists()) or (
                db_path.stat().st_mtime > parquet_path.stat().st_mtime
            ):
                with sqlite3.connect(db_path) as conn:
                    df = pd.read_sql("SELECT * from metrics", conn)
                # break out the single JSON metrics column into individual columns
                metrics = df["metrics"].copy()
                metrics = pd.DataFrame(
                    metrics.apply(json.loads).values.tolist(), index=df.index
                )
                del df["metrics"]
                for col in metrics.columns:
                    df[col] = metrics[col]
                df.to_parquet(parquet_path)

    @staticmethod
    def import_from_parquet():
        """
        Imports to all DB files that have matching files under the same path but with extension ".parquet".
        """
        all_paths = os.listdir(TRACKIO_DIR)
        parquet_paths = [f for f in all_paths if f.endswith(".parquet")]
        for parquet_path in parquet_paths:
            parquet_path = TRACKIO_DIR / parquet_path
            db_path = parquet_path.with_suffix(".db")
            df = pd.read_parquet(parquet_path)
            with sqlite3.connect(db_path) as conn:
                # fix up df to have a single JSON metrics column
                if "metrics" not in df.columns:
                    # separate other columns from metrics
                    metrics = df.copy()
                    other_cols = ["id", "timestamp", "run_name", "step"]
                    df = df[other_cols]
                    for col in other_cols:
                        del metrics[col]
                    # combine them all into a single metrics col
                    metrics = json.loads(metrics.to_json(orient="records"))
                    df["metrics"] = [json.dumps(row) for row in metrics]
                df.to_sql("metrics", conn, if_exists="replace", index=False)

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
        and is set up with the correct tables. It also uses the scheduler to lock the database so
        that there is no race condition when logging / syncing to the Hugging Face Dataset.
        """
        db_path = SQLiteStorage.init_db(project)

        with SQLiteStorage.get_scheduler().lock:
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
                if step is None:
                    current_step = 0 if last_step is None else last_step + 1
                else:
                    current_step = step

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
                        json.dumps(metrics),
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
    ):
        """Bulk log metrics to the database with specified steps and timestamps."""
        if not metrics_list:
            return

        if timestamps is None:
            timestamps = [datetime.now().isoformat()] * len(metrics_list)

        db_path = SQLiteStorage.init_db(project)
        with SQLiteStorage.get_scheduler().lock:
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
                            json.dumps(metrics),
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
                metrics = json.loads(row["metrics"])
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

        for db_file in TRACKIO_DIR.glob("*.db"):
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
    def get_max_steps_for_runs(project: str, runs: list[str]) -> dict[str, int]:
        """Efficiently get the maximum step for multiple runs in a single query."""
        db_path = SQLiteStorage.get_project_db_path(project)
        if not db_path.exists():
            return {run: 0 for run in runs}

        with SQLiteStorage._get_connection(db_path) as conn:
            cursor = conn.cursor()
            placeholders = ",".join("?" * len(runs))
            cursor.execute(
                f"""
                SELECT run_name, MAX(step) as max_step
                FROM metrics
                WHERE run_name IN ({placeholders})
                GROUP BY run_name
                """,
                runs,
            )

            results = {run: 0 for run in runs}  # Default to 0 for runs with no data
            for row in cursor.fetchall():
                results[row["run_name"]] = row["max_step"]

            return results

    def finish(self):
        """Cleanup when run is finished."""
        pass
