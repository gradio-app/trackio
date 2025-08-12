from unittest.mock import MagicMock

import huggingface_hub
import pytest

from trackio import Run, init


class DummyClient:
    def __init__(self):
        self.predict = MagicMock()


def test_run_log_calls_client():
    client = DummyClient()
    run = Run(url="fake_url", project="proj", client=client, name="run1")
    metrics = {"x": 1}
    run.log(metrics)

    # Since logging is now batched, we need to wait or trigger the batch
    # Let's check that the log was added to pending logs instead
    import time

    time.sleep(0.6)  # Wait for batch interval

    # The predict should have been called with bulk_log
    assert client.predict.called
    # Check that it was called with the bulk_log API
    call_args = client.predict.call_args
    if call_args:
        assert (
            call_args.kwargs.get("api_name") == "/bulk_log"
            or call_args.kwargs.get("api_name") == "/log"
        )


def test_init_resume_modes(temp_db):
    run = init(
        project="test-project",
        name="new-run",
        resume="never",
    )
    assert isinstance(run, Run)
    assert run.name == "new-run"

    run.log({"x": 1})
    run.finish()  # Ensure the run is finished and logs are flushed

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
