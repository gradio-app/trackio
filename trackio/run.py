import threading
import time
import warnings
from datetime import datetime, timezone

import huggingface_hub
from gradio_client import Client, handle_file

from trackio import utils
from trackio.histogram import Histogram
from trackio.media import TrackioMedia
from trackio.sqlite_storage import SQLiteStorage
from trackio.table import Table
from trackio.typehints import LogEntry, UploadEntry
from trackio.utils import _get_default_namespace

BATCH_SEND_INTERVAL = 0.5


class Run:
    def __init__(
        self,
        url: str,
        project: str,
        client: Client | None,
        name: str | None = None,
        group: str | None = None,
        config: dict | None = None,
        space_id: str | None = None,
    ):
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
        self._queued_uploads: list[UploadEntry] = []
        self._stop_flag = threading.Event()
        self._config_logged = False

        self._client_thread = threading.Thread(target=self._init_client_background)
        self._client_thread.daemon = True
        self._client_thread.start()

    def _get_username(self) -> str | None:
        """Get the current HuggingFace username if logged in, otherwise None."""
        try:
            return _get_default_namespace()
        except Exception:
            return None

    def _batch_sender(self):
        """Send batched logs every BATCH_SEND_INTERVAL."""
        while not self._stop_flag.is_set() or len(self._queued_logs) > 0:
            if not self._stop_flag.is_set():
                time.sleep(BATCH_SEND_INTERVAL)

            with self._client_lock:
                if self._client is None:
                    return
                if self._queued_logs:
                    logs_to_send = self._queued_logs.copy()
                    self._queued_logs.clear()
                    self._client.predict(
                        api_name="/bulk_log",
                        logs=logs_to_send,
                        hf_token=huggingface_hub.utils.get_token(),
                    )
                if self._queued_uploads:
                    uploads_to_send = self._queued_uploads.copy()
                    self._queued_uploads.clear()
                    self._client.predict(
                        api_name="/bulk_upload_media",
                        uploads=uploads_to_send,
                        hf_token=huggingface_hub.utils.get_token(),
                    )

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
        """
        Queues a media file for upload to a Space.

        Args:
            file_path:
                The path to the file to upload.
            step (`int` or `None`, *optional*):
                The step number associated with this upload.
            relative_path (`str` or `None`, *optional*):
                The relative path within the project's files directory. Used when
                uploading files via `trackio.save()`.
            use_run_name (`bool`, *optional*):
                Whether to use the run name for the uploaded file. This is set to
                `False` when uploading files via `trackio.save()`.
        """
        upload_entry: UploadEntry = {
            "project": self.project,
            "run": self.name if use_run_name else None,
            "step": step,
            "relative_path": relative_path,
            "uploaded_file": handle_file(file_path),
        }
        with self._client_lock:
            self._queued_uploads.append(upload_entry)

    def _process_media(self, value: TrackioMedia, step: int | None) -> dict:
        """
        Serialize media in metrics and upload to space if needed.
        """
        value._save(self.project, self.name, step)
        if self._space_id:
            self._queue_upload(value._get_absolute_file_path(), step)
        return value._to_dict()

    def _scan_and_queue_media_uploads(self, table_dict: dict, step: int | None):
        """
        Scan a serialized table for media objects and queue them for upload to space.
        """
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
            elif isinstance(value, TrackioMedia):
                metrics[key] = self._process_media(value, step)
        metrics = utils.serialize_values(metrics)

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
        }

        with self._client_lock:
            self._queued_logs.append(log_entry)

    def finish(self):
        """Cleanup when run is finished."""
        self._stop_flag.set()

        time.sleep(2 * BATCH_SEND_INTERVAL)

        if self._client_thread is not None:
            print("* Run finished. Uploading logs to Trackio (please wait...)")
            self._client_thread.join()
