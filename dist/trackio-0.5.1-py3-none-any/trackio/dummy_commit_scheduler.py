# A dummy object to fit the interface of huggingface_hub's CommitScheduler
class DummyCommitSchedulerLock:
    def __enter__(self):
        return None

    def __exit__(self, exception_type, exception_value, exception_traceback):
        pass


class DummyCommitScheduler:
    def __init__(self):
        self.lock = DummyCommitSchedulerLock()
