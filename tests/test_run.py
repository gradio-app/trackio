from unittest.mock import MagicMock, patch

import huggingface_hub
import pytest

from trackio import Run, init
from trackio.sqlite_storage import SQLiteStorage


class DummyClient:
    def __init__(self):
        self.predict = MagicMock()


def test_run_log_calls_client():
    client = DummyClient()
    run = Run(project="proj", client=client, name="run1")
    metrics = {"x": 1}
    run.log(metrics)
    client.predict.assert_called_once_with(
        api_name="/log",
        project="proj",
        run="run1",
        metrics=metrics,
        dataset_id=None,
        hf_token=huggingface_hub.utils.get_token(),
    )


def test_init_resume_must():
    with patch("trackio.SQLiteStorage.get_runs") as mock_get_runs:
        mock_get_runs.return_value = ["existing-run"]
        client = DummyClient()

        run = init(
            project="test-project",
            name="existing-run",
            resume="must",
            client=client,
        )

        assert run.name == "existing-run"
        assert isinstance(run, Run)


def test_init_resume_must_nonexistent():
    with patch("trackio.SQLiteStorage.get_runs") as mock_get_runs:
        mock_get_runs.return_value = []
        client = DummyClient()

        with pytest.raises(
            ValueError,
            match="Run 'nonexistent-run' does not exist in project 'test-project'",
        ):
            init(
                project="test-project",
                name="nonexistent-run",
                resume="must",
                client=client,
            )


def test_init_resume_must_no_name():
    client = DummyClient()

    with pytest.raises(ValueError, match="Must provide a run name when resume='must'"):
        init(
            project="test-project",
            resume="must",
            client=client,
        )


def test_init_resume_allow_existing():
    with patch("trackio.SQLiteStorage.get_runs") as mock_get_runs:
        mock_get_runs.return_value = ["existing-run"]
        client = DummyClient()

        run = init(
            project="test-project",
            name="existing-run",
            resume="allow",
            client=client,
        )

        assert run.name == "existing-run"
        assert isinstance(run, Run)


def test_init_resume_allow_nonexistent():
    with patch("trackio.SQLiteStorage.get_runs") as mock_get_runs:
        mock_get_runs.return_value = []
        client = DummyClient()

        run = init(
            project="test-project",
            name="nonexistent-run",
            resume="allow",
            client=client,
        )

        assert run.name != "nonexistent-run"  # Should generate new name
        assert isinstance(run, Run)


def test_init_resume_never():
    with patch("trackio.SQLiteStorage.get_runs") as mock_get_runs:
        mock_get_runs.return_value = ["existing-run"]
        client = DummyClient()

        run = init(
            project="test-project",
            name="existing-run",
            resume="never",
            client=client,
        )

        assert run.name != "existing-run"  # Should generate new name
        assert isinstance(run, Run)


def test_init_resume_invalid():
    client = DummyClient()

    with pytest.raises(
        ValueError, match="resume must be one of: 'must', 'allow', 'never', or None"
    ):
        init(
            project="test-project",
            resume="invalid",
            client=client,
        )


def test_run_step_tracking():
    client = DummyClient()
    run = Run(project="test-project", client=client)

    # Test automatic step increment
    run.log({"metric1": 1.0})
    assert run.last_step == 1

    run.log({"metric2": 2.0})
    assert run.last_step == 2

    # Test manual step
    run.log({"step": 5, "metric3": 3.0})
    assert run.last_step == 5

    # Test step continuity
    run.log({"metric4": 4.0})
    assert run.last_step == 6


def test_run_resume_step_tracking():
    with patch("trackio.SQLiteStorage.get_metrics") as mock_get_metrics:
        mock_get_metrics.return_value = [
            {"step": 1, "metric1": 1.0},
            {"step": 2, "metric2": 2.0},
            {"step": 5, "metric3": 3.0},
        ]

        client = DummyClient()
        run = Run(project="test-project", client=client, name="resumed-run")

        assert run.last_step == 5  # Should load last step from metrics

        run.log({"metric4": 4.0})
        assert run.last_step == 6  # Should continue from last step


def test_run_finish():
    client = DummyClient()
    run = Run(project="test-project", client=client)

    with patch.object(run.storage, "finish") as mock_finish:
        run.finish()
        mock_finish.assert_called_once()
