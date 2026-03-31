from concurrent.futures import Future


class DummyCommitSchedulerLock:
    def __enter__(self):
        return None

    def __exit__(self, exception_type, exception_value, exception_traceback):
        pass


class DummyCommitScheduler:
    def __init__(self):
        self.lock = DummyCommitSchedulerLock()

    def trigger(self) -> Future:
        fut: Future = Future()
        fut.set_result(None)
        return fut
