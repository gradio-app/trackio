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

        if client is None:
            self._client_thread = threading.Thread(target=self._init_client_background)
            self._client_thread.start()

    def _init_client_background(self):
        fib = fibo()
        for sleep_coefficient in fib:
            try:
                client = Client(self.url, verbose=False)
                with self._client_lock:
                    self._client = client
                    if len(self._queued_logs) > 0:
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
        payload = dict(
            api_name="/log",
            project=self.project,
            run=self.name,
            metrics=metrics,
            step=step,
            hf_token=huggingface_hub.utils.get_token(),
        )
        with self._client_lock:
            if self._client is None:
                # client can still be None for a Space while the Space is still initializing.
                # queue up log items for when the client is not None.
                self._queued_logs.append(payload)
            else:
                assert (
                    len(self._queued_logs) == 0
                )  # queue should have been flushed on client init
                # write the current log item
                self._client.predict(**payload)

    def finish(self):
        """Cleanup when run is finished."""
        # wait for background client thread, in case it has a queue of logs to flush.
        if self._client_thread is not None:
            print(f"* Uploading logs to Trackio Space: {self.url} (please wait...)")
            self._client_thread.join()
