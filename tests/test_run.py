import time
from unittest.mock import MagicMock, patch

import pytest

from trackio import Run, init


class DummyClient:
    def __init__(self):
        self.predict = MagicMock()


def test_run_log_calls_client(temp_dir):
    client = DummyClient()
    run = Run(url="fake_url", project="proj", client=client, name="run1", space_id=None)
    metrics = {"x": 1}
    run.log(metrics)

    time.sleep(0.6)  # Wait for the client to send the log
    args, kwargs = client.predict.call_args
    assert kwargs["api_name"] == "/bulk_log"
    assert len(kwargs["logs"]) == 1
    assert kwargs["logs"][0]["project"] == "proj"
    assert kwargs["logs"][0]["run"] == "run1"
    assert kwargs["logs"][0]["metrics"] == metrics
    assert kwargs["logs"][0]["step"] is None
    assert "config" in kwargs["logs"][0]


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
def test_run_name_generation_with_space_id(mock_time, mock_whoami, temp_dir):
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


def test_reserved_config_keys_rejected(temp_dir):
    with pytest.raises(ValueError, match="Config key '_test' is reserved"):
        Run(
            url="http://test",
            project="test_project",
            client=None,
            config={"_test": "value"},
        )


@patch("huggingface_hub.whoami")
def test_automatic_username_and_timestamp_added(mock_whoami, temp_dir):
    mock_whoami.return_value = {"name": "testuser"}

    run = Run(
        url="http://test",
        project="test_project",
        client=None,
        config={"learning_rate": 0.01},
    )

    assert run.config["_Username"] == "testuser"
    assert "_Created" in run.config
    assert run.config["learning_rate"] == 0.01

    from datetime import datetime

    created_time = datetime.fromisoformat(run.config["_Created"])
    assert created_time.tzinfo is not None


def test_run_group_added(temp_dir):
    run = Run(
        url="http://test",
        project="test_project",
        group="test_group",
        client=None,
        config={"learning_rate": 0.01},
    )
    assert run.config["_Group"] == "test_group"
