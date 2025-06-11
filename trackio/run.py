from collections import deque

from gradio_client import Client

from trackio.utils import generate_readable_name


class Run:
    def __init__(
        self,
        url: str,
        project: str,
        client: Client,
        name: str | None = None,
        config: dict | None = None,
        dataset_id: str | None = None,
    ):
        self.url = url
        self.project = project
        self.client = client
        self.name = name or generate_readable_name()
        self.config = config or {}
        self.dataset_id = dataset_id
        self.queued_logs = deque()

    def log(self, metrics: dict):
        if self.client is None:
            # lazily try to initialize the client
            try:
                self.client = Client(self.url, verbose=False)
            except BaseException as e:
                print(
                    f"Unable to instantiate log client; error was {e}. Will queue log item and try again on next log() call."
                )
        if self.client is None:
            # client can still be None for a Space while the Space is still initializing.
            # queue up log items for when the client is not None.
            self.queued_logs.append(
                dict(
                    api_name="/log",
                    project=self.project,
                    run=self.name,
                    metrics=metrics,
                    dataset_id=self.dataset_id,
                )
            )
        else:
            # flush the queued log items, if there are any
            if len(self.queued_logs) > 0:
                for queued_log in self.queued_logs:
                    self.client.predict(**queued_log)
                self.queued_logs.clear()
            # write the current log item
            self.client.predict(
                api_name="/log",
                project=self.project,
                run=self.name,
                metrics=metrics,
                dataset_id=self.dataset_id,
            )

    def finish(self):
        pass
