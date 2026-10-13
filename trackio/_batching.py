import threading


class _PendingBatch:
    """Share one fallback write between the sender and shutdown."""

    def __init__(self, entries, api_name, parameter, persist):
        self.entries = entries
        self.api_name = api_name
        self.parameter = parameter
        self._persist = persist
        self._lock = threading.Lock()
        self._handled = False

    def persist(self):
        with self._lock:
            if not self._handled:
                self._persist(self.entries)
                self._handled = True

    def send(self, client, hf_token) -> bool:
        with self._lock:
            if self._handled:
                return True
        try:
            client.predict(
                api_name=self.api_name,
                hf_token=hf_token,
                **{self.parameter: self.entries},
            )
        except Exception:
            self.persist()
            return False
        with self._lock:
            self._handled = True
        return True
