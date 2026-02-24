import os
import shutil
import threading
import time
import uuid
import warnings
from datetime import datetime, timezone
from pathlib import Path

import huggingface_hub
from gradio_client import Client, handle_file

from trackio import utils
from trackio.alerts import AlertLevel, format_alert_terminal, send_webhook
from trackio.gpu import GpuMonitor
from trackio.histogram import Histogram
from trackio.markdown import Markdown
from trackio.media import TrackioMedia, get_project_media_path
from trackio.sqlite_storage import SQLiteStorage
from trackio.table import Table
from trackio.typehints import AlertEntry, LogEntry, SystemLogEntry, UploadEntry
from trackio.utils import _get_default_namespace

BATCH_SEND_INTERVAL = 0.5
MAX_BACKOFF = 30


class Run:
    def __init__(
        self,
        url: str | None,
        project: str,
        client: Client | None,
        name: str | None = None,
        group: str | None = None,
        config: dict | None = None,
        space_id: str | None = None,
        auto_log_gpu: bool = False,
        gpu_log_interval: float = 10.0,
        webhook_url: str | None = None,
    ):
        """
        Initialize a Run for logging metrics to Trackio.

        Args:
            url: The URL of the Trackio server (local Gradio app or HF Space).
            project: The name of the project to log metrics to.
            client: A pre-configured gradio_client.Client instance, or None to
                create one automatically in a background thread with retry logic.
                Passing None is recommended for normal usage. Passing a client
                is useful for testing (e.g., injecting a mock client).
            name: The name of this run. If None, a readable name like
                "brave-sunset-0" is auto-generated. If space_id is provided,
                generates a "username-timestamp" format instead.
            group: Optional group name to organize related runs together.
            config: A dictionary of configuration/hyperparameters for this run.
                Keys starting with '_' are reserved for internal use.
            space_id: The HF Space ID if logging to a Space (e.g., "user/space").
                If provided, media files will be uploaded to the Space.
            auto_log_gpu: Whether to automatically log GPU metrics (utilization,
                memory, temperature) at regular intervals.
            gpu_log_interval: The interval in seconds between GPU metric logs.
                Only used when auto_log_gpu is True.
            webhook_url: A webhook URL to POST alert payloads to. Supports
                Slack and Discord webhook URLs natively. Can also be set via
                the TRACKIO_WEBHOOK_URL environment variable.
        """
        self.url = url
        self.project = project
        self._client_lock = threading.Lock()
        self._client_thread = None
        self._client = client
        self._space_id = space_id
        self.name = name or utils.generate_readable_name(
            SQLiteStorage.get_runs(project), space_id
        )
        self.group = group
        self.config = utils.to_json_safe(config or {})

        if isinstance(self.config, dict):
            for key in self.config:
                if key.startswith("_"):
                    raise ValueError(
                        f"Config key '{key}' is reserved (keys starting with '_' are reserved for internal use)"
                    )

        self.config["_Username"] = self._get_username()
        self.config["_Created"] = datetime.now(timezone.utc).isoformat()
        self.config["_Group"] = self.group

        self._queued_logs: list[LogEntry] = []
        self._queued_system_logs: list[SystemLogEntry] = []
        self._queued_uploads: list[UploadEntry] = []
        self._queued_alerts: list[AlertEntry] = []
        self._stop_flag = threading.Event()
        self._config_logged = False
        max_step = SQLiteStorage.get_max_step_for_run(self.project, self.name)
        self._next_step = 0 if max_step is None else max_step + 1
        self._has_local_buffer = False

        self._is_local = space_id is None
        self._webhook_url = webhook_url or os.environ.get("TRACKIO_WEBHOOK_URL")

        if self._is_local:
            self._local_sender_thread = threading.Thread(
                target=self._local_batch_sender
            )
            self._local_sender_thread.daemon = True
            self._local_sender_thread.start()
        else:
            self._client_thread = threading.Thread(target=self._init_client_background)
            self._client_thread.daemon = True
            self._client_thread.start()

        self._gpu_monitor: "GpuMonitor | None" = None
        if auto_log_gpu:
            self._gpu_monitor = GpuMonitor(self, interval=gpu_log_interval)
            self._gpu_monitor.start()

    def _get_username(self) -> str | None:
        try:
            return _get_default_namespace()
        except Exception:
            return None

    def _local_batch_sender(self):
        while (
            not self._stop_flag.is_set()
            or len(self._queued_logs) > 0
            or len(self._queued_system_logs) > 0
            or len(self._queued_alerts) > 0
        ):
            if not self._stop_flag.is_set():
                time.sleep(BATCH_SEND_INTERVAL)

            with self._client_lock:
                if self._queued_logs:
                    logs_to_send = self._queued_logs.copy()
                    self._queued_logs.clear()
                    self._write_logs_to_sqlite(logs_to_send)

                if self._queued_system_logs:
                    system_logs_to_send = self._queued_system_logs.copy()
                    self._queued_system_logs.clear()
                    self._write_system_logs_to_sqlite(system_logs_to_send)

                if self._queued_alerts:
                    alerts_to_send = self._queued_alerts.copy()
                    self._queued_alerts.clear()
                    self._write_alerts_to_sqlite(alerts_to_send)

    def _write_logs_to_sqlite(self, logs: list[LogEntry]):
        logs_by_run: dict[tuple, dict] = {}
        for entry in logs:
            key = (entry["project"], entry["run"])
            if key not in logs_by_run:
                logs_by_run[key] = {
                    "metrics": [],
                    "steps": [],
                    "log_ids": [],
                    "config": None,
                }
            logs_by_run[key]["metrics"].append(entry["metrics"])
            logs_by_run[key]["steps"].append(entry.get("step"))
            logs_by_run[key]["log_ids"].append(entry.get("log_id"))
            if entry.get("config") and logs_by_run[key]["config"] is None:
                logs_by_run[key]["config"] = entry["config"]

        for (project, run), data in logs_by_run.items():
            has_log_ids = any(lid is not None for lid in data["log_ids"])
            SQLiteStorage.bulk_log(
                project=project,
                run=run,
                metrics_list=data["metrics"],
                steps=data["steps"],
                config=data["config"],
                log_ids=data["log_ids"] if has_log_ids else None,
            )

    def _write_system_logs_to_sqlite(self, logs: list[SystemLogEntry]):
        logs_by_run: dict[tuple, dict] = {}
        for entry in logs:
            key = (entry["project"], entry["run"])
            if key not in logs_by_run:
                logs_by_run[key] = {"metrics": [], "timestamps": [], "log_ids": []}
            logs_by_run[key]["metrics"].append(entry["metrics"])
            logs_by_run[key]["timestamps"].append(entry.get("timestamp"))
            logs_by_run[key]["log_ids"].append(entry.get("log_id"))

        for (project, run), data in logs_by_run.items():
            has_log_ids = any(lid is not None for lid in data["log_ids"])
            SQLiteStorage.bulk_log_system(
                project=project,
                run=run,
                metrics_list=data["metrics"],
                timestamps=data["timestamps"],
                log_ids=data["log_ids"] if has_log_ids else None,
            )

    def _write_alerts_to_sqlite(self, alerts: list[AlertEntry]):
        alerts_by_run: dict[tuple, dict] = {}
        for entry in alerts:
            key = (entry["project"], entry["run"])
            if key not in alerts_by_run:
                alerts_by_run[key] = {
                    "titles": [],
                    "texts": [],
                    "levels": [],
                    "steps": [],
                    "timestamps": [],
                    "alert_ids": [],
                }
            alerts_by_run[key]["titles"].append(entry["title"])
            alerts_by_run[key]["texts"].append(entry.get("text"))
            alerts_by_run[key]["levels"].append(entry["level"])
            alerts_by_run[key]["steps"].append(entry.get("step"))
            alerts_by_run[key]["timestamps"].append(entry.get("timestamp"))
            alerts_by_run[key]["alert_ids"].append(entry.get("alert_id"))

        for (project, run), data in alerts_by_run.items():
            has_alert_ids = any(aid is not None for aid in data["alert_ids"])
            SQLiteStorage.bulk_alert(
                project=project,
                run=run,
                titles=data["titles"],
                texts=data["texts"],
                levels=data["levels"],
                steps=data["steps"],
                timestamps=data["timestamps"],
                alert_ids=data["alert_ids"] if has_alert_ids else None,
            )

    def _batch_sender(self):
        consecutive_failures = 0
        while (
            not self._stop_flag.is_set()
            or len(self._queued_logs) > 0
            or len(self._queued_system_logs) > 0
            or len(self._queued_uploads) > 0
            or len(self._queued_alerts) > 0
        ):
            if not self._stop_flag.is_set():
                if consecutive_failures:
                    sleep_time = min(
                        BATCH_SEND_INTERVAL * (2**consecutive_failures), MAX_BACKOFF
                    )
                else:
                    sleep_time = BATCH_SEND_INTERVAL
                time.sleep(sleep_time)

            with self._client_lock:
                if self._client is None:
                    return

                failed = False

                if self._queued_logs:
                    logs_to_send = self._queued_logs.copy()
                    self._queued_logs.clear()
                    try:
                        self._client.predict(
                            api_name="/bulk_log",
                            logs=logs_to_send,
                            hf_token=huggingface_hub.utils.get_token(),
                        )
                    except Exception:
                        self._persist_logs_locally(logs_to_send)
                        failed = True

                if self._queued_system_logs:
                    system_logs_to_send = self._queued_system_logs.copy()
                    self._queued_system_logs.clear()
                    try:
                        self._client.predict(
                            api_name="/bulk_log_system",
                            logs=system_logs_to_send,
                            hf_token=huggingface_hub.utils.get_token(),
                        )
                    except Exception:
                        self._persist_system_logs_locally(system_logs_to_send)
                        failed = True

                if self._queued_uploads:
                    uploads_to_send = self._queued_uploads.copy()
                    self._queued_uploads.clear()
                    try:
                        self._client.predict(
                            api_name="/bulk_upload_media",
                            uploads=uploads_to_send,
                            hf_token=huggingface_hub.utils.get_token(),
                        )
                    except Exception:
                        self._persist_uploads_locally(uploads_to_send)
                        failed = True

                if self._queued_alerts:
                    alerts_to_send = self._queued_alerts.copy()
                    self._queued_alerts.clear()
                    try:
                        self._client.predict(
                            api_name="/bulk_alert",
                            alerts=alerts_to_send,
                            hf_token=huggingface_hub.utils.get_token(),
                        )
                    except Exception:
                        self._write_alerts_to_sqlite(alerts_to_send)
                        failed = True

                if failed:
                    consecutive_failures += 1
                else:
                    consecutive_failures = 0
                    if self._has_local_buffer:
                        self._flush_local_buffer()

    def _persist_logs_locally(self, logs: list[LogEntry]):
        if not self._space_id:
            return
        logs_by_run: dict[tuple, dict] = {}
        for entry in logs:
            key = (entry["project"], entry["run"])
            if key not in logs_by_run:
                logs_by_run[key] = {
                    "metrics": [],
                    "steps": [],
                    "log_ids": [],
                    "config": None,
                }
            logs_by_run[key]["metrics"].append(entry["metrics"])
            logs_by_run[key]["steps"].append(entry.get("step"))
            logs_by_run[key]["log_ids"].append(entry.get("log_id"))
            if entry.get("config") and logs_by_run[key]["config"] is None:
                logs_by_run[key]["config"] = entry["config"]

        for (project, run), data in logs_by_run.items():
            SQLiteStorage.bulk_log(
                project=project,
                run=run,
                metrics_list=data["metrics"],
                steps=data["steps"],
                log_ids=data["log_ids"],
                config=data["config"],
                space_id=self._space_id,
            )
        self._has_local_buffer = True

    def _persist_system_logs_locally(self, logs: list[SystemLogEntry]):
        if not self._space_id:
            return
        logs_by_run: dict[tuple, dict] = {}
        for entry in logs:
            key = (entry["project"], entry["run"])
            if key not in logs_by_run:
                logs_by_run[key] = {"metrics": [], "timestamps": [], "log_ids": []}
            logs_by_run[key]["metrics"].append(entry["metrics"])
            logs_by_run[key]["timestamps"].append(entry.get("timestamp"))
            logs_by_run[key]["log_ids"].append(entry.get("log_id"))

        for (project, run), data in logs_by_run.items():
            SQLiteStorage.bulk_log_system(
                project=project,
                run=run,
                metrics_list=data["metrics"],
                timestamps=data["timestamps"],
                log_ids=data["log_ids"],
                space_id=self._space_id,
            )
        self._has_local_buffer = True

    def _persist_uploads_locally(self, uploads: list[UploadEntry]):
        if not self._space_id:
            return
        for entry in uploads:
            file_data = entry.get("uploaded_file")
            file_path = ""
            if isinstance(file_data, dict):
                file_path = file_data.get("path", "")
            elif hasattr(file_data, "path"):
                file_path = str(file_data.path)
            else:
                file_path = str(file_data)
            SQLiteStorage.add_pending_upload(
                project=entry["project"],
                space_id=self._space_id,
                run_name=entry.get("run"),
                step=entry.get("step"),
                file_path=file_path,
                relative_path=entry.get("relative_path"),
            )
        self._has_local_buffer = True

    def _flush_local_buffer(self):
        try:
            buffered_logs = SQLiteStorage.get_pending_logs(self.project)
            if buffered_logs:
                self._client.predict(
                    api_name="/bulk_log",
                    logs=buffered_logs["logs"],
                    hf_token=huggingface_hub.utils.get_token(),
                )
                SQLiteStorage.clear_pending_logs(self.project, buffered_logs["ids"])

            buffered_sys = SQLiteStorage.get_pending_system_logs(self.project)
            if buffered_sys:
                self._client.predict(
                    api_name="/bulk_log_system",
                    logs=buffered_sys["logs"],
                    hf_token=huggingface_hub.utils.get_token(),
                )
                SQLiteStorage.clear_pending_system_logs(
                    self.project, buffered_sys["ids"]
                )

            buffered_uploads = SQLiteStorage.get_pending_uploads(self.project)
            if buffered_uploads:
                upload_entries = []
                for u in buffered_uploads["uploads"]:
                    fp = u["file_path"]
                    if Path(fp).exists():
                        upload_entries.append(
                            {
                                "project": u["project"],
                                "run": u["run"],
                                "step": u["step"],
                                "relative_path": u["relative_path"],
                                "uploaded_file": handle_file(fp),
                            }
                        )
                if upload_entries:
                    self._client.predict(
                        api_name="/bulk_upload_media",
                        uploads=upload_entries,
                        hf_token=huggingface_hub.utils.get_token(),
                    )
                SQLiteStorage.clear_pending_uploads(
                    self.project, buffered_uploads["ids"]
                )

            self._has_local_buffer = False
        except Exception:
            pass

    def _init_client_background(self):
        if self._client is None:
            fib = utils.fibo()
            for sleep_coefficient in fib:
                try:
                    client = Client(self.url, verbose=False)

                    with self._client_lock:
                        self._client = client
                    break
                except Exception:
                    pass
                if sleep_coefficient is not None:
                    time.sleep(0.1 * sleep_coefficient)

        self._batch_sender()

    def _queue_upload(
        self,
        file_path,
        step: int | None,
        relative_path: str | None = None,
        use_run_name: bool = True,
    ):
        if self._is_local:
            self._save_upload_locally(file_path, step, relative_path, use_run_name)
        else:
            upload_entry: UploadEntry = {
                "project": self.project,
                "run": self.name if use_run_name else None,
                "step": step,
                "relative_path": relative_path,
                "uploaded_file": handle_file(file_path),
            }
            with self._client_lock:
                self._queued_uploads.append(upload_entry)

    def _save_upload_locally(
        self,
        file_path,
        step: int | None,
        relative_path: str | None = None,
        use_run_name: bool = True,
    ):
        media_path = get_project_media_path(
            project=self.project,
            run=self.name if use_run_name else None,
            step=step,
            relative_path=relative_path,
        )
        src = Path(file_path)
        if src.exists() and str(src.resolve()) != str(Path(media_path).resolve()):
            shutil.copy(str(src), str(media_path))

    def _process_media(self, value: TrackioMedia, step: int | None) -> dict:
        value._save(self.project, self.name, step if step is not None else 0)
        if self._space_id:
            self._queue_upload(value._get_absolute_file_path(), step)
        return value._to_dict()

    def _scan_and_queue_media_uploads(self, table_dict: dict, step: int | None):
        if not self._space_id:
            return

        table_data = table_dict.get("_value", [])
        for row in table_data:
            for value in row.values():
                if isinstance(value, dict) and value.get("_type") in [
                    "trackio.image",
                    "trackio.video",
                    "trackio.audio",
                ]:
                    file_path = value.get("file_path")
                    if file_path:
                        from trackio.utils import MEDIA_DIR

                        absolute_path = MEDIA_DIR / file_path
                        self._queue_upload(absolute_path, step)
                elif isinstance(value, list):
                    for item in value:
                        if isinstance(item, dict) and item.get("_type") in [
                            "trackio.image",
                            "trackio.video",
                            "trackio.audio",
                        ]:
                            file_path = item.get("file_path")
                            if file_path:
                                from trackio.utils import MEDIA_DIR

                                absolute_path = MEDIA_DIR / file_path
                                self._queue_upload(absolute_path, step)

    def _ensure_sender_alive(self):
        if self._is_local:
            if (
                hasattr(self, "_local_sender_thread")
                and not self._local_sender_thread.is_alive()
                and not self._stop_flag.is_set()
            ):
                self._local_sender_thread = threading.Thread(
                    target=self._local_batch_sender
                )
                self._local_sender_thread.daemon = True
                self._local_sender_thread.start()
        else:
            if (
                self._client_thread is not None
                and not self._client_thread.is_alive()
                and not self._stop_flag.is_set()
            ):
                self._client_thread = threading.Thread(
                    target=self._init_client_background
                )
                self._client_thread.daemon = True
                self._client_thread.start()

    def log(self, metrics: dict, step: int | None = None):
        renamed_keys = []
        new_metrics = {}

        for k, v in metrics.items():
            if k in utils.RESERVED_KEYS or k.startswith("__"):
                new_key = f"__{k}"
                renamed_keys.append(k)
                new_metrics[new_key] = v
            else:
                new_metrics[k] = v

        if renamed_keys:
            warnings.warn(f"Reserved keys renamed: {renamed_keys} → '__{{key}}'")

        metrics = new_metrics
        for key, value in metrics.items():
            if isinstance(value, Table):
                metrics[key] = value._to_dict(
                    project=self.project, run=self.name, step=step
                )
                self._scan_and_queue_media_uploads(metrics[key], step)
            elif isinstance(value, Histogram):
                metrics[key] = value._to_dict()
            elif isinstance(value, Markdown):
                metrics[key] = value._to_dict()
            elif isinstance(value, TrackioMedia):
                metrics[key] = self._process_media(value, step)
        metrics = utils.serialize_values(metrics)

        if step is None:
            step = self._next_step
        self._next_step = max(self._next_step, step + 1)

        config_to_log = None
        if not self._config_logged and self.config:
            config_to_log = utils.to_json_safe(self.config)
            self._config_logged = True

        log_entry: LogEntry = {
            "project": self.project,
            "run": self.name,
            "metrics": metrics,
            "step": step,
            "config": config_to_log,
            "log_id": uuid.uuid4().hex,
        }

        with self._client_lock:
            self._queued_logs.append(log_entry)
            self._ensure_sender_alive()

    def alert(
        self,
        title: str,
        text: str | None = None,
        level: AlertLevel = AlertLevel.WARN,
        step: int | None = None,
        webhook_url: str | None = None,
    ):
        if step is None:
            step = max(self._next_step - 1, 0)
        timestamp = datetime.now(timezone.utc).isoformat()

        print(format_alert_terminal(level, title, text, step))

        alert_entry: AlertEntry = {
            "project": self.project,
            "run": self.name,
            "title": title,
            "text": text,
            "level": level.value,
            "step": step,
            "timestamp": timestamp,
            "alert_id": uuid.uuid4().hex,
        }

        with self._client_lock:
            self._queued_alerts.append(alert_entry)
            self._ensure_sender_alive()

        url = webhook_url or self._webhook_url
        if url:
            t = threading.Thread(
                target=send_webhook,
                args=(
                    url,
                    level,
                    title,
                    text,
                    self.project,
                    self.name,
                    step,
                    timestamp,
                ),
                daemon=True,
            )
            t.start()

    def log_system(self, metrics: dict):
        metrics = utils.serialize_values(metrics)
        timestamp = datetime.now(timezone.utc).isoformat()

        system_log_entry: SystemLogEntry = {
            "project": self.project,
            "run": self.name,
            "metrics": metrics,
            "timestamp": timestamp,
            "log_id": uuid.uuid4().hex,
        }

        with self._client_lock:
            self._queued_system_logs.append(system_log_entry)
            self._ensure_sender_alive()

    def finish(self):
        if self._gpu_monitor is not None:
            self._gpu_monitor.stop()

        self._stop_flag.set()

        if self._is_local:
            if hasattr(self, "_local_sender_thread"):
                print("* Run finished. Uploading logs to Trackio (please wait...)")
                self._local_sender_thread.join(timeout=30)
                if self._local_sender_thread.is_alive():
                    warnings.warn(
                        "Could not flush all logs within 30s. Some data may be buffered locally."
                    )
        else:
            if self._client_thread is not None:
                print(
                    "* Run finished. Uploading logs to Trackio Space (please wait...)"
                )
                self._client_thread.join(timeout=30)
                if self._client_thread.is_alive():
                    warnings.warn(
                        "Could not flush all logs within 30s. Some data may be buffered locally."
                    )
