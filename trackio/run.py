import huggingface_hub
from gradio_client import Client

from trackio.utils import RESERVED_KEYS, generate_readable_name


class Run:
    def __init__(
        self,
        project: str,
        client: Client,
        name: str | None = None,
        config: dict | None = None,
        dataset_id: str | None = None,
    ):
        self.project = project
        self.client = client
        self.name = name or generate_readable_name()
        self.config = config or {}
        self.dataset_id = dataset_id

    def log(self, metrics: dict):
        for k in metrics.keys():
            if k in RESERVED_KEYS or k.startswith("__"):
                raise ValueError(
                    f"Please do not use this reserved key as a metric: {k}"
                )
        self.client.predict(
            api_name="/log",
            project=self.project,
            run=self.name,
            metrics=metrics,
            dataset_id=self.dataset_id,
            hf_token=huggingface_hub.utils.get_token(),
        )

    def finish(self):
        """Cleanup when run is finished."""
        pass
