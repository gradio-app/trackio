import os
import shutil
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import huggingface_hub
from gradio_client import handle_file

from trackio import utils
from trackio.alerts import (
    AlertLevel,
    format_alert_terminal,
    resolve_webhook_min_level,
    send_webhook,
    should_send_webhook,
)
from trackio.apple_gpu import AppleGpuMonitor, apple_gpu_available
from trackio.gpu import GpuMonitor, gpu_available
from trackio.histogram import Histogram
from trackio.markdown import Markdown
from trackio.media import TrackioMedia, get_project_media_path
from trackio.remote_client import RemoteClient
from trackio.sqlite_storage import SQLiteStorage
from trackio.table import Table
from trackio.typehints import AlertEntry, LogEntry, SystemLogEntry, UploadEntry
from trackio.utils import MEDIA_DIR, _emit_nonfatal_warning, _get_default_namespace

BATCH_SEND_INTERVAL = 0.5
MAX_BACKOFF = 30


class Run:
    def __init__(
        self,
        url: str | None,
        project: str,
        client: Any | None,
        name: str | None = None,
        run_id: str | None = None,
        group: str | None = None,
        config: dict | None = None,
        space_id: str | None = None,
        auto_log_gpu: bool = False,
        gpu_log_interval: float = 10.0,
        webhook_url: str | None = None,
        webhook_min_level: AlertLevel | str | None = None,
    ):
        """
        Initialize a Run for logging metrics to Trackio.

        Args:
            url: The URL or Space id of the Trackio server.
            project: The name of the project to log metrics to.
            client: A pre-configured Trackio-compatible client instance, or None to
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
            webhook_min_level: Minimum alert level that should trigger webhook
                delivery. For example, `AlertLevel.WARN` sends only WARN and
                ERROR alerts to webhook destinations. Can also be set via
                `TRACKIO_WEBHOOK_MIN_LEVEL`.
        """
        self.url = url
        self.project = project
        self._client_lock = threading.Lock()
        self._warning_lock = threading.Lock()
        self._warned_failures: set[str] = set()
        self._local_sender_thread: threading.Thread | None = None
        self._client_thread = None
        self._client = client
        self._space_id = space_id
        self.id = run_id or uuid.uuid4().hex
        if name is not None:
            self.name = name
        else:
            try:
                self.name = utils.generate_readable_name(
                    self._safe_get_existing_runs(), space_id
                )
            except Exception as e:
                self._warn_once(
                    "init-run-name",
                    f"trackio.init() could not generate a run name: {e}. Falling back to a random name.",
                )
                self.name = f"trackio-run-{uuid.uuid4().hex[:8]}"
        self.group = group
        try:
            self.config = utils.to_json_safe(config or {})
        except Exception as e:
            self._warn_once(
                "init-config",
                f"trackio.init() failed to serialize the run config: {e}. Continuing without config.",
            )
            self.config = {}

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
        max_step = self._safe_get_max_step_for_run()
        self._next_step = 0 if max_step is None else max_step + 1
        self._has_local_buffer = False

        self._is_local = space_id is None
        self._webhook_url = webhook_url or os.environ.get("TRACKIO_WEBHOOK_URL")
        self._webhook_min_level = resolve_webhook_min_level(
            webhook_min_level or os.environ.get("TRACKIO_WEBHOOK_MIN_LEVEL")
        )

        if self._is_local:
            self._start_background_thread(
                "_local_sender_thread",
                self._local_batch_sender,
                warning_key="local-sender-thread",
                description="local Trackio logging thread",
            )
        else:
            self._start_background_thread(
                "_client_thread",
                self._init_client_background,
                warning_key="remote-sender-thread",
                description="remote Trackio logging thread",
            )

        self._gpu_monitor: "GpuMonitor | AppleGpuMonitor | None" = None
        if auto_log_gpu:
            try:
                if gpu_available():
                    self._gpu_monitor = GpuMonitor(self, interval=gpu_log_interval)
                    self._gpu_monitor.start()
                elif apple_gpu_available():
                    self._gpu_monitor = AppleGpuMonitor(self, interval=gpu_log_interval)
                    self._gpu_monitor.start()
            except Exception as e:
                self._warn_once(
                    "gpu-monitor",
                    f"trackio.init() failed to start automatic GPU logging: {e}. Continuing without system metric auto-logging.",
                )

    def _get_username(self) -> str | None:
        try:
            return _get_default_namespace()
        except Exception:
            return None

    def _warn_once(self, key: str, message: str) -> None:
        with self._warning_lock:
            if key in self._warned_failures:
                return
            self._warned_failures.add(key)
        _emit_nonfatal_warning(message)

    def _safe_get_existing_runs(self) -> list[str]:
        try:
            return SQLiteStorage.get_runs(self.project)
        except Exception as e:
            self._warn_once(
                "init-existing-runs",
                f"trackio.init() could not inspect existing runs for project '{self.project}': {e}. Continuing without prior-run metadata.",
            )
            return []

    def _safe_get_max_step_for_run(self) -> int | None:
        try:
            return SQLiteStorage.get_max_step_for_run(
                self.project, self.name, run_id=self.id
            )
        except Exception as e:
            self._warn_once(
                "init-max-step",
                f"trackio.init() could not recover the previous step for run '{self.name}': {e}. Continuing from step 0.",
            )
            return None

    def _start_background_thread(
        self,
        attr_name: str,
        target,
        *,
        warning_key: str,
        description: str,
    ) -> bool:
        try:
            thread = threading.Thread(target=target, daemon=True)
            setattr(self, attr_name, thread)
            thread.start()
            return True
        except Exception as e:
            setattr(self, attr_name, None)
            self._warn_once(
                warning_key,
                f"trackio failed to start the {description}: {e}. Logging will continue in degraded mode.",
            )
            return False

    def _thread_is_alive(self, attr_name: str) -> bool:
        thread = getattr(self, attr_name, None)
        return isinstance(thread, threading.Thread) and thread.is_alive()

    def _flush_queues_inline(self) -> None:
        if self._is_local:
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
            return

        if self._queued_logs:
            logs_to_send = self._queued_logs.copy()
            self._queued_logs.clear()
            self._persist_logs_locally(logs_to_send)

        if self._queued_system_logs:
            system_logs_to_send = self._queued_system_logs.copy()
            self._queued_system_logs.clear()
            self._persist_system_logs_locally(system_logs_to_send)

        if self._queued_uploads:
            uploads_to_send = self._queued_uploads.copy()
            self._queued_uploads.clear()
            self._persist_uploads_locally(uploads_to_send)

        if self._queued_alerts:
            alerts_to_send = self._queued_alerts.copy()
            self._queued_alerts.clear()
            self._write_alerts_to_sqlite(alerts_to_send)

    def _local_batch_sender(self):
        while (
            not self._stop_flag.is_set()
            or len(self._queued_logs) > 0
            or len(self._queued_system_logs) > 0
            or len(self._queued_alerts) > 0
        ):
            if not self._stop_flag.is_set():
                self._stop_flag.wait(timeout=BATCH_SEND_INTERVAL)

            try:
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
            except Exception as e:
                self._warn_once(
                    "local-sender-loop",
                    f"trackio's local logging thread hit an internal error: {e}. User code will continue, but some Trackio data may be dropped.",
                )

    def _write_logs_to_sqlite(self, logs: list[LogEntry]):
        try:
            logs_by_run: dict[tuple, dict] = {}
            for entry in logs:
                key = (entry["project"], entry["run"], entry.get("run_id"))
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

            for (project, run, run_id), data in logs_by_run.items():
                has_log_ids = any(lid is not None for lid in data["log_ids"])
                SQLiteStorage.bulk_log(
                    project=project,
                    run=run,
                    run_id=run_id,
                    metrics_list=data["metrics"],
                    steps=data["steps"],
                    config=data["config"],
                    log_ids=data["log_ids"] if has_log_ids else None,
                )
        except Exception as e:
            self._warn_once(
                "write-logs-to-sqlite",
                f"trackio failed to flush metric logs for run '{self.name}': {e}. User code will continue, but this batch could not be persisted.",
            )

    def _write_system_logs_to_sqlite(self, logs: list[SystemLogEntry]):
        try:
            logs_by_run: dict[tuple, dict] = {}
            for entry in logs:
                key = (entry["project"], entry["run"], entry.get("run_id"))
                if key not in logs_by_run:
                    logs_by_run[key] = {"metrics": [], "timestamps": [], "log_ids": []}
                logs_by_run[key]["metrics"].append(entry["metrics"])
                logs_by_run[key]["timestamps"].append(entry.get("timestamp"))
                logs_by_run[key]["log_ids"].append(entry.get("log_id"))

            for (project, run, run_id), data in logs_by_run.items():
                has_log_ids = any(lid is not None for lid in data["log_ids"])
                SQLiteStorage.bulk_log_system(
                    project=project,
                    run=run,
                    run_id=run_id,
                    metrics_list=data["metrics"],
                    timestamps=data["timestamps"],
                    log_ids=data["log_ids"] if has_log_ids else None,
                )
        except Exception as e:
            self._warn_once(
                "write-system-logs-to-sqlite",
                f"trackio failed to flush system logs for run '{self.name}': {e}. User code will continue, but this batch could not be persisted.",
            )

    def _write_alerts_to_sqlite(self, alerts: list[AlertEntry]):
        try:
            alerts_by_run: dict[tuple, dict] = {}
            for entry in alerts:
                key = (entry["project"], entry["run"], entry.get("run_id"))
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

            for (project, run, run_id), data in alerts_by_run.items():
                has_alert_ids = any(aid is not None for aid in data["alert_ids"])
                SQLiteStorage.bulk_alert(
                    project=project,
                    run=run,
                    run_id=run_id,
                    titles=data["titles"],
                    texts=data["texts"],
                    levels=data["levels"],
                    steps=data["steps"],
                    timestamps=data["timestamps"],
                    alert_ids=data["alert_ids"] if has_alert_ids else None,
                )
        except Exception as e:
            self._warn_once(
                "write-alerts-to-sqlite",
                f"trackio failed to flush alerts for run '{self.name}': {e}. User code will continue, but this batch could not be persisted.",
            )

    def _batch_sender(self):
        consecutive_failures = 0
        while (
            not self._stop_flag.is_set()
            or len(self._queued_logs) > 0
            or len(self._queued_system_logs) > 0
            or len(self._queued_uploads) > 0
            or len(self._queued_alerts) > 0
            or self._has_local_buffer
        ):
            if not self._stop_flag.is_set():
                if consecutive_failures:
                    sleep_time = min(
                        BATCH_SEND_INTERVAL * (2**consecutive_failures), MAX_BACKOFF
                    )
                else:
                    sleep_time = BATCH_SEND_INTERVAL
                self._stop_flag.wait(timeout=sleep_time)
            elif self._has_local_buffer:
                self._stop_flag.wait(timeout=BATCH_SEND_INTERVAL)

            try:
                with self._client_lock:
                    if self._client is None:
                        if self._stop_flag.is_set():
                            if self._queued_logs:
                                self._persist_logs_locally(self._queued_logs)
                                self._queued_logs.clear()
                            if self._queued_system_logs:
                                self._persist_system_logs_locally(
                                    self._queued_system_logs
                                )
                                self._queued_system_logs.clear()
                            if self._queued_uploads:
                                self._persist_uploads_locally(self._queued_uploads)
                                self._queued_uploads.clear()
                            if self._queued_alerts:
                                self._write_alerts_to_sqlite(self._queued_alerts)
                                self._queued_alerts.clear()
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
            except Exception as e:
                consecutive_failures += 1
                self._warn_once(
                    "remote-sender-loop",
                    f"trackio's remote logging thread hit an internal error: {e}. User code will continue while Trackio retries in the background.",
                )

    def _persist_logs_locally(self, logs: list[LogEntry]):
        if not self._space_id:
            return
        try:
            logs_by_run: dict[tuple, dict] = {}
            for entry in logs:
                key = (entry["project"], entry["run"], entry.get("run_id"))
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

            for (project, run, run_id), data in logs_by_run.items():
                SQLiteStorage.bulk_log(
                    project=project,
                    run=run,
                    run_id=run_id,
                    metrics_list=data["metrics"],
                    steps=data["steps"],
                    log_ids=data["log_ids"],
                    config=data["config"],
                    space_id=self._space_id,
                )
            self._has_local_buffer = True
        except Exception as e:
            self._warn_once(
                "persist-logs-locally",
                f"trackio could not persist failed remote metric logs locally for run '{self.name}': {e}. User code will continue, but this batch could be lost.",
            )

    def _persist_system_logs_locally(self, logs: list[SystemLogEntry]):
        if not self._space_id:
            return
        try:
            logs_by_run: dict[tuple, dict] = {}
            for entry in logs:
                key = (entry["project"], entry["run"], entry.get("run_id"))
                if key not in logs_by_run:
                    logs_by_run[key] = {"metrics": [], "timestamps": [], "log_ids": []}
                logs_by_run[key]["metrics"].append(entry["metrics"])
                logs_by_run[key]["timestamps"].append(entry.get("timestamp"))
                logs_by_run[key]["log_ids"].append(entry.get("log_id"))

            for (project, run, run_id), data in logs_by_run.items():
                SQLiteStorage.bulk_log_system(
                    project=project,
                    run=run,
                    run_id=run_id,
                    metrics_list=data["metrics"],
                    timestamps=data["timestamps"],
                    log_ids=data["log_ids"],
                    space_id=self._space_id,
                )
            self._has_local_buffer = True
        except Exception as e:
            self._warn_once(
                "persist-system-logs-locally",
                f"trackio could not persist failed remote system logs locally for run '{self.name}': {e}. User code will continue, but this batch could be lost.",
            )

    def _persist_uploads_locally(self, uploads: list[UploadEntry]):
        if not self._space_id:
            return
        try:
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
                    run_id=entry.get("run_id"),
                    run_name=entry.get("run"),
                    step=entry.get("step"),
                    file_path=file_path,
                    relative_path=entry.get("relative_path"),
                )
            self._has_local_buffer = True
        except Exception as e:
            self._warn_once(
                "persist-uploads-locally",
                f"trackio could not persist failed remote file uploads locally for run '{self.name}': {e}. User code will continue, but some artifacts could be lost.",
            )

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
                                "run_id": u.get("run_id"),
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
        except Exception as e:
            self._warn_once(
                "flush-local-buffer",
                f"trackio could not flush buffered remote data for run '{self.name}': {e}. It will retry later if possible.",
            )

    def _init_client_background(self):
        if self._client is None:
            fib = utils.fibo()
            for sleep_coefficient in fib:
                if self._stop_flag.is_set():
                    break
                try:
                    client = RemoteClient(
                        self.url,
                        hf_token=huggingface_hub.utils.get_token(),
                        verbose=False,
                    )

                    with self._client_lock:
                        self._client = client
                    break
                except Exception:
                    pass
                sleep_time = min(0.1 * sleep_coefficient, MAX_BACKOFF)
                self._stop_flag.wait(timeout=sleep_time)

        self._batch_sender()

    def _queue_upload(
        self,
        file_path,
        step: int | None,
        relative_path: str | None = None,
        use_run_name: bool = True,
    ):
        try:
            if self._is_local:
                self._save_upload_locally(file_path, step, relative_path, use_run_name)
            else:
                upload_entry: UploadEntry = {
                    "project": self.project,
                    "run": self.name if use_run_name else None,
                    "run_id": self.id if use_run_name else None,
                    "step": step,
                    "relative_path": relative_path,
                    "uploaded_file": handle_file(file_path),
                }
                with self._client_lock:
                    self._queued_uploads.append(upload_entry)
                    self._ensure_sender_alive()
                    if not self._thread_is_alive("_client_thread"):
                        self._flush_queues_inline()
        except Exception as e:
            self._warn_once(
                "queue-upload",
                f"trackio could not queue the artifact '{file_path}' for run '{self.name}': {e}. User code will continue, but this artifact could be missing.",
            )

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
                                absolute_path = MEDIA_DIR / file_path
                                self._queue_upload(absolute_path, step)

    def _ensure_sender_alive(self):
        if self._is_local:
            if (
                not self._thread_is_alive("_local_sender_thread")
                and not self._stop_flag.is_set()
            ):
                self._start_background_thread(
                    "_local_sender_thread",
                    self._local_batch_sender,
                    warning_key="local-sender-thread-restart",
                    description="local Trackio logging thread",
                )
        else:
            if (
                not self._thread_is_alive("_client_thread")
                and not self._stop_flag.is_set()
            ):
                self._start_background_thread(
                    "_client_thread",
                    self._init_client_background,
                    warning_key="remote-sender-thread-restart",
                    description="remote Trackio logging thread",
                )

    def log(self, metrics: dict, step: int | None = None):
        try:
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
                _emit_nonfatal_warning(
                    f"Reserved keys renamed: {renamed_keys} → '__{{key}}'"
                )

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
                "run_id": self.id,
                "metrics": metrics,
                "step": step,
                "config": config_to_log,
                "log_id": uuid.uuid4().hex,
            }

            with self._client_lock:
                self._queued_logs.append(log_entry)
                self._ensure_sender_alive()
                if not self._thread_is_alive(
                    "_local_sender_thread" if self._is_local else "_client_thread"
                ):
                    self._flush_queues_inline()
        except Exception as e:
            _emit_nonfatal_warning(f"trackio.log() failed to process metrics: {e}")

    def alert(
        self,
        title: str,
        text: str | None = None,
        level: AlertLevel = AlertLevel.WARN,
        step: int | None = None,
        webhook_url: str | None = None,
    ):
        try:
            if step is None:
                step = max(self._next_step - 1, 0)
            timestamp = datetime.now(timezone.utc).isoformat()

            print(format_alert_terminal(level, title, text, step))

            alert_entry: AlertEntry = {
                "project": self.project,
                "run": self.name,
                "run_id": self.id,
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
                if not self._thread_is_alive(
                    "_local_sender_thread" if self._is_local else "_client_thread"
                ):
                    self._flush_queues_inline()

            url = webhook_url or self._webhook_url
            if url and should_send_webhook(level, self._webhook_min_level):
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
        except Exception as e:
            _emit_nonfatal_warning(f"trackio.alert() failed: {e}")

    def log_system(self, metrics: dict):
        try:
            metrics = utils.serialize_values(metrics)
            timestamp = datetime.now(timezone.utc).isoformat()

            system_log_entry: SystemLogEntry = {
                "project": self.project,
                "run": self.name,
                "run_id": self.id,
                "metrics": metrics,
                "timestamp": timestamp,
                "log_id": uuid.uuid4().hex,
            }

            with self._client_lock:
                self._queued_system_logs.append(system_log_entry)
                self._ensure_sender_alive()
                if not self._thread_is_alive(
                    "_local_sender_thread" if self._is_local else "_client_thread"
                ):
                    self._flush_queues_inline()
        except Exception as e:
            _emit_nonfatal_warning(f"trackio.log_system() failed: {e}")

    def finish(self):
        try:
            if self._gpu_monitor is not None:
                try:
                    self._gpu_monitor.stop()
                except Exception as e:
                    self._warn_once(
                        "finish-gpu-monitor",
                        f"trackio.finish() could not stop automatic GPU logging cleanly: {e}.",
                    )

            self._stop_flag.set()

            if self._is_local:
                if self._local_sender_thread is not None:
                    print("* Run finished. Uploading logs to Trackio (please wait...)")
                    self._local_sender_thread.join(timeout=30)
                    if self._local_sender_thread.is_alive():
                        _emit_nonfatal_warning(
                            "Could not flush all logs within 30s. Some data may be buffered locally."
                        )
                else:
                    with self._client_lock:
                        self._flush_queues_inline()
            else:
                if self._client_thread is not None:
                    print(
                        "* Run finished. Uploading logs to Trackio Space (please wait...)"
                    )
                    self._client_thread.join(timeout=30)
                    if self._client_thread.is_alive():
                        _emit_nonfatal_warning(
                            "Could not flush all logs within 30s. Some data may be buffered locally."
                        )
                else:
                    with self._client_lock:
                        self._flush_queues_inline()

                try:
                    has_pending = SQLiteStorage.has_pending_data(self.project)
                except Exception as e:
                    self._warn_once(
                        "finish-pending-data",
                        f"trackio.finish() could not inspect pending buffered logs for project '{self.project}': {e}.",
                    )
                    has_pending = False

                if has_pending:
                    _emit_nonfatal_warning(
                        f"* Some logs could not be sent to the Space (it may still be starting up). "
                        f"They have been saved locally and will be sent automatically next time you call: "
                        f'trackio.init(project="{self.project}", space_id="{self._space_id}")'
                    )
        except Exception as e:
            _emit_nonfatal_warning(f"trackio.finish() failed: {e}")
