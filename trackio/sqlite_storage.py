import glob
import json
import os
import sqlite3
from datetime import datetime

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
    def _get_connection(db_path: str) -> sqlite3.Connection:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def get_last_step(project: str, run: str) -> int:
        db_path = SQLiteStorage.get_project_db_path(project)
        if not os.path.exists(db_path):
            return -1
        with SQLiteStorage._get_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT MAX(step) FROM metrics WHERE project_name = ? AND run_name = ?",
                (project, run),
            )
            val = cursor.fetchone()[0]
            return -1 if val is None else int(val)

    @staticmethod
    def _update_project_index(project: str | None) -> None:
        os.makedirs(os.path.dirname(PROJECTS_INDEX_PATH), exist_ok=True)
        try:
            if os.path.exists(PROJECTS_INDEX_PATH):
                with open(PROJECTS_INDEX_PATH, "r") as f:
                    data = set(json.load(f))
            else:
                data = set()
            if project is not None and project not in data:
                data.add(project)
                with open(PROJECTS_INDEX_PATH, "w") as f:
                    json.dump(sorted(data), f)
        except Exception:
            pass

    @staticmethod
    def get_project_db_path(project: str) -> str:
        """Get the database path for a specific project."""
        safe_project_name = "".join(
            c for c in project if c.isalnum() or c in ("-", "_")
        ).rstrip()
        if not safe_project_name:
            safe_project_name = "default"
        return os.path.join(TRACKIO_DIR, f"{safe_project_name}.db")

    @staticmethod
    def init_db(project: str) -> str:
        """
        Initialize the SQLite database with required tables.
        Returns the database path.
        """
        db_path = SQLiteStorage.get_project_db_path(project)
        if not os.path.exists(db_path):
            SQLiteStorage._last_step_cache.clear()
            SQLiteStorage._metrics_cache.clear()
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        with SQLiteStorage.get_scheduler().lock:
            with sqlite3.connect(db_path) as conn:
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
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_metrics_proj_run_step
                    ON metrics(project_name, run_name, step)
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_metrics_project
                    ON metrics(project_name)
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
                        "SELECT MAX(step) FROM metrics WHERE project_name = ? AND run_name = ?",
                        key,
                    )
                    last = cursor.fetchone()[0]
                    SQLiteStorage._last_step_cache[key] = -1 if last is None else last

                current_step = SQLiteStorage._last_step_cache[key] + 1
                SQLiteStorage._last_step_cache[key] = current_step

                current_timestamp = datetime.now().isoformat()

                cursor.execute(
                    """
                    INSERT INTO metrics
                    (timestamp, project_name, run_name, step, metrics)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        current_timestamp,
                        project,
                        run,
                        current_step,
                        json.dumps(metrics),
                    ),
                )
                conn.commit()
        SQLiteStorage._update_project_index(project)

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
                            project,
                            run,
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

                key = (project, run)
                if data:
                    SQLiteStorage._last_step_cache[key] = data[-1][3]
        SQLiteStorage._update_project_index(project)

    @staticmethod
    def get_metrics(project: str, run: str) -> list[dict]:
        """Retrieve metrics for a specific run. The metrics also include the step count (int) and the timestamp (datetime object)."""
        db_path = SQLiteStorage.get_project_db_path(project)
        if not os.path.exists(db_path):
            return []

        with SQLiteStorage._get_connection(db_path) as conn:
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
            key = (project, run)
            last_cached = SQLiteStorage._metrics_cache.get(key, [])
            last_step = last_cached[-1]["step"] if last_cached else -1

            cursor.execute(
                "SELECT timestamp, step, metrics FROM metrics WHERE project_name = ? AND run_name = ? AND step > ? ORDER BY step",
                (project, run, last_step),
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
        """Get list of all projects."""
        projects: set[str] = set()
        if not os.path.exists(TRACKIO_DIR):
            return []

        for db_file in glob.glob(os.path.join(TRACKIO_DIR, "*.db")):
            try:
                with SQLiteStorage._get_connection(db_file) as conn:
                    for row in conn.execute(
                        "SELECT DISTINCT project_name FROM metrics"
                    ):
                        projects.add(row[0])
            except sqlite3.Error:
                continue

        if projects:
            try:
                with open(PROJECTS_INDEX_PATH, "w") as f:
                    json.dump(sorted(projects), f)
            except Exception:
                pass
        return sorted(projects)

    @staticmethod
    def get_runs(project: str) -> list[str]:
        """Get list of all runs for a project."""
        db_path = SQLiteStorage.get_project_db_path(project)
        if not os.path.exists(db_path):
            return []

        with SQLiteStorage._get_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT DISTINCT run_name FROM metrics WHERE project_name = ?",
                (project,),
            )
            return [row[0] for row in cursor.fetchall()]

    def finish(self):
        """Cleanup when run is finished."""
        pass
