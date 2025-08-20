import time
from unittest.mock import MagicMock, patch

import huggingface_hub
import pytest

from trackio import Run, init


class DummyClient:
    def __init__(self):
        self.predict = MagicMock()


def test_run_log_calls_client():
    client = DummyClient()
    run = Run(url="fake_url", project="proj", client=client, name="run1", space_id=None)
    metrics = {"x": 1}
    run.log(metrics)

    time.sleep(0.6)  # Wait for the client to send the log
    client.predict.assert_called_once_with(
        api_name="/bulk_log",
        logs=[{"project": "proj", "run": "run1", "metrics": metrics, "step": None}],
        hf_token=huggingface_hub.utils.get_token(),
    )


def test_init_resume_modes(temp_dir):
    run = init(
        project="test-project",
        name="new-run",
        resume="never",
    )
    assert isinstance(run, Run)
    assert run.name == "new-run"

    run.log({"x": 1})
    run.finish()

    run = init(
        project="test-project",
        name="new-run",
        resume="must",
    )
    assert isinstance(run, Run)
    assert run.name == "new-run"

    run = init(
        project="test-project",
        name="new-run",
        resume="allow",
    )
    assert isinstance(run, Run)
    assert run.name == "new-run"

    run = init(
        project="test-project",
        name="new-run",
        resume="never",
    )
    assert isinstance(run, Run)
    assert run.name != "new-run"

    with pytest.raises(
        ValueError,
        match="Run 'nonexistent-run' does not exist in project 'test-project'",
    ):
        init(
            project="test-project",
            name="nonexistent-run",
            resume="must",
        )

    run = init(
        project="test-project",
        name="nonexistent-run",
        resume="allow",
    )
    assert isinstance(run, Run)
    assert run.name == "nonexistent-run"


@patch("huggingface_hub.whoami")
@patch("time.time")
def test_run_name_generation_with_space_id(mock_time, mock_whoami):
    mock_whoami.return_value = {"name": "testuser"}
    mock_time.return_value = 1234567890

    client = DummyClient()
    run = Run(
        url="fake_url",
        project="proj",
        client=client,
        name=None,
        space_id="testuser/test-space",
    )
    assert run.name == "testuser-1234567890"
