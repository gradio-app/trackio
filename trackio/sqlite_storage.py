import glob
import json
import os
import sqlite3
from datetime import datetime

from huggingface_hub import CommitScheduler

try:
    from trackio.dummy_commit_scheduler import DummyCommitScheduler
    from trackio.utils import TRACKIO_DIR
except:  # noqa: E722
    from dummy_commit_scheduler import DummyCommitScheduler
    from utils import TRACKIO_DIR


class SQLiteStorage:
    def __init__(self, project: str, name: str, config: dict):
        """
        Basic constructor for the SQLiteStorage class. This
        will create a new database file for the project if it doesn't exist.
        """
        self.project = project
        self.name = name
        self.config = config
        self.db_path = self._get_project_db_path(project)
        os.makedirs(TRACKIO_DIR, exist_ok=True)
        self._init_db()
        self._save_config()

    @staticmethod
    def _get_project_db_path(project: str) -> str:
        """Get the database path for a specific project."""
        safe_project_name = "".join(
            c for c in project if c.isalnum() or c in ("-", "_")
        ).rstrip()
        if not safe_project_name:
            safe_project_name = "default"
        return os.path.join(TRACKIO_DIR, f"{safe_project_name}.db")

    @staticmethod
    def _get_scheduler() -> CommitScheduler | DummyCommitScheduler:
        """
        Get the scheduler for the database based on the environment variables.
        This applies to both local and Spaces.
        """
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
        return scheduler

    def _init_db(self):
        """Initialize the SQLite database with required tables."""
        with self._get_scheduler().lock:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()

                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS metrics (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp TEXT NOT NULL,
                        project_name TEXT NOT NULL,
                        run_name TEXT NOT NULL,
                        step INTEGER NOT NULL,
                        metrics TEXT NOT NULL
                    )
                """)

                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS configs (
                        project_name TEXT NOT NULL,
                        run_name TEXT NOT NULL,
                        config TEXT NOT NULL,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        PRIMARY KEY (project_name, run_name)
                    )
                """)

                conn.commit()

    def _save_config(self):
        """Save the run configuration to the database."""
        with self._get_scheduler().lock:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT OR REPLACE INTO configs (project_name, run_name, config) VALUES (?, ?, ?)",
                    (self.project, self.name, json.dumps(self.config)),
                )
                conn.commit()

    def log(self, metrics: dict):
        """Log metrics to the database."""
        with self._get_scheduler().lock:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()

                cursor.execute(
                    """
                    SELECT MAX(step) 
                    FROM metrics 
                    WHERE project_name = ? AND run_name = ?
                    """,
                    (self.project, self.name),
                )
                last_step = cursor.fetchone()[0]
                current_step = 0 if last_step is None else last_step + 1

                current_timestamp = datetime.now().isoformat()

                cursor.execute(
                    """
                    INSERT INTO metrics 
                    (timestamp, project_name, run_name, step, metrics)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        current_timestamp,
                        self.project,
                        self.name,
                        current_step,
                        json.dumps(metrics),
                    ),
                )
                conn.commit()

    def bulk_log(
        self,
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

        with self._get_scheduler().lock:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()

                data = []
                for i, metrics in enumerate(metrics_list):
                    data.append(
                        (
                            timestamps[i],
                            self.project,
                            self.name,
                            steps[i],
                            json.dumps(metrics),
                        )
                    )

                cursor.executemany(
                    """
                    INSERT INTO metrics 
                    (timestamp, project_name, run_name, step, metrics)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    data,
                )
                conn.commit()

    @staticmethod
    def get_metrics(project: str, run: str) -> list[dict]:
        """Retrieve metrics for a specific run. The metrics also include the step count (int) and the timestamp (datetime object)."""
        db_path = SQLiteStorage._get_project_db_path(project)
        if not os.path.exists(db_path):
            return []

        with sqlite3.connect(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT timestamp, step, metrics
                FROM metrics
                WHERE project_name = ? AND run_name = ?
                ORDER BY timestamp
                """,
                (project, run),
            )
            rows = cursor.fetchall()

            results = []
            for row in rows:
                timestamp, step, metrics_json = row
                metrics = json.loads(metrics_json)
                metrics["timestamp"] = timestamp
                metrics["step"] = step
                results.append(metrics)
            return results

    @staticmethod
    def get_projects() -> list[str]:
        """Get list of all projects by scanning database files."""
        projects = []
        if not os.path.exists(TRACKIO_DIR):
            return projects

        db_files = glob.glob(os.path.join(TRACKIO_DIR, "*.db"))

        for db_file in db_files:
            try:
                with sqlite3.connect(db_file) as conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' AND name='metrics'"
                    )
                    if cursor.fetchone():
                        cursor.execute("SELECT DISTINCT project_name FROM metrics")
                        project_names = [row[0] for row in cursor.fetchall()]
                        projects.extend(project_names)
            except sqlite3.Error:
                continue

        return list(set(projects))

    @staticmethod
    def get_runs(project: str) -> list[str]:
        """Get list of all runs for a project."""
        db_path = SQLiteStorage._get_project_db_path(project)
        if not os.path.exists(db_path):
            return []

        with sqlite3.connect(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT DISTINCT run_name FROM metrics WHERE project_name = ?",
                (project,),
            )
            return [row[0] for row in cursor.fetchall()]

    def finish(self):
        """Cleanup when run is finished."""
        pass
