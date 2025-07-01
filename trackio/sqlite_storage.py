import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path

from huggingface_hub import CommitScheduler

try:  # absolute imports when installed
    from trackio.context_vars import current_scheduler
    from trackio.dummy_commit_scheduler import DummyCommitScheduler
    from trackio.utils import TRACKIO_DIR
except Exception:  # relative imports for local execution on Spaces
    from context_vars import current_scheduler
    from dummy_commit_scheduler import DummyCommitScheduler
    from utils import TRACKIO_DIR


class SQLiteStorage:
    _last_step_cache: dict[tuple[str, str], int] = {}
    _metrics_cache: dict[tuple[str, str], list[dict]] = {}

    @staticmethod
    def _get_connection(db_path: Path) -> sqlite3.Connection:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def get_project_db_path(project: str) -> Path:
        """Get the database path for a specific project."""
        safe_project_name = "".join(
            c for c in project if c.isalnum() or c in ("-", "_")
        ).rstrip()
        if not safe_project_name:
            safe_project_name = "default"
        return TRACKIO_DIR / f"{safe_project_name}.db"

    @staticmethod
    def init_db(project: str) -> str:
        """
        Initialize the SQLite database with required tables.
        Returns the database path.
        """
        db_path = SQLiteStorage.get_project_db_path(project)
        if not db_path.exists():
            SQLiteStorage._last_step_cache.clear()
            SQLiteStorage._metrics_cache.clear()
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
    def get_scheduler():
        """
        Get the scheduler for the database based on the environment variables.
        This applies to both local and Spaces.
        """
        if current_scheduler.get() is not None:
            return current_scheduler.get()
        hf_token = os.environ.get("HF_TOKEN")
        dataset_id = os.environ.get("TRACKIO_DATASET_ID")
        if dataset_id is None:
            scheduler = DummyCommitScheduler()
        else:
            scheduler = CommitScheduler(
                repo_id=dataset_id,
                repo_type="dataset",
                folder_path=TRACKIO_DIR,
                private=True,
                squash_history=True,
                token=hf_token,
            )
        current_scheduler.set(scheduler)
        return scheduler

    @staticmethod
    def log(project: str, run: str, metrics: dict):
        """
        Safely log metrics to the database. Before logging, this method will ensure the database exists
        and is set up with the correct tables. It also uses the scheduler to lock the database so
        that there is no race condition when logging / syncing to the Hugging Face Dataset.
        """
        db_path = SQLiteStorage.init_db(project)

        with SQLiteStorage.get_scheduler().lock:
            with SQLiteStorage._get_connection(db_path) as conn:
                cursor = conn.cursor()

                key = (project, run)
                if key not in SQLiteStorage._last_step_cache:
                    cursor.execute(
                        "SELECT MAX(step) FROM metrics WHERE run_name = ?",
                        (run,),
                    )
                    last = cursor.fetchone()[0]
                    SQLiteStorage._last_step_cache[key] = -1 if last is None else last

                current_step = SQLiteStorage._last_step_cache[key] + 1
                SQLiteStorage._last_step_cache[key] = current_step

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

        if steps is None:
            steps = list(range(len(metrics_list)))

        if timestamps is None:
            timestamps = [datetime.now().isoformat()] * len(metrics_list)

        if len(metrics_list) != len(steps) or len(metrics_list) != len(timestamps):
            raise ValueError(
                "metrics_list, steps, and timestamps must have the same length"
            )

        db_path = SQLiteStorage.init_db(project)
        with SQLiteStorage.get_scheduler().lock:
            with SQLiteStorage._get_connection(db_path) as conn:
                cursor = conn.cursor()

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

                key = (project, run)
                if data:
                    SQLiteStorage._last_step_cache[key] = data[-1][2]

    @staticmethod
    def get_metrics(project: str, run: str) -> list[dict]:
        """Retrieve metrics for a specific run. The metrics also include the step count (int) and the timestamp (datetime object)."""
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
            key = (project, run)
            last_cached = SQLiteStorage._metrics_cache.get(key, [])
            last_step = last_cached[-1]["step"] if last_cached else -1

            cursor.execute(
                "SELECT timestamp, step, metrics FROM metrics WHERE run_name = ? AND step > ? ORDER BY step",
                (run, last_step),
            )
            new_rows = cursor.fetchall()

            for row in new_rows:
                timestamp = row["timestamp"]
                step = row["step"]
                metrics = json.loads(row["metrics"])
                metrics["timestamp"] = timestamp
                metrics["step"] = step
                last_cached.append(metrics)

            SQLiteStorage._metrics_cache[key] = last_cached
            return list(last_cached)

    @staticmethod
    def get_projects() -> list[str]:
        """
        Get list of all projects by scanning the database files in the trackio directory.
        """
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

    def finish(self):
        """Cleanup when run is finished."""
        pass
