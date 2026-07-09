import os
import shutil
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import huggingface_hub
from gradio_client import handle_file

from trackio import cas, fragments, references, utils
from trackio.alerts import (
    AlertLevel,
    format_alert_terminal,
    resolve_webhook_min_level,
    send_webhook,
    should_send_webhook,
)
from trackio.apple_gpu import AppleGpuMonitor, apple_gpu_available
from trackio.artifact import Artifact
from trackio.cpu import CpuMonitor
from trackio.gpu import GpuMonitor, gpu_available
from trackio.histogram import Histogram
from trackio.markdown import Markdown
from trackio.media import TrackioMedia, get_project_media_path
from trackio.pending_uploads import classify_pending_uploads, replay_pending_uploads
from trackio.remote_client import RemoteClient, is_transient_remote_error
from trackio.sqlite_storage import SQLiteStorage
from trackio.table import Table
from trackio.trace import Trace
from trackio.typehints import AlertEntry, LogEntry, SystemLogEntry, UploadEntry
from trackio.utils import MEDIA_DIR, _emit_nonfatal_warning, _get_default_namespace

BATCH_SEND_INTERVAL = 0.5
MAX_BACKOFF = 30
BUCKET_FLUSH_INTERVAL = 30
ARTIFACT_LOG_RETRY_BACKOFFS = (0.5, 1.0, 2.0)


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
        bucket_id: str | None = None,
        server_base_url: str | None = None,
        write_token: str | None = None,
        existing_runs: list[str] | None = None,
        initial_last_step: int | None = None,
        auto_log_gpu: bool = False,
        gpu_log_interval: float = 10.0,
        auto_log_cpu: bool = False,
        cpu_log_interval: float = 10.0,
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
            bucket_id: The HF Bucket ID attached to the Space, if any. When set,
                logs that cannot be delivered to the Space are written as JSONL
                fragments directly to the Bucket inbox so they survive ephemeral
                environments; the Space imports them once it is running.
            existing_runs: Optional pre-fetched run names for this project. Used to
                avoid redundant storage or remote lookups during init.
            initial_last_step: Optional pre-fetched last step for a resumed run.
            auto_log_gpu: Whether to automatically log GPU metrics (utilization,
                memory, temperature) at regular intervals.
            gpu_log_interval: The interval in seconds between GPU metric logs.
                Only used when auto_log_gpu is True.
            auto_log_cpu: Whether to automatically log CPU and RAM metrics
                (utilization, memory, disk I/O, network I/O, sensors) at regular
                intervals.
            cpu_log_interval: The interval in seconds between CPU metric logs.
                Only used when auto_log_cpu is True.
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
        self._bucket_id = bucket_id if space_id is not None else None
        self._server_base_url = server_base_url
        self._write_token = write_token
        self._remote_storage_key = space_id or server_base_url
        self._storage_mode = utils.get_storage_mode()
        self._fragment_writer = fragments.FragmentWriter()
        self._last_bucket_flush: float | None = None
        self._spilled_metric_ids: set[int] = set()
        self._spilled_system_ids: set[int] = set()
        self.id = run_id or uuid.uuid4().hex
        self._existing_runs = existing_runs
        self._initial_last_step = initial_last_step
        if name is not None:
            self.name = name
        else:
            try:
                self.name = utils.generate_readable_name(
                    self._safe_get_existing_runs(), self._space_id
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

        self._is_local = space_id is None and server_base_url is None
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
                    self._gpu_monitor = AppleGpuMonitor(
                        self,
                        interval=gpu_log_interval,
                        include_cpu_metrics=not auto_log_cpu,
                    )
                    self._gpu_monitor.start()
            except Exception as e:
                self._warn_once(
                    "gpu-monitor",
                    f"trackio.init() failed to start automatic GPU logging: {e}. Continuing without system metric auto-logging.",
                )

        self._cpu_monitor: "CpuMonitor | None" = None
        if auto_log_cpu:
            try:
                self._cpu_monitor = CpuMonitor(self, interval=cpu_log_interval)
                self._cpu_monitor.start()
            except Exception as e:
                self._warn_once(
                    "cpu-monitor",
                    f"trackio.init() failed to start automatic CPU logging: {e}. Continuing without CPU metric auto-logging.",
                )

    def _hf_token_for_remote(self) -> str | None:
        return huggingface_hub.utils.get_token() if self._space_id else None

    def _remote_source_dict(self) -> dict:
        return {
            "space_id": self._space_id,
            "server_base_url": self._server_base_url,
            "write_token": self._write_token,
        }

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
        if self._existing_runs is not None:
            return self._existing_runs
        try:
            return SQLiteStorage.get_runs(self.project)
        except Exception as e:
            self._warn_once(
                "init-existing-runs",
                f"trackio.init() could not inspect existing runs for project '{self.project}': {e}. Continuing without prior-run metadata.",
            )
            return []

    def _safe_get_max_step_for_run(self) -> int | None:
        if self._initial_last_step is not None:
            return self._initial_last_step
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

    def _stamped_records(self, records: list[dict]) -> list[dict]:
        timestamp = datetime.now(timezone.utc).isoformat()
        for record in records:
            if not record.get("timestamp"):
                record["timestamp"] = timestamp
        return records

    def _attach_run_config(self, records: list[dict]) -> list[dict]:
        if not self.config:
            return records
        if any(record.get("config") for record in records):
            return records
        for record in records:
            if record.get("run_id") == self.id:
                record["config"] = utils.to_json_safe(self.config)
                break
        return records

    def _write_records_to_local_inbox(self, records: list[dict], warning_key: str):
        try:
            self._fragment_writer.write_local(self._stamped_records(records))
        except Exception as e:
            self._warn_once(
                warning_key,
                f"trackio failed to write a JSONL fragment for run '{self.name}': {e}. User code will continue, but this batch could not be persisted.",
            )

    def _write_logs_to_sqlite(self, logs: list[LogEntry]):
        if self._storage_mode == "jsonl":
            self._write_records_to_local_inbox(
                [fragments.metric_record(entry) for entry in logs],
                "write-logs-fragment",
            )
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
        if self._storage_mode == "jsonl":
            self._write_records_to_local_inbox(
                [fragments.system_metric_record(entry) for entry in logs],
                "write-system-logs-fragment",
            )
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
        records = [fragments.alert_record(entry) for entry in alerts]
        if self._remote_storage_key and self._bucket_id is not None:
            try:
                self._fragment_writer.write_to_bucket(
                    self._stamped_records(records), self._bucket_id
                )
                return
            except Exception:
                pass
        if self._storage_mode == "jsonl":
            self._write_records_to_local_inbox(records, "write-alerts-fragment")
            return
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
                                hf_token=self._hf_token_for_remote(),
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
                                hf_token=self._hf_token_for_remote(),
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
                                hf_token=self._hf_token_for_remote(),
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
                                hf_token=self._hf_token_for_remote(),
                            )
                        except Exception:
                            self._write_alerts_to_sqlite(alerts_to_send)
                            failed = True

                    if failed:
                        consecutive_failures += 1
                    else:
                        consecutive_failures = 0
                        if self._has_local_buffer:
                            flushed = self._flush_local_buffer()
                            if (
                                not flushed
                                and self._stop_flag.is_set()
                                and self._bucket_id is not None
                            ):
                                return
            except Exception as e:
                consecutive_failures += 1
                self._warn_once(
                    "remote-sender-loop",
                    f"trackio's remote logging thread hit an internal error: {e}. User code will continue while Trackio retries in the background.",
                )

    def _persist_records_as_fragments(self, records: list[dict], warning_key: str):
        records = self._stamped_records(records)
        if self._bucket_id is not None:
            try:
                self._fragment_writer.write_to_bucket(records, self._bucket_id)
                return
            except Exception:
                pass
        self._write_records_to_local_inbox(records, warning_key)

    def _persist_logs_locally(self, logs: list[LogEntry]):
        if not self._remote_storage_key:
            return
        if self._storage_mode == "jsonl":
            self._persist_records_as_fragments(
                self._attach_run_config(
                    [fragments.metric_record(entry) for entry in logs]
                ),
                "persist-logs-fragment",
            )
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
                    space_id=self._remote_storage_key,
                )
            self._has_local_buffer = True
        except Exception as e:
            self._warn_once(
                "persist-logs-locally",
                f"trackio could not persist failed remote metric logs locally for run '{self.name}': {e}. User code will continue, but this batch could be lost.",
            )

    def _persist_system_logs_locally(self, logs: list[SystemLogEntry]):
        if not self._remote_storage_key:
            return
        if self._storage_mode == "jsonl":
            self._persist_records_as_fragments(
                [fragments.system_metric_record(entry) for entry in logs],
                "persist-system-logs-fragment",
            )
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
                    space_id=self._remote_storage_key,
                )
            self._has_local_buffer = True
        except Exception as e:
            self._warn_once(
                "persist-system-logs-locally",
                f"trackio could not persist failed remote system logs locally for run '{self.name}': {e}. User code will continue, but this batch could be lost.",
            )

    @staticmethod
    def _upload_entry_file_path(entry: UploadEntry) -> str:
        file_data = entry.get("uploaded_file")
        if isinstance(file_data, dict):
            return file_data.get("path", "")
        elif hasattr(file_data, "path"):
            return str(file_data.path)
        return str(file_data)

    def _persist_uploads_locally(self, uploads: list[UploadEntry]):
        if not self._remote_storage_key:
            return
        if self._storage_mode == "jsonl" and self._bucket_id is not None:
            try:
                fragments.upload_media_files_to_bucket(
                    self._bucket_id,
                    [
                        {
                            "project": entry["project"],
                            "run": entry.get("run"),
                            "step": entry.get("step"),
                            "relative_path": entry.get("relative_path"),
                            "file_path": self._upload_entry_file_path(entry),
                        }
                        for entry in uploads
                    ],
                )
                return
            except Exception as e:
                self._warn_once(
                    "persist-uploads-fragment",
                    f"trackio could not upload media files to Bucket '{self._bucket_id}' for run '{self.name}': {e}. They will be kept in the local pending buffer instead.",
                )
        try:
            for entry in uploads:
                file_path = self._upload_entry_file_path(entry)
                SQLiteStorage.add_pending_upload(
                    project=entry["project"],
                    space_id=self._remote_storage_key,
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

    def _warn_missing_uploads(self, count: int, sample: str) -> None:
        self._warn_once(
            "pending-uploads-missing-files",
            f"trackio dropped {count} pending upload(s) whose local files no "
            f"longer exist (e.g. {sample!r}). Data for these uploads was not "
            "uploaded.",
        )

    def _send_pending_uploads_to_server(self, buffered: dict) -> None:
        """Group buffered pending_uploads by kind and POST to the right endpoints."""
        replay_pending_uploads(
            buffered,
            self.project,
            predict=self._client.predict,
            hf_token=self._hf_token_for_remote(),
            warn_missing=self._warn_missing_uploads,
        )

    def _flush_local_buffer(self) -> bool:
        try:
            buffered_logs = SQLiteStorage.get_pending_logs(self.project)
            if buffered_logs:
                self._client.predict(
                    api_name="/bulk_log",
                    logs=buffered_logs["logs"],
                    hf_token=self._hf_token_for_remote(),
                )
                SQLiteStorage.clear_pending_logs(self.project, buffered_logs["ids"])

            buffered_sys = SQLiteStorage.get_pending_system_logs(self.project)
            if buffered_sys:
                self._client.predict(
                    api_name="/bulk_log_system",
                    logs=buffered_sys["logs"],
                    hf_token=self._hf_token_for_remote(),
                )
                SQLiteStorage.clear_pending_system_logs(
                    self.project, buffered_sys["ids"]
                )

            buffered_uploads = SQLiteStorage.get_pending_uploads(self.project)
            if buffered_uploads:
                self._send_pending_uploads_to_server(buffered_uploads)

            self._has_local_buffer = False
            return True
        except Exception as e:
            self._warn_once(
                "flush-local-buffer",
                f"trackio could not flush buffered remote data for run '{self.name}': {e}. It will retry later if possible.",
            )
            return False

    def _unspilled_pending(
        self, pending: dict | None, spilled_ids: set[int]
    ) -> list[dict]:
        if not pending:
            return []
        return [
            entry
            for entry_id, entry in zip(pending["ids"], pending["logs"])
            if entry_id not in spilled_ids
        ]

    def _flush_pending_uploads_to_bucket(self) -> None:
        pending = SQLiteStorage.get_pending_uploads(self.project)
        if not pending:
            return
        classified = classify_pending_uploads(pending)
        missing = classified["missing"]
        if missing["ids"]:
            self._warn_missing_uploads(len(missing["ids"]), missing["paths"][0])
            SQLiteStorage.clear_pending_uploads(self.project, missing["ids"])
        media = classified["media"]
        if media:
            fragments.upload_media_files_to_bucket(
                self._bucket_id, [upload for upload, _ in media]
            )
            SQLiteStorage.clear_pending_uploads(
                self.project, [upload_id for _, upload_id in media]
            )
        blobs = classified["artifact_blobs"]
        if blobs:
            fragments.upload_artifact_blobs_to_bucket(
                self._bucket_id, [upload for upload, _ in blobs]
            )
            SQLiteStorage.clear_pending_uploads(
                self.project, [upload_id for _, upload_id in blobs]
            )

    def _spill_pending_to_bucket(self):
        """
        Spill buffered rows to the Bucket while the Space is unreachable. Metric
        and system rows are written without clearing them, so the normal
        /bulk_log replay still happens once the Space is reachable (it
        deduplicates by log_id). Media and artifact-blob uploads are sent to
        their bucket paths and cleared, since they are delivered through the
        bucket rather than replayed to the Space.
        """
        try:
            pending = SQLiteStorage.get_pending_logs(self.project)
            entries = self._unspilled_pending(pending, self._spilled_metric_ids)
            if entries:
                records = self._attach_run_config(
                    [fragments.metric_record(entry) for entry in entries]
                )
                self._fragment_writer.write_to_bucket(records, self._bucket_id)
                self._spilled_metric_ids.update(pending["ids"])

            pending_sys = SQLiteStorage.get_pending_system_logs(self.project)
            entries = self._unspilled_pending(pending_sys, self._spilled_system_ids)
            if entries:
                records = [fragments.system_metric_record(entry) for entry in entries]
                self._fragment_writer.write_to_bucket(records, self._bucket_id)
                self._spilled_system_ids.update(pending_sys["ids"])

            self._flush_pending_uploads_to_bucket()
        except Exception as e:
            self._warn_once(
                "bucket-spill",
                f"trackio could not upload buffered logs to Bucket '{self._bucket_id}': {e}. It will retry later if possible.",
            )

    def _drain_pending_to_bucket(self):
        if self._bucket_id is None or not self._has_local_buffer:
            return
        try:
            pending = SQLiteStorage.get_pending_logs(self.project)
            if pending:
                entries = self._unspilled_pending(pending, self._spilled_metric_ids)
                if entries:
                    records = self._attach_run_config(
                        [fragments.metric_record(entry) for entry in entries]
                    )
                    self._fragment_writer.write_to_bucket(records, self._bucket_id)
                SQLiteStorage.clear_pending_logs(self.project, pending["ids"])
                self._spilled_metric_ids.update(pending["ids"])

            pending_sys = SQLiteStorage.get_pending_system_logs(self.project)
            if pending_sys:
                entries = self._unspilled_pending(pending_sys, self._spilled_system_ids)
                if entries:
                    records = [
                        fragments.system_metric_record(entry) for entry in entries
                    ]
                    self._fragment_writer.write_to_bucket(records, self._bucket_id)
                SQLiteStorage.clear_pending_system_logs(
                    self.project, pending_sys["ids"]
                )
                self._spilled_system_ids.update(pending_sys["ids"])

            self._flush_pending_uploads_to_bucket()

            self._has_local_buffer = SQLiteStorage.has_pending_data(self.project)
        except Exception as e:
            self._warn_once(
                "bucket-drain",
                f"trackio could not upload buffered logs to Bucket '{self._bucket_id}': {e}. It will retry later if possible.",
            )

    def _spill_queues_while_waiting(self):
        if self._bucket_id is None:
            return
        if not (
            self._queued_logs
            or self._queued_system_logs
            or self._queued_uploads
            or self._queued_alerts
            or self._has_local_buffer
        ):
            return
        now = time.monotonic()
        if (
            self._last_bucket_flush is not None
            and now - self._last_bucket_flush < BUCKET_FLUSH_INTERVAL
        ):
            return
        self._last_bucket_flush = now
        with self._client_lock:
            if self._client is not None:
                return
            self._flush_queues_inline()
        self._spill_pending_to_bucket()

    def _wait_for_client_ready(self, timeout: float = 60.0) -> None:
        """Block until `self._client` is initialized by `_init_client_background`."""
        deadline = time.monotonic() + timeout
        while self._client is None:
            if self._stop_flag.is_set():
                raise RuntimeError(
                    "trackio run is finishing; cannot wait for remote client"
                )
            if time.monotonic() >= deadline:
                raise RuntimeError(f"trackio remote client not ready after {timeout}s")
            time.sleep(0.1)

    def _drain_pending_uploads(self) -> None:
        """Synchronously flush pending_uploads (both kinds). Raises on failure."""
        with self._client_lock:
            if self._client is None:
                raise RuntimeError(
                    "trackio remote client not ready; cannot drain pending_uploads"
                )
            buffered = SQLiteStorage.get_pending_uploads(self.project)
            if not buffered:
                return
            self._send_pending_uploads_to_server(buffered)

    def _init_client_background(self):
        if self._client is None:
            fib = utils.fibo()
            for sleep_coefficient in fib:
                if self._stop_flag.is_set():
                    break
                try:
                    if self._server_base_url is not None:
                        client = RemoteClient(
                            self._server_base_url,
                            hf_token=None,
                            write_token=self._write_token,
                            verbose=False,
                        )
                    else:
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
                try:
                    self._spill_queues_while_waiting()
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
        if self._space_id or self._server_base_url:
            self._queue_upload(value._get_absolute_file_path(), step)
        return value._to_dict()

    def _scan_and_queue_media_uploads(self, value: Any, step: int | None):
        if not self._space_id and not self._server_base_url:
            return
        if isinstance(value, dict):
            if value.get("_type") in [
                "trackio.image",
                "trackio.video",
                "trackio.audio",
            ]:
                file_path = value.get("file_path")
                if file_path:
                    absolute_path = MEDIA_DIR / file_path
                    self._queue_upload(absolute_path, step)
                return
            for nested in value.values():
                self._scan_and_queue_media_uploads(nested, step)
            return
        if isinstance(value, list):
            for nested in value:
                self._scan_and_queue_media_uploads(nested, step)

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
            media_step = step if step is not None else self._next_step
            for key, value in metrics.items():
                if isinstance(value, Table):
                    metrics[key] = value._to_dict(
                        project=self.project, run=self.name, step=media_step
                    )
                    self._scan_and_queue_media_uploads(metrics[key], media_step)
                elif isinstance(value, Trace):
                    metrics[key] = value._to_dict(
                        project=self.project, run=self.name, step=media_step
                    )
                    self._scan_and_queue_media_uploads(metrics[key], media_step)
                elif (
                    isinstance(value, list)
                    and value
                    and all(isinstance(item, Trace) for item in value)
                ):
                    converted = [
                        item._to_dict(
                            project=self.project, run=self.name, step=media_step
                        )
                        for item in value
                    ]
                    metrics[key] = converted
                    for item in converted:
                        self._scan_and_queue_media_uploads(item, media_step)
                elif isinstance(value, Histogram):
                    metrics[key] = value._to_dict()
                elif isinstance(value, Markdown):
                    metrics[key] = value._to_dict()
                elif isinstance(value, TrackioMedia):
                    metrics[key] = self._process_media(value, media_step)
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

    def _artifact_log_with_retry(self, **kwargs) -> dict:
        manifest = kwargs.get("manifest", [])
        ref_entries = [
            entry for entry in manifest if references.is_reference_entry(entry)
        ]
        upgrade_hint = (
            "The server likely predates artifact references. To support "
            "add_reference, you need to upgrade trackio to a more recent "
            "release."
        )
        attempts = len(ARTIFACT_LOG_RETRY_BACKOFFS) + 1
        for attempt in range(attempts):
            if attempt > 0:
                time.sleep(ARTIFACT_LOG_RETRY_BACKOFFS[attempt - 1])
            try:
                with self._client_lock:
                    record = self._client.predict(api_name="/artifact_log", **kwargs)
            except Exception as e:
                if attempt == attempts - 1 or not is_transient_remote_error(e):
                    message = str(e)
                    pre_reference_rejection = ref_entries and (
                        "Invalid sha256 digest" in message
                        or (
                            "blobs not on server" in message
                            and any(entry["digest"] in message for entry in ref_entries)
                        )
                    )
                    if pre_reference_rejection:
                        raise RuntimeError(
                            "The remote trackio server rejected this artifact's "
                            f"reference entries ({message}). {upgrade_hint} "
                            "Alternatively, log this artifact without "
                            "add_reference entries."
                        ) from e
                    raise
            else:
                stored = record.get("manifest")
                stored_ref_paths = {
                    entry["path"]
                    for entry in (stored if isinstance(stored, list) else [])
                    if isinstance(entry, dict) and references.is_reference_entry(entry)
                }
                dropped = sorted(
                    {entry["path"] for entry in ref_entries} - stored_ref_paths
                )
                if dropped:
                    preview = dropped[:5]
                    suffix = "..." if len(dropped) > 5 else ""
                    raise RuntimeError(
                        "The remote trackio server stored this artifact's "
                        f"reference entries as plain file entries "
                        f"({preview}{suffix}), dropping their reference URIs. "
                        f"{upgrade_hint} Then re-log this artifact."
                    )
                return record

    def log_artifact(
        self,
        artifact_or_path: Artifact | str | Path,
        name: str | None = None,
        type: str | None = None,
        aliases: list[str] | None = None,
    ) -> Artifact:
        if isinstance(artifact_or_path, Artifact):
            if name is not None or type is not None:
                raise ValueError(
                    "name/type can only be passed when logging a path; "
                    "set them on the Artifact instead."
                )
            artifact = artifact_or_path
        else:
            path = Path(artifact_or_path)
            artifact = Artifact(
                name=name or path.name,
                type=type or "unspecified",
            )
            if path.is_dir():
                artifact.add_dir(path)
            else:
                artifact.add_file(path)

        if artifact._logged:
            raise RuntimeError(
                "Artifact has already been logged or fetched; "
                "construct a new Artifact() to log again."
            )

        user_aliases = cas.validate_aliases(aliases)

        manifest = artifact._build_manifest(self.project)

        if self._is_local:
            record = SQLiteStorage.commit_artifact_version(
                project=self.project,
                name=artifact.name,
                type=artifact.type,
                description=artifact.description,
                manifest=manifest,
                metadata=artifact.metadata,
                aliases=user_aliases,
                run_name=self.name,
                run_id=self.id,
            )
        else:
            self._wait_for_client_ready()

            file_entries = [e for e in manifest if not references.is_reference_entry(e)]
            digests = [e["digest"] for e in file_entries]
            with self._client_lock:
                present_response = self._client.predict(
                    api_name="/check_artifact_blobs",
                    project=self.project,
                    digests=digests,
                    hf_token=self._hf_token_for_remote(),
                )
            present = set((present_response or {}).get("present", []))

            SQLiteStorage.enqueue_artifact_blob_uploads(
                project=self.project,
                space_id=self._remote_storage_key,
                blobs=[
                    (
                        entry["digest"],
                        str(cas.blob_path(self.project, entry["digest"])),
                    )
                    for entry in file_entries
                    if entry["digest"] not in present
                ],
                run_name=self.name,
                run_id=self.id,
            )

            self._drain_pending_uploads()

            record = self._artifact_log_with_retry(
                project=self.project,
                name=artifact.name,
                type=artifact.type,
                description=artifact.description,
                metadata=artifact.metadata,
                manifest=manifest,
                aliases=user_aliases,
                run_name=self.name,
                run_id=self.id,
                hf_token=self._hf_token_for_remote(),
            )

        artifact._hydrate_from_db(
            project=self.project,
            version=record["version"],
            aliases=record["aliases"],
            manifest=record["manifest"],
            manifest_digest=record["manifest_digest"],
            size_bytes=record["size_bytes"],
        )
        if not self._is_local:
            artifact._remote_source = self._remote_source_dict()
        return artifact

    @staticmethod
    def _check_artifact_type(
        spec: str, stored_type: str, expected_type: str | None
    ) -> None:
        if expected_type is not None and stored_type != expected_type:
            raise ValueError(
                f"Artifact {spec!r} has type {stored_type!r}, not {expected_type!r}."
            )

    def use_artifact(
        self,
        artifact_or_name: Artifact | str,
        type: str | None = None,
    ) -> Artifact:
        """Resolve an artifact and record this run as a consumer of it."""
        if isinstance(artifact_or_name, Artifact):
            if not artifact_or_name._logged or artifact_or_name._version is None:
                raise ValueError(
                    "use_artifact() with an Artifact instance requires an "
                    "artifact that has already been logged or fetched."
                )
            spec = f"{artifact_or_name.name}:v{artifact_or_name._version}"
            project = artifact_or_name._project or self.project
        else:
            spec = artifact_or_name
            project = self.project

        if ":" in spec:
            name, version_or_alias = spec.split(":", 1)
            if not version_or_alias:
                raise ValueError(
                    f"Artifact spec {spec!r} has an empty version/alias after ':'. "
                    "Use 'name:vN' or 'name:alias', or drop the colon to get latest."
                )
        else:
            name, version_or_alias = spec, None

        if self._is_local:
            record = SQLiteStorage.get_artifact_manifest(
                project, name, version_or_alias
            )
        else:
            self._wait_for_client_ready()
            with self._client_lock:
                record = self._client.predict(
                    api_name="/get_artifact_manifest",
                    project=project,
                    name=name,
                    spec=version_or_alias,
                )

        if record is None:
            raise ValueError(f"Artifact {spec!r} not found in project {project!r}.")
        self._check_artifact_type(spec, record["type"], type)

        art = Artifact(name=record["name"], type=record["type"])
        art._hydrate_from_db(
            project=project,
            version=record["version"],
            aliases=record["aliases"],
            manifest=record["manifest"],
            manifest_digest=record["manifest_digest"],
            size_bytes=record["size_bytes"],
            description=record["description"],
            metadata=record["metadata"],
        )
        if not self._is_local:
            art._remote_source = self._remote_source_dict()

        try:
            if self._is_local:
                SQLiteStorage.insert_run_artifact_link(
                    project=project,
                    run_name=self.name,
                    run_id=self.id,
                    version_id=record["version_id"],
                    direction="input",
                )
            else:
                with self._client_lock:
                    self._client.predict(
                        api_name="/log_artifact_use",
                        project=project,
                        version_id=record["version_id"],
                        run_name=self.name,
                        run_id=self.id,
                        hf_token=self._hf_token_for_remote(),
                    )
        except Exception as e:
            self._warn_once(
                "artifact-use-lineage",
                f"trackio could not record consumer lineage for {spec!r}: {e}",
            )

        return art

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

            if self._cpu_monitor is not None:
                try:
                    self._cpu_monitor.stop()
                except Exception as e:
                    self._warn_once(
                        "finish-cpu-monitor",
                        f"trackio.finish() could not stop automatic CPU logging cleanly: {e}.",
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
                with self._client_lock:
                    client_connected = self._client is not None
                if self._client_thread is not None:
                    if client_connected:
                        print(
                            "* Run finished. Uploading logs to the remote Trackio server (please wait...)"
                        )
                        self._client_thread.join(timeout=30)
                    else:
                        self._client_thread.join(timeout=5)
                    if self._client_thread.is_alive():
                        with self._client_lock:
                            if self._client is None:
                                self._flush_queues_inline()
                        if client_connected or self._bucket_id is None:
                            _emit_nonfatal_warning(
                                "Could not flush all logs to the remote server in time. Some data may be buffered locally."
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

                if has_pending and self._bucket_id is not None:
                    self._has_local_buffer = True
                    self._drain_pending_to_bucket()
                    has_pending = self._has_local_buffer
                    if not has_pending:
                        print(
                            f"* Some logs could not be sent to the Space directly: they were uploaded to "
                            f"the Hugging Face Bucket '{self._bucket_id}' instead and will appear on the "
                            f"dashboard once the Space is running."
                        )

                if has_pending:
                    if self._space_id is not None:
                        retry = f'trackio.init(project="{self.project}", space_id="{self._space_id}")'
                    else:
                        retry = f'trackio.init(project="{self.project}", server_url="{self._server_base_url}")'
                    _emit_nonfatal_warning(
                        f"* Some logs could not be sent to the remote server (it may still be starting up). "
                        f"They have been saved locally and will be sent automatically next time you call: "
                        f"{retry}"
                    )
        except Exception as e:
            _emit_nonfatal_warning(f"trackio.finish() failed: {e}")
