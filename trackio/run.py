import threading
import time
from collections import deque

import huggingface_hub
from gradio_client import Client

from trackio.sqlite_storage import SQLiteStorage
from trackio.utils import RESERVED_KEYS, fibo, generate_readable_name


class Run:
    def __init__(
        self,
        url: str,
        project: str,
        client: Client | None,
        name: str | None = None,
        config: dict | None = None,
    ):
        self.url = url
        self.project = project
        self._client_lock = threading.Lock()
        self._client_thread = None
        self._client = client
        self.name = name or generate_readable_name(SQLiteStorage.get_runs(project))
        self.config = config or {}
        self._queued_logs = deque()
        self._batch_thread = None
        self._batch_thread_stop = threading.Event()
        self._pending_logs = []
        self._pending_logs_lock = threading.Lock()

        if client is None:
            self._client_thread = threading.Thread(target=self._init_client_background)
            self._client_thread.start()
        else:
            # Start batch thread if client is already available
            self._start_batch_thread()

    def _start_batch_thread(self):
        """Start the thread that batches and sends logs every 500ms."""
        if self._batch_thread is None:
            self._batch_thread = threading.Thread(target=self._batch_sender)
            self._batch_thread.daemon = True
            self._batch_thread.start()

    def _batch_sender(self):
        """Background thread that sends batched logs every 500ms."""
        while not self._batch_thread_stop.is_set():
            time.sleep(0.5)  # Wait 500ms

            # Collect pending logs
            with self._pending_logs_lock:
                if self._pending_logs:
                    logs_to_send = self._pending_logs.copy()
                    self._pending_logs.clear()
                else:
                    continue

            # Send batched logs
            with self._client_lock:
                if self._client is not None:
                    try:
                        self._client.predict(
                            api_name="/bulk_log",
                            logs=logs_to_send,
                            hf_token=huggingface_hub.utils.get_token(),
                        )
                    except Exception:
                        # If bulk_log fails, fall back to individual logs
                        for log_entry in logs_to_send:
                            try:
                                self._client.predict(**log_entry)
                            except Exception:
                                pass

    def _init_client_background(self):
        fib = fibo()
        for sleep_coefficient in fib:
            try:
                client = Client(self.url, verbose=False)
                with self._client_lock:
                    self._client = client
                    # Start batch thread once client is ready
                    self._start_batch_thread()
                    # Process any queued logs from before client was ready
                    if len(self._queued_logs) > 0:
                        logs_to_send = []
                        for queued_log in self._queued_logs:
                            # Convert old format to new bulk format
                            logs_to_send.append(
                                {
                                    "project": queued_log["project"],
                                    "run": queued_log["run"],
                                    "metrics": queued_log["metrics"],
                                    "step": queued_log.get("step"),
                                }
                            )
                        try:
                            self._client.predict(
                                api_name="/bulk_log",
                                logs=logs_to_send,
                                hf_token=huggingface_hub.utils.get_token(),
                            )
                        except Exception:
                            # Fall back to individual logs if bulk fails
                            for queued_log in self._queued_logs:
                                self._client.predict(**queued_log)
                        self._queued_logs.clear()
                    break
            except Exception:
                pass
            if sleep_coefficient is not None:
                time.sleep(0.1 * sleep_coefficient)

    def log(self, metrics: dict, step: int | None = None):
        for k in metrics.keys():
            if k in RESERVED_KEYS or k.startswith("__"):
                raise ValueError(
                    f"Please do not use this reserved key as a metric: {k}"
                )

        log_entry = {
            "project": self.project,
            "run": self.name,
            "metrics": metrics,
            "step": step,
        }

        with self._client_lock:
            if self._client is None:
                # client can still be None for a Space while the Space is still initializing.
                # queue up log items for when the client is not None.
                payload = dict(
                    api_name="/log",
                    project=self.project,
                    run=self.name,
                    metrics=metrics,
                    step=step,
                    hf_token=huggingface_hub.utils.get_token(),
                )
                self._queued_logs.append(payload)
            else:
                # Add to pending logs for batch sending
                with self._pending_logs_lock:
                    self._pending_logs.append(log_entry)

    def finish(self):
        """Cleanup when run is finished."""
        # Stop batch thread
        if self._batch_thread is not None:
            self._batch_thread_stop.set()

            # Send any remaining pending logs immediately
            with self._pending_logs_lock:
                if self._pending_logs and self._client is not None:
                    logs_to_send = self._pending_logs.copy()
                    self._pending_logs.clear()
                    try:
                        self._client.predict(
                            api_name="/bulk_log",
                            logs=logs_to_send,
                            hf_token=huggingface_hub.utils.get_token(),
                        )
                    except Exception:
                        # Fall back to individual logs if bulk fails
                        for log_entry in logs_to_send:
                            payload = dict(
                                api_name="/log",
                                project=log_entry["project"],
                                run=log_entry["run"],
                                metrics=log_entry["metrics"],
                                step=log_entry.get("step"),
                                hf_token=huggingface_hub.utils.get_token(),
                            )
                            try:
                                self._client.predict(**payload)
                            except Exception:
                                pass

            self._batch_thread.join(timeout=2)

        # wait for background client thread, in case it has a queue of logs to flush.
        if self._client_thread is not None:
            print(f"* Uploading logs to Trackio Space: {self.url} (please wait...)")
            self._client_thread.join()
