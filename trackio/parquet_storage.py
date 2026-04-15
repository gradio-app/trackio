import json as json_mod
import os
import shutil
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock

try:
    import fcntl
except ImportError:
    fcntl = None

try:
    import msvcrt as _msvcrt
except ImportError:
    _msvcrt = None

import orjson
import pandas as pd

from trackio.dummy_commit_scheduler import DummyCommitScheduler
from trackio.utils import (
    deserialize_values,
    get_color_palette,
    serialize_values,
)
import trackio.utils as utils

PROJECT_EXT = ".trackio"
DB_EXT = PROJECT_EXT
RUNS_FILE = "runs.parquet"
CONFIGS_FILE = "configs.parquet"
PROJECT_METADATA_FILE = "project_metadata.parquet"
PENDING_LOGS_FILE = "pending_logs.parquet"
PENDING_SYSTEM_FILE = "pending_system.parquet"
PENDING_UPLOADS_FILE = "pending_uploads.parquet"
TRACKIO_DIR = utils.TRACKIO_DIR
MEDIA_DIR = utils.MEDIA_DIR


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_project_name(project: str) -> str:
    safe_project_name = "".join(
        c for c in project if c.isalnum() or c in ("-", "_")
    ).rstrip()
    if not safe_project_name:
        safe_project_name = "default"
    return safe_project_name


def _metrics_to_json(metrics: dict) -> str:
    return orjson.dumps(serialize_values(metrics)).decode("utf-8")


def _json_to_metrics(value: str | bytes) -> dict:
    return deserialize_values(orjson.loads(value))


def _empty_df(columns: list[str]) -> pd.DataFrame:
    return pd.DataFrame(columns=columns)


class ProcessLock:
    """A file-based lock that works across processes using fcntl (Unix) or msvcrt (Windows)."""

    def __init__(self, lockfile_path: Path):
        self.lockfile_path = lockfile_path
        self.lockfile = None

    def __enter__(self):
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
                    raise IOError("Could not acquire storage lock after 10 seconds")

    def __exit__(self, exc_type, exc_val, exc_tb):
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
    """Parquet-backed storage engine exposed through the legacy SQLiteStorage name."""

    _dataset_import_attempted = False
    _current_scheduler = None
    _scheduler_lock = Lock()

    @staticmethod
    def storage_backend() -> str:
        return "parquet"

    @staticmethod
    def get_project_db_filename(project: str) -> str:
        return f"{_safe_project_name(project)}{PROJECT_EXT}"

    @staticmethod
    def get_project_db_path(project: str) -> Path:
        return utils.TRACKIO_DIR / SQLiteStorage.get_project_db_filename(project)

    @staticmethod
    def get_project_root(project: str) -> Path:
        return SQLiteStorage.get_project_db_path(project)

    @staticmethod
    def _data_dir(project: str, kind: str) -> Path:
        return SQLiteStorage.get_project_root(project) / kind

    @staticmethod
    def _meta_path(project: str, filename: str) -> Path:
        return SQLiteStorage.get_project_root(project) / filename

    @staticmethod
    def _part_file(project: str, kind: str) -> Path:
        base = SQLiteStorage._data_dir(project, kind)
        base.mkdir(parents=True, exist_ok=True)
        return base / f"{int(time.time() * 1000)}-{uuid.uuid4().hex}.parquet"

    @staticmethod
    def _read_df(path: Path, columns: list[str]) -> pd.DataFrame:
        if not path.exists():
            return _empty_df(columns)
        try:
            df = pd.read_parquet(path)
            for column in columns:
                if column not in df.columns:
                    df[column] = None
            return df[columns]
        except Exception:
            return _empty_df(columns)

    @staticmethod
    def _write_df(path: Path, df: pd.DataFrame) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_name(f"{path.name}.tmp-{uuid.uuid4().hex}")
        df.to_parquet(tmp_path, index=False)
        tmp_path.replace(path)

    @staticmethod
    def _append_part(project: str, kind: str, df: pd.DataFrame) -> None:
        if df.empty:
            return
        out = SQLiteStorage._part_file(project, kind)
        df.to_parquet(out, index=False)

    @staticmethod
    def _read_parts(project: str, kind: str, columns: list[str]) -> pd.DataFrame:
        part_dir = SQLiteStorage._data_dir(project, kind)
        if not part_dir.exists():
            return _empty_df(columns)
        paths = sorted(part_dir.glob("*.parquet"))
        if not paths:
            return _empty_df(columns)
        dfs = []
        for path in paths:
            try:
                df = pd.read_parquet(path)
            except Exception:
                continue
            for column in columns:
                if column not in df.columns:
                    df[column] = None
            dfs.append(df[columns])
        if not dfs:
            return _empty_df(columns)
        return pd.concat(dfs, ignore_index=True)

    @staticmethod
    def _runs_columns() -> list[str]:
        return ["run_id", "run_name", "created_at", "storage_key"]

    @staticmethod
    def _configs_columns() -> list[str]:
        return ["run_id", "config", "created_at"]

    @staticmethod
    def _project_meta_columns() -> list[str]:
        return ["key", "value", "updated_at"]

    @staticmethod
    def _pending_log_columns() -> list[str]:
        return [
            "id",
            "project",
            "run",
            "timestamp",
            "step",
            "metrics",
            "log_id",
            "config",
            "space_id",
        ]

    @staticmethod
    def _pending_system_columns() -> list[str]:
        return [
            "id",
            "project",
            "run",
            "timestamp",
            "metrics",
            "log_id",
            "space_id",
        ]

    @staticmethod
    def _pending_upload_columns() -> list[str]:
        return [
            "id",
            "space_id",
            "run_name",
            "step",
            "file_path",
            "relative_path",
            "created_at",
        ]

    @staticmethod
    def _metrics_columns() -> list[str]:
        return ["run_id", "timestamp", "step", "metrics", "log_id"]

    @staticmethod
    def _system_columns() -> list[str]:
        return ["run_id", "timestamp", "metrics", "log_id"]

    @staticmethod
    def _alerts_columns() -> list[str]:
        return ["run_id", "timestamp", "title", "text", "level", "step", "alert_id"]

    @staticmethod
    @contextmanager
    def _get_connection(
        db_path: Path,
        *,
        timeout: float = 30.0,
        configure_pragmas: bool = True,
        row_factory=None,
    ) -> Iterator[None]:
        # Compatibility shim for callers/tests that still expect a context manager.
        yield None

    @staticmethod
    def _get_process_lock(project: str) -> ProcessLock:
        return ProcessLock(utils.TRACKIO_DIR / f"{_safe_project_name(project)}.lock")

    @staticmethod
    def _read_runs(project: str) -> pd.DataFrame:
        return SQLiteStorage._read_df(
            SQLiteStorage._meta_path(project, RUNS_FILE),
            SQLiteStorage._runs_columns(),
        )

    @staticmethod
    def _write_runs(project: str, df: pd.DataFrame) -> None:
        SQLiteStorage._write_df(SQLiteStorage._meta_path(project, RUNS_FILE), df)

    @staticmethod
    def _read_configs(project: str) -> pd.DataFrame:
        return SQLiteStorage._read_df(
            SQLiteStorage._meta_path(project, CONFIGS_FILE),
            SQLiteStorage._configs_columns(),
        )

    @staticmethod
    def _write_configs(project: str, df: pd.DataFrame) -> None:
        SQLiteStorage._write_df(SQLiteStorage._meta_path(project, CONFIGS_FILE), df)

    @staticmethod
    def _read_project_metadata_df(project: str) -> pd.DataFrame:
        return SQLiteStorage._read_df(
            SQLiteStorage._meta_path(project, PROJECT_METADATA_FILE),
            SQLiteStorage._project_meta_columns(),
        )

    @staticmethod
    def _write_project_metadata_df(project: str, df: pd.DataFrame) -> None:
        SQLiteStorage._write_df(
            SQLiteStorage._meta_path(project, PROJECT_METADATA_FILE), df
        )

    @staticmethod
    def _read_pending_logs_df(project: str) -> pd.DataFrame:
        return SQLiteStorage._read_df(
            SQLiteStorage._meta_path(project, PENDING_LOGS_FILE),
            SQLiteStorage._pending_log_columns(),
        )

    @staticmethod
    def _write_pending_logs_df(project: str, df: pd.DataFrame) -> None:
        SQLiteStorage._write_df(
            SQLiteStorage._meta_path(project, PENDING_LOGS_FILE), df
        )

    @staticmethod
    def _read_pending_system_df(project: str) -> pd.DataFrame:
        return SQLiteStorage._read_df(
            SQLiteStorage._meta_path(project, PENDING_SYSTEM_FILE),
            SQLiteStorage._pending_system_columns(),
        )

    @staticmethod
    def _write_pending_system_df(project: str, df: pd.DataFrame) -> None:
        SQLiteStorage._write_df(
            SQLiteStorage._meta_path(project, PENDING_SYSTEM_FILE), df
        )

    @staticmethod
    def _read_pending_uploads_df(project: str) -> pd.DataFrame:
        return SQLiteStorage._read_df(
            SQLiteStorage._meta_path(project, PENDING_UPLOADS_FILE),
            SQLiteStorage._pending_upload_columns(),
        )

    @staticmethod
    def _write_pending_uploads_df(project: str, df: pd.DataFrame) -> None:
        SQLiteStorage._write_df(
            SQLiteStorage._meta_path(project, PENDING_UPLOADS_FILE), df
        )

    @staticmethod
    def _active_runs(project: str) -> pd.DataFrame:
        df = SQLiteStorage._read_runs(project)
        if df.empty:
            return df
        return df.sort_values("created_at", kind="stable").reset_index(drop=True)

    @staticmethod
    def _run_row_by_name(project: str, run_name: str) -> pd.Series | None:
        runs = SQLiteStorage._active_runs(project)
        if runs.empty:
            return None
        matches = runs[runs["run_name"] == run_name]
        if matches.empty:
            return None
        return matches.iloc[0]

    @staticmethod
    def _run_row_by_id(project: str, run_id: str) -> pd.Series | None:
        runs = SQLiteStorage._active_runs(project)
        if runs.empty:
            return None
        matches = runs[runs["run_id"] == run_id]
        if matches.empty:
            return None
        return matches.iloc[0]

    @staticmethod
    def _ensure_run_unlocked(project: str, run_name: str) -> str:
        SQLiteStorage.init_db(project)
        runs = SQLiteStorage._read_runs(project)
        if not runs.empty:
            matches = runs[runs["run_name"] == run_name]
            if not matches.empty:
                return str(matches.iloc[0]["run_id"])

        run_id = uuid.uuid4().hex
        row = pd.DataFrame(
            [
                {
                    "run_id": run_id,
                    "run_name": run_name,
                    "created_at": _now_iso(),
                    "storage_key": run_id,
                }
            ]
        )
        runs = pd.concat([runs, row], ignore_index=True)
        SQLiteStorage._write_runs(project, runs)
        return run_id

    @staticmethod
    def ensure_run(project: str, run_name: str) -> str:
        with SQLiteStorage._get_process_lock(project):
            return SQLiteStorage._ensure_run_unlocked(project, run_name)

    @staticmethod
    def get_run_id(project: str, run_name: str) -> str | None:
        row = SQLiteStorage._run_row_by_name(project, run_name)
        return None if row is None else str(row["run_id"])

    @staticmethod
    def get_run_storage_key(project: str, run_name: str) -> str | None:
        row = SQLiteStorage._run_row_by_name(project, run_name)
        return None if row is None else str(row["storage_key"])

    @staticmethod
    def _run_name_for_id(project: str, run_id: str) -> str | None:
        row = SQLiteStorage._run_row_by_id(project, run_id)
        return None if row is None else str(row["run_name"])

    @staticmethod
    def init_db(project: str) -> Path:
        SQLiteStorage._ensure_hub_loaded()
        root = SQLiteStorage.get_project_root(project)
        root.mkdir(parents=True, exist_ok=True)
        for kind in ("metrics", "system_metrics", "alerts"):
            SQLiteStorage._data_dir(project, kind).mkdir(parents=True, exist_ok=True)
        return root

    @staticmethod
    def _existing_ids(project: str, kind: str, id_column: str, candidates: list[str]) -> set[str]:
        if not candidates:
            return set()
        columns = {
            "metrics": SQLiteStorage._metrics_columns(),
            "system_metrics": SQLiteStorage._system_columns(),
            "alerts": SQLiteStorage._alerts_columns(),
        }[kind]
        df = SQLiteStorage._read_parts(project, kind, columns)
        if df.empty or id_column not in df.columns:
            return set()
        values = df[id_column].dropna().astype(str)
        candidate_set = set(candidates)
        return {value for value in values if value in candidate_set}

    @staticmethod
    def log(project: str, run: str, metrics: dict, step: int | None = None):
        SQLiteStorage.bulk_log(project, run, [metrics], steps=[step] if step is not None else None)

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
        if not metrics_list:
            return

        if timestamps is None:
            timestamps = [_now_iso()] * len(metrics_list)
        else:
            timestamps = [ts if ts else _now_iso() for ts in timestamps]

        with SQLiteStorage._get_process_lock(project):
            run_id = SQLiteStorage._ensure_run_unlocked(project, run)

            if steps is None:
                last_step = SQLiteStorage.get_max_step_for_run(project, run)
                start = 0 if last_step is None else last_step + 1
                steps = list(range(start, start + len(metrics_list)))
            elif any(step is None for step in steps):
                last_step = SQLiteStorage.get_max_step_for_run(project, run)
                current = 0 if last_step is None else last_step + 1
                processed = []
                for step in steps:
                    if step is None:
                        processed.append(current)
                        current += 1
                    else:
                        processed.append(step)
                steps = processed

            if len(metrics_list) != len(steps) or len(metrics_list) != len(timestamps):
                raise ValueError(
                    "metrics_list, steps, and timestamps must have the same length"
                )

            duplicate_ids = SQLiteStorage._existing_ids(
                project, "metrics", "log_id", [lid for lid in (log_ids or []) if lid]
            )
            rows = []
            pending_rows = []
            for idx, metrics in enumerate(metrics_list):
                lid = log_ids[idx] if log_ids else None
                if lid is not None and lid in duplicate_ids:
                    continue
                metrics_json = _metrics_to_json(metrics)
                row = {
                    "run_id": run_id,
                    "timestamp": timestamps[idx],
                    "step": int(steps[idx]),
                    "metrics": metrics_json,
                    "log_id": lid,
                }
                rows.append(row)
                if space_id is not None:
                    pending_rows.append(
                        {
                            "id": uuid.uuid4().hex,
                            "project": project,
                            "run": run,
                            "timestamp": timestamps[idx],
                            "step": int(steps[idx]),
                            "metrics": metrics_json,
                            "log_id": lid,
                            "config": (
                                json_mod.dumps(serialize_values(config))
                                if config is not None and idx == 0
                                else None
                            ),
                            "space_id": space_id,
                        }
                    )

            if rows:
                SQLiteStorage._append_part(project, "metrics", pd.DataFrame(rows))

            if config:
                configs = SQLiteStorage._read_configs(project)
                configs = configs[configs["run_id"] != run_id]
                config_row = pd.DataFrame(
                    [
                        {
                            "run_id": run_id,
                            "config": json_mod.dumps(serialize_values(config)),
                            "created_at": _now_iso(),
                        }
                    ]
                )
                configs = pd.concat([configs, config_row], ignore_index=True)
                SQLiteStorage._write_configs(project, configs)

            if pending_rows:
                pending = SQLiteStorage._read_pending_logs_df(project)
                pending = pd.concat([pending, pd.DataFrame(pending_rows)], ignore_index=True)
                SQLiteStorage._write_pending_logs_df(project, pending)

    @staticmethod
    def bulk_log_system(
        project: str,
        run: str,
        metrics_list: list[dict],
        timestamps: list[str] | None = None,
        log_ids: list[str] | None = None,
        space_id: str | None = None,
    ):
        if not metrics_list:
            return

        if timestamps is None:
            timestamps = [_now_iso()] * len(metrics_list)
        else:
            timestamps = [ts if ts else _now_iso() for ts in timestamps]

        with SQLiteStorage._get_process_lock(project):
            run_id = SQLiteStorage._ensure_run_unlocked(project, run)
            duplicate_ids = SQLiteStorage._existing_ids(
                project,
                "system_metrics",
                "log_id",
                [lid for lid in (log_ids or []) if lid],
            )
            rows = []
            pending_rows = []
            for idx, metrics in enumerate(metrics_list):
                lid = log_ids[idx] if log_ids else None
                if lid is not None and lid in duplicate_ids:
                    continue
                metrics_json = _metrics_to_json(metrics)
                rows.append(
                    {
                        "run_id": run_id,
                        "timestamp": timestamps[idx],
                        "metrics": metrics_json,
                        "log_id": lid,
                    }
                )
                if space_id is not None:
                    pending_rows.append(
                        {
                            "id": uuid.uuid4().hex,
                            "project": project,
                            "run": run,
                            "timestamp": timestamps[idx],
                            "metrics": metrics_json,
                            "log_id": lid,
                            "space_id": space_id,
                        }
                    )
            if rows:
                SQLiteStorage._append_part(
                    project, "system_metrics", pd.DataFrame(rows)
                )
            if pending_rows:
                pending = SQLiteStorage._read_pending_system_df(project)
                pending = pd.concat([pending, pd.DataFrame(pending_rows)], ignore_index=True)
                SQLiteStorage._write_pending_system_df(project, pending)

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
    ):
        if not titles:
            return

        if timestamps is None:
            timestamps = [_now_iso()] * len(titles)
        else:
            timestamps = [ts if ts else _now_iso() for ts in timestamps]

        with SQLiteStorage._get_process_lock(project):
            run_id = SQLiteStorage._ensure_run_unlocked(project, run)
            duplicate_ids = SQLiteStorage._existing_ids(
                project, "alerts", "alert_id", [aid for aid in (alert_ids or []) if aid]
            )
            rows = []
            for idx in range(len(titles)):
                aid = alert_ids[idx] if alert_ids else None
                if aid is not None and aid in duplicate_ids:
                    continue
                rows.append(
                    {
                        "run_id": run_id,
                        "timestamp": timestamps[idx],
                        "title": titles[idx],
                        "text": texts[idx],
                        "level": levels[idx],
                        "step": steps[idx],
                        "alert_id": aid,
                    }
                )
            if rows:
                SQLiteStorage._append_part(project, "alerts", pd.DataFrame(rows))

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
        SQLiteStorage._dataset_import_attempted = True

    @staticmethod
    def _ensure_hub_loaded():
        if not SQLiteStorage._dataset_import_attempted:
            SQLiteStorage.load_from_dataset()

    @staticmethod
    def get_projects() -> list[str]:
        SQLiteStorage._ensure_hub_loaded()
        if not utils.TRACKIO_DIR.exists():
            return []
        projects = []
        for path in utils.TRACKIO_DIR.glob(f"*{PROJECT_EXT}"):
            if path.exists():
                projects.append(path.stem)
        return sorted(projects)

    @staticmethod
    def get_runs(project: str) -> list[str]:
        SQLiteStorage._ensure_hub_loaded()
        runs = SQLiteStorage._active_runs(project)
        if runs.empty:
            return []
        return runs.sort_values("created_at", kind="stable")["run_name"].tolist()

    @staticmethod
    def _run_metrics_df(project: str, run: str) -> pd.DataFrame:
        run_id = SQLiteStorage.get_run_id(project, run)
        if run_id is None:
            return _empty_df(SQLiteStorage._metrics_columns())
        df = SQLiteStorage._read_parts(project, "metrics", SQLiteStorage._metrics_columns())
        if df.empty:
            return df
        df = df[df["run_id"] == run_id].copy()
        if df.empty:
            return df
        return df.sort_values(["timestamp", "step"], kind="stable").reset_index(drop=True)

    @staticmethod
    def _run_system_df(project: str, run: str) -> pd.DataFrame:
        run_id = SQLiteStorage.get_run_id(project, run)
        if run_id is None:
            return _empty_df(SQLiteStorage._system_columns())
        df = SQLiteStorage._read_parts(
            project, "system_metrics", SQLiteStorage._system_columns()
        )
        if df.empty:
            return df
        df = df[df["run_id"] == run_id].copy()
        if df.empty:
            return df
        return df.sort_values("timestamp", kind="stable").reset_index(drop=True)

    @staticmethod
    def get_max_steps_for_runs(project: str) -> dict[str, int]:
        results = {}
        for run in SQLiteStorage.get_runs(project):
            last_step = SQLiteStorage.get_last_step(project, run)
            if last_step is not None:
                results[run] = last_step
        return results

    @staticmethod
    def get_max_step_for_run(project: str, run: str) -> int | None:
        return SQLiteStorage.get_last_step(project, run)

    @staticmethod
    def get_log_count(project: str, run: str) -> int:
        return len(SQLiteStorage._run_metrics_df(project, run))

    @staticmethod
    def get_last_step(project: str, run: str) -> int | None:
        df = SQLiteStorage._run_metrics_df(project, run)
        if df.empty:
            return None
        return int(df["step"].max())

    @staticmethod
    def get_logs(project: str, run: str, max_points: int | None = None) -> list[dict]:
        df = SQLiteStorage._run_metrics_df(project, run)
        if df.empty:
            return []
        rows = list(df.to_dict(orient="records"))
        if max_points is not None and len(rows) > max_points:
            step = len(rows) / max_points
            indices = {int(i * step) for i in range(max_points)}
            indices.add(len(rows) - 1)
            rows = [rows[i] for i in sorted(indices)]
        results = []
        for row in rows:
            metrics = _json_to_metrics(row["metrics"])
            metrics["timestamp"] = row["timestamp"]
            metrics["step"] = int(row["step"])
            results.append(metrics)
        return results

    @staticmethod
    def get_alerts(
        project: str,
        run_name: str | None = None,
        level: str | None = None,
        since: str | None = None,
    ) -> list[dict]:
        alerts = SQLiteStorage._read_parts(project, "alerts", SQLiteStorage._alerts_columns())
        if alerts.empty:
            return []
        runs = SQLiteStorage._active_runs(project)
        if runs.empty:
            return []
        merged = alerts.merge(runs[["run_id", "run_name"]], on="run_id", how="inner")
        if run_name is not None:
            merged = merged[merged["run_name"] == run_name]
        if level is not None:
            merged = merged[merged["level"] == level]
        if since is not None:
            merged = merged[merged["timestamp"] > since]
        merged = merged.sort_values("timestamp", ascending=False, kind="stable")
        return [
            {
                "timestamp": row["timestamp"],
                "run": row["run_name"],
                "title": row["title"],
                "text": row["text"],
                "level": row["level"],
                "step": row["step"],
            }
            for row in merged.to_dict(orient="records")
        ]

    @staticmethod
    def get_alert_count(project: str) -> int:
        return len(SQLiteStorage.get_alerts(project))

    @staticmethod
    def get_system_logs(project: str, run: str) -> list[dict]:
        df = SQLiteStorage._run_system_df(project, run)
        if df.empty:
            return []
        results = []
        for row in df.to_dict(orient="records"):
            metrics = _json_to_metrics(row["metrics"])
            metrics["timestamp"] = row["timestamp"]
            results.append(metrics)
        return results

    @staticmethod
    def get_all_system_metrics_for_run(project: str, run: str) -> list[str]:
        logs = SQLiteStorage.get_system_logs(project, run)
        names = set()
        for row in logs:
            for key in row.keys():
                if key != "timestamp":
                    names.add(key)
        return sorted(names)

    @staticmethod
    def has_system_metrics(project: str) -> bool:
        return not SQLiteStorage._read_parts(
            project, "system_metrics", SQLiteStorage._system_columns()
        ).empty

    @staticmethod
    def get_run_config(project: str, run: str) -> dict | None:
        run_id = SQLiteStorage.get_run_id(project, run)
        if run_id is None:
            return None
        configs = SQLiteStorage._read_configs(project)
        if configs.empty:
            return None
        matches = configs[configs["run_id"] == run_id]
        if matches.empty:
            return None
        row = matches.sort_values("created_at", kind="stable").iloc[-1]
        return deserialize_values(json_mod.loads(row["config"]))

    @staticmethod
    def get_all_run_configs(project: str) -> dict[str, dict]:
        runs = SQLiteStorage._active_runs(project)
        if runs.empty:
            return {}
        configs = SQLiteStorage._read_configs(project)
        if configs.empty:
            return {}
        latest = (
            configs.sort_values("created_at", kind="stable")
            .drop_duplicates(subset=["run_id"], keep="last")
        )
        merged = runs.merge(latest, on="run_id", how="left")
        result = {}
        for row in merged.to_dict(orient="records"):
            if isinstance(row.get("config"), str):
                result[row["run_name"]] = deserialize_values(json_mod.loads(row["config"]))
        return result

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
        rows = SQLiteStorage.get_logs(project, run)
        results = []
        for row in rows:
            include = True
            if step is not None:
                include = row["step"] == step
            elif around_step is not None and window is not None:
                include = around_step - int(window) <= row["step"] <= around_step + int(window)
            elif at_time is not None and window is not None:
                ts = datetime.fromisoformat(str(row["timestamp"]))
                ref = datetime.fromisoformat(str(at_time))
                include = abs((ts - ref).total_seconds()) <= float(window)
            if include and metric_name in row:
                results.append(
                    {
                        "timestamp": row["timestamp"],
                        "step": row["step"],
                        "value": row[metric_name],
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
        rows = SQLiteStorage.get_logs(project, run)
        result: dict[str, list[dict]] = {}
        for row in rows:
            include = True
            if step is not None:
                include = row["step"] == step
            elif around_step is not None and window is not None:
                include = around_step - int(window) <= row["step"] <= around_step + int(window)
            elif at_time is not None and window is not None:
                ts = datetime.fromisoformat(str(row["timestamp"]))
                ref = datetime.fromisoformat(str(at_time))
                include = abs((ts - ref).total_seconds()) <= float(window)
            if not include:
                continue
            for key, value in row.items():
                if key in {"timestamp", "step"}:
                    continue
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
        rows = SQLiteStorage.get_logs(project, run)
        names = set()
        for row in rows:
            for key in row.keys():
                if key not in {"timestamp", "step"}:
                    names.add(key)
        return sorted(names)

    @staticmethod
    def _update_media_paths(obj, old_prefix: str, new_prefix: str):
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
        if isinstance(obj, list):
            return [
                SQLiteStorage._update_media_paths(item, old_prefix, new_prefix)
                for item in obj
            ]
        return obj

    @staticmethod
    def _rewrite_metrics_media_paths(
        rows: pd.DataFrame, old_prefix: str, new_prefix: str
    ) -> pd.DataFrame:
        if rows.empty:
            return rows
        rewritten = rows.copy()
        rewritten["metrics"] = rewritten["metrics"].map(
            lambda value: _metrics_to_json(
                SQLiteStorage._update_media_paths(
                    _json_to_metrics(value), old_prefix, new_prefix
                )
            )
        )
        return rewritten

    @staticmethod
    def _move_media_dir(source: Path, target: Path):
        if source.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                shutil.rmtree(target)
            shutil.move(str(source), str(target))

    @staticmethod
    def delete_run(project: str, run: str) -> bool:
        with SQLiteStorage._get_process_lock(project):
            runs = SQLiteStorage._read_runs(project)
            if runs.empty:
                return False
            matches = runs[runs["run_name"] == run]
            if matches.empty:
                return False
            row = matches.iloc[0]
            runs = runs[runs["run_id"] != row["run_id"]]
            SQLiteStorage._write_runs(project, runs.reset_index(drop=True))
            media_dir = utils.MEDIA_DIR / project / str(row["storage_key"])
            if media_dir.exists():
                shutil.rmtree(media_dir, ignore_errors=True)
            return True

    @staticmethod
    def rename_run(project: str, old_name: str, new_name: str) -> None:
        if not new_name or not new_name.strip():
            raise ValueError("New run name cannot be empty")
        new_name = new_name.strip()
        with SQLiteStorage._get_process_lock(project):
            runs = SQLiteStorage._read_runs(project)
            if runs.empty or old_name not in runs["run_name"].tolist():
                raise ValueError(
                    f"Run '{old_name}' does not exist in project '{project}'"
                )
            if new_name in runs["run_name"].tolist():
                raise ValueError(
                    f"A run named '{new_name}' already exists in project '{project}'"
                )
            runs.loc[runs["run_name"] == old_name, "run_name"] = new_name
            SQLiteStorage._write_runs(project, runs.reset_index(drop=True))

    @staticmethod
    def move_run(project: str, run: str, new_project: str) -> bool:
        with SQLiteStorage._get_process_lock(project):
            source_row = SQLiteStorage._run_row_by_name(project, run)
            if source_row is None:
                return False
            with SQLiteStorage._get_process_lock(new_project):
                if SQLiteStorage.get_run_id(new_project, run) is not None:
                    return False

                SQLiteStorage.init_db(new_project)
                new_run_id = uuid.uuid4().hex
                new_storage_key = new_run_id

                target_runs = SQLiteStorage._read_runs(new_project)
                target_runs = pd.concat(
                    [
                        target_runs,
                        pd.DataFrame(
                            [
                                {
                                    "run_id": new_run_id,
                                    "run_name": run,
                                    "created_at": source_row["created_at"],
                                    "storage_key": new_storage_key,
                                }
                            ]
                        ),
                    ],
                    ignore_index=True,
                )
                SQLiteStorage._write_runs(new_project, target_runs)

                source_run_id = str(source_row["run_id"])
                source_storage_key = str(source_row["storage_key"])
                old_prefix = f"{project}/{source_storage_key}/"
                new_prefix = f"{new_project}/{new_storage_key}/"
                metrics = SQLiteStorage._read_parts(project, "metrics", SQLiteStorage._metrics_columns())
                if not metrics.empty:
                    rows = metrics[metrics["run_id"] == source_run_id].copy()
                    if not rows.empty:
                        rows["run_id"] = new_run_id
                        rows = SQLiteStorage._rewrite_metrics_media_paths(
                            rows, old_prefix, new_prefix
                        )
                        SQLiteStorage._append_part(new_project, "metrics", rows)

                system = SQLiteStorage._read_parts(project, "system_metrics", SQLiteStorage._system_columns())
                if not system.empty:
                    rows = system[system["run_id"] == source_run_id].copy()
                    if not rows.empty:
                        rows["run_id"] = new_run_id
                        SQLiteStorage._append_part(new_project, "system_metrics", rows)

                alerts = SQLiteStorage._read_parts(project, "alerts", SQLiteStorage._alerts_columns())
                if not alerts.empty:
                    rows = alerts[alerts["run_id"] == source_run_id].copy()
                    if not rows.empty:
                        rows["run_id"] = new_run_id
                        SQLiteStorage._append_part(new_project, "alerts", rows)

                configs = SQLiteStorage._read_configs(project)
                if not configs.empty:
                    rows = configs[configs["run_id"] == source_run_id].copy()
                    if not rows.empty:
                        rows["run_id"] = new_run_id
                        target_configs = SQLiteStorage._read_configs(new_project)
                        target_configs = pd.concat([target_configs, rows], ignore_index=True)
                        SQLiteStorage._write_configs(new_project, target_configs)

                SQLiteStorage._move_media_dir(
                    utils.MEDIA_DIR / project / str(source_row["storage_key"]),
                    utils.MEDIA_DIR / new_project / new_storage_key,
                )

                runs = SQLiteStorage._read_runs(project)
                runs = runs[runs["run_id"] != source_run_id]
                SQLiteStorage._write_runs(project, runs.reset_index(drop=True))
                return True

    @staticmethod
    def set_project_metadata(project: str, key: str, value: str) -> None:
        SQLiteStorage.init_db(project)
        with SQLiteStorage._get_process_lock(project):
            df = SQLiteStorage._read_project_metadata_df(project)
            df = df[df["key"] != key]
            df = pd.concat(
                [df, pd.DataFrame([{"key": key, "value": value, "updated_at": _now_iso()}])],
                ignore_index=True,
            )
            SQLiteStorage._write_project_metadata_df(project, df)

    @staticmethod
    def get_project_metadata(project: str, key: str) -> str | None:
        df = SQLiteStorage._read_project_metadata_df(project)
        if df.empty:
            return None
        matches = df[df["key"] == key]
        if matches.empty:
            return None
        return str(matches.sort_values("updated_at", kind="stable").iloc[-1]["value"])

    @staticmethod
    def get_space_id(project: str) -> str | None:
        return SQLiteStorage.get_project_metadata(project, "space_id")

    @staticmethod
    def has_pending_data(project: str) -> bool:
        return (
            not SQLiteStorage._read_pending_logs_df(project).empty
            or not SQLiteStorage._read_pending_system_df(project).empty
            or not SQLiteStorage._read_pending_uploads_df(project).empty
        )

    @staticmethod
    def get_pending_logs(project: str) -> dict | None:
        df = SQLiteStorage._read_pending_logs_df(project)
        if df.empty:
            return None
        logs = []
        ids = []
        for row in df.to_dict(orient="records"):
            entry = {
                "project": project,
                "run": row["run"],
                "metrics": _json_to_metrics(row["metrics"]),
                "timestamp": row["timestamp"],
                "log_id": row["log_id"],
                "step": None if pd.isna(row["step"]) else int(row["step"]),
                "config": (
                    deserialize_values(json_mod.loads(row["config"]))
                    if isinstance(row.get("config"), str) and row["config"]
                    else None
                ),
            }
            logs.append(entry)
            ids.append(row["id"])
        return {"logs": logs, "ids": ids, "space_id": df.iloc[0]["space_id"]}

    @staticmethod
    def clear_pending_logs(project: str, metric_ids: list[int]) -> None:
        if not metric_ids:
            return
        with SQLiteStorage._get_process_lock(project):
            df = SQLiteStorage._read_pending_logs_df(project)
            df = df[~df["id"].isin(metric_ids)]
            SQLiteStorage._write_pending_logs_df(project, df.reset_index(drop=True))

    @staticmethod
    def get_pending_system_logs(project: str) -> dict | None:
        df = SQLiteStorage._read_pending_system_df(project)
        if df.empty:
            return None
        logs = []
        ids = []
        for row in df.to_dict(orient="records"):
            logs.append(
                {
                    "project": project,
                    "run": row["run"],
                    "metrics": _json_to_metrics(row["metrics"]),
                    "timestamp": row["timestamp"],
                    "log_id": row["log_id"],
                }
            )
            ids.append(row["id"])
        return {"logs": logs, "ids": ids, "space_id": df.iloc[0]["space_id"]}

    @staticmethod
    def clear_pending_system_logs(project: str, metric_ids: list[int]) -> None:
        if not metric_ids:
            return
        with SQLiteStorage._get_process_lock(project):
            df = SQLiteStorage._read_pending_system_df(project)
            df = df[~df["id"].isin(metric_ids)]
            SQLiteStorage._write_pending_system_df(project, df.reset_index(drop=True))

    @staticmethod
    def get_pending_uploads(project: str) -> dict | None:
        df = SQLiteStorage._read_pending_uploads_df(project)
        if df.empty:
            return None
        uploads = []
        ids = []
        for row in df.to_dict(orient="records"):
            uploads.append(
                {
                    "project": project,
                    "run": row["run_name"],
                    "step": None if pd.isna(row["step"]) else int(row["step"]),
                    "file_path": row["file_path"],
                    "relative_path": row["relative_path"],
                }
            )
            ids.append(row["id"])
        return {"uploads": uploads, "ids": ids, "space_id": df.iloc[0]["space_id"]}

    @staticmethod
    def clear_pending_uploads(project: str, upload_ids: list[int]) -> None:
        if not upload_ids:
            return
        with SQLiteStorage._get_process_lock(project):
            df = SQLiteStorage._read_pending_uploads_df(project)
            df = df[~df["id"].isin(upload_ids)]
            SQLiteStorage._write_pending_uploads_df(project, df.reset_index(drop=True))

    @staticmethod
    def add_pending_upload(
        project: str,
        space_id: str,
        run_name: str | None,
        step: int | None,
        file_path: str,
        relative_path: str | None,
    ) -> None:
        SQLiteStorage.init_db(project)
        with SQLiteStorage._get_process_lock(project):
            df = SQLiteStorage._read_pending_uploads_df(project)
            df = pd.concat(
                [
                    df,
                    pd.DataFrame(
                        [
                            {
                                "id": uuid.uuid4().hex,
                                "space_id": space_id,
                                "run_name": run_name,
                                "step": step,
                                "file_path": file_path,
                                "relative_path": relative_path,
                                "created_at": _now_iso(),
                            }
                        ]
                    ),
                ],
                ignore_index=True,
            )
            SQLiteStorage._write_pending_uploads_df(project, df)

    @staticmethod
    def get_all_logs_for_sync(project: str) -> list[dict]:
        runs = SQLiteStorage._active_runs(project)
        if runs.empty:
            return []
        run_map = {row["run_id"]: row["run_name"] for row in runs.to_dict(orient="records")}
        configs = SQLiteStorage.get_all_run_configs(project)
        df = SQLiteStorage._read_parts(project, "metrics", SQLiteStorage._metrics_columns())
        if df.empty:
            return []
        df = df[df["run_id"].isin(run_map.keys())].copy()
        df = df.sort_values(["run_id", "step"], kind="stable")
        results = []
        config_sent = set()
        for row in df.to_dict(orient="records"):
            run_name = run_map.get(row["run_id"])
            if run_name is None:
                continue
            entry = {
                "project": project,
                "run": run_name,
                "metrics": _json_to_metrics(row["metrics"]),
                "timestamp": row["timestamp"],
                "log_id": row["log_id"],
                "step": int(row["step"]),
                "config": None,
            }
            if run_name not in config_sent and run_name in configs:
                entry["config"] = configs[run_name]
                config_sent.add(run_name)
            results.append(entry)
        return results

    @staticmethod
    def get_all_system_logs_for_sync(project: str) -> list[dict]:
        runs = SQLiteStorage._active_runs(project)
        if runs.empty:
            return []
        run_map = {row["run_id"]: row["run_name"] for row in runs.to_dict(orient="records")}
        df = SQLiteStorage._read_parts(project, "system_metrics", SQLiteStorage._system_columns())
        if df.empty:
            return []
        df = df[df["run_id"].isin(run_map.keys())].copy()
        df = df.sort_values(["run_id", "timestamp"], kind="stable")
        results = []
        for row in df.to_dict(orient="records"):
            run_name = run_map.get(row["run_id"])
            if run_name is None:
                continue
            results.append(
                {
                    "project": project,
                    "run": run_name,
                    "metrics": _json_to_metrics(row["metrics"]),
                    "timestamp": row["timestamp"],
                    "log_id": row["log_id"],
                }
            )
        return results

    @staticmethod
    def export_to_parquet():
        return

    @staticmethod
    def import_from_parquet():
        return

    @staticmethod
    def export_for_static_space(
        project: str, output_dir: Path, db_path_override: Path | None = None
    ) -> None:
        output_dir.mkdir(parents=True, exist_ok=True)
        aux_dir = output_dir / "aux"
        aux_dir.mkdir(parents=True, exist_ok=True)

        runs = SQLiteStorage._active_runs(project)
        if runs.empty:
            raise FileNotFoundError(f"No data found for project '{project}'")
        run_map = {row["run_id"]: row["run_name"] for row in runs.to_dict(orient="records")}

        metrics = SQLiteStorage._read_parts(project, "metrics", SQLiteStorage._metrics_columns())
        if not metrics.empty:
            metrics = metrics[metrics["run_id"].isin(run_map.keys())].copy()
            metrics["run_name"] = metrics["run_id"].map(run_map)
            metrics["metrics"] = metrics["metrics"].map(lambda x: _json_to_metrics(x))
            expanded = pd.DataFrame(metrics["metrics"].tolist(), index=metrics.index)
            flat = pd.concat(
                [metrics[["timestamp", "run_name", "step"]].reset_index(drop=True), expanded.reset_index(drop=True)],
                axis=1,
            )
            flat.to_parquet(output_dir / "metrics.parquet", index=False)

        system = SQLiteStorage._read_parts(project, "system_metrics", SQLiteStorage._system_columns())
        if not system.empty:
            system = system[system["run_id"].isin(run_map.keys())].copy()
            system["run_name"] = system["run_id"].map(run_map)
            system["metrics"] = system["metrics"].map(lambda x: _json_to_metrics(x))
            expanded = pd.DataFrame(system["metrics"].tolist(), index=system.index)
            flat = pd.concat(
                [system[["timestamp", "run_name"]].reset_index(drop=True), expanded.reset_index(drop=True)],
                axis=1,
            )
            flat.to_parquet(aux_dir / "system_metrics.parquet", index=False)

        configs = SQLiteStorage.get_all_run_configs(project)
        if configs:
            rows = []
            for run_name, config in configs.items():
                row = {"run_name": run_name}
                row.update(config)
                rows.append(row)
            pd.DataFrame(rows).to_parquet(aux_dir / "configs.parquet", index=False)

        runs_meta = []
        for run_name in SQLiteStorage.get_runs(project):
            runs_meta.append(
                {
                    "name": run_name,
                    "last_step": SQLiteStorage.get_last_step(project, run_name),
                    "log_count": SQLiteStorage.get_log_count(project, run_name),
                }
            )
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
    def get_scheduler():
        with SQLiteStorage._scheduler_lock:
            if SQLiteStorage._current_scheduler is None:
                SQLiteStorage._current_scheduler = DummyCommitScheduler()
            return SQLiteStorage._current_scheduler
