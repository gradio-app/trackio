import threading
import time

import huggingface_hub
from gradio_client import Client, handle_file

from trackio.media import TrackioImage
from trackio.sqlite_storage import SQLiteStorage
from trackio.typehints import LogEntry, UploadEntry
from trackio.utils import RESERVED_KEYS, fibo, generate_readable_name

BATCH_SEND_INTERVAL = 0.5


class Run:
    def __init__(
        self,
        url: str,
        project: str,
        client: Client | None,
        name: str | None = None,
        config: dict | None = None,
        space_id: str | None = None,
    ):
        self.url = url
        self.project = project
        self._client_lock = threading.Lock()
        self._client_thread = None
        self._client = client
        self._space_id = space_id
        self.name = name or generate_readable_name(
            SQLiteStorage.get_runs(project), space_id
        )
        self.config = config or {}
        self._queued_logs: list[LogEntry] = []
        self._queued_uploads: list[UploadEntry] = []
        self._stop_flag = threading.Event()

        self._client_thread = threading.Thread(target=self._init_client_background)
        self._client_thread.daemon = True
        self._client_thread.start()

    def _batch_sender(self):
        """Send batched logs every BATCH_SEND_INTERVAL."""
        while not self._stop_flag.is_set() or len(self._queued_logs) > 0:
            # If the stop flag has been set, then just quickly send all
            # the logs and exit.
            if not self._stop_flag.is_set():
                time.sleep(BATCH_SEND_INTERVAL)

            with self._client_lock:
                if self._queued_logs and self._client is not None:
                    logs_to_send = self._queued_logs.copy()
                    self._queued_logs.clear()
                    self._client.predict(
                        api_name="/bulk_log",
                        logs=logs_to_send,
                        hf_token=huggingface_hub.utils.get_token(),
                    )
                if self._queued_uploads and self._client is not None:
                    uploads_to_send = self._queued_uploads.copy()
                    self._queued_uploads.clear()
                    self._client.predict(
                        api_name="/bulk_upload_media",
                        uploads=uploads_to_send,
                        hf_token=huggingface_hub.utils.get_token(),
                    )

    def _init_client_background(self):
        if self._client is None:
            fib = fibo()
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

    def _process_media(self, metrics, step: int | None) -> dict:
        """
        Serialize media in metrics and upload to space if needed.
        """
        serializable_metrics = {}
        if not step:
            step = 0
        for key, value in metrics.items():
            if isinstance(value, TrackioImage):
                value._save(self.project, self.name, step)
                serializable_metrics[key] = value._to_dict()
                if self._space_id:
                    # Upload local media when deploying to space
                    upload_entry: UploadEntry = {
                        "project": self.project,
                        "run": self.name,
                        "step": step,
                        "uploaded_file": handle_file(value._get_absolute_file_path()),
                    }
                    with self._client_lock:
                        self._queued_uploads.append(upload_entry)
            else:
                serializable_metrics[key] = value
        return serializable_metrics

    def log(self, metrics: dict, step: int | None = None):
        for k in metrics.keys():
            if k in RESERVED_KEYS or k.startswith("__"):
                raise ValueError(
                    f"Please do not use this reserved key as a metric: {k}"
                )

        metrics = self._process_media(metrics, step)
        log_entry: LogEntry = {
            "project": self.project,
            "run": self.name,
            "metrics": metrics,
            "step": step,
        }

        with self._client_lock:
            self._queued_logs.append(log_entry)

    def finish(self):
        """Cleanup when run is finished."""
        self._stop_flag.set()

        # Wait for the batch sender to finish before joining the client thread.
        time.sleep(2 * BATCH_SEND_INTERVAL)

        if self._client_thread is not None:
            print(
                f"* Run finished. Uploading logs to Trackio Space: {self.url} (please wait...)"
            )
            self._client_thread.join()
