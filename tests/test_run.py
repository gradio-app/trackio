from unittest.mock import MagicMock

from trackio.run import Run


class DummyClient:
    def __init__(self):
        self.predict = MagicMock()


def test_run_log_calls_client():
    client = DummyClient()
    run = Run(url="fake_url", project="proj", client=client, name="run1")
    metrics = {"x": 1}
    run.log(metrics)
    client.predict.assert_called_once_with(
        api_name="/log", project="proj", run="run1", metrics=metrics, dataset_id=None
    )
