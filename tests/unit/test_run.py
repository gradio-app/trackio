import sqlite3
import time
from unittest.mock import MagicMock

import pytest

from trackio import Markdown, Run, init, utils
from trackio.sqlite_storage import SQLiteStorage


class DummyClient:
    def __init__(self):
        self.predict = MagicMock()


def test_run_log_writes_to_sqlite_locally(temp_dir):
    run = Run(url=None, project="proj", client=None, name="run1", space_id=None)
    metrics = {"x": 1}
    run.log(metrics)
    run.finish()

    logs = SQLiteStorage.get_logs("proj", "run1")
    assert len(logs) == 1
    assert logs[0]["x"] == 1
    assert logs[0]["step"] == 0

    config = SQLiteStorage.get_run_config("proj", "run1")
    assert config is not None
    assert run.id is not None


def test_markdown_logging(temp_dir):
    run = Run(url=None, project="proj", client=None, name="run-report", space_id=None)
    run.log({"loss": 0.1, "summary": Markdown("# Training summary")})
    run.finish()

    logs = SQLiteStorage.get_logs("proj", "run-report")

    markdown_entries = [
        entry
        for entry in logs
        if isinstance(entry.get("summary"), dict)
        and entry["summary"].get("_type") == Markdown.TYPE
    ]
    assert len(markdown_entries) == 1
    assert markdown_entries[0]["summary"]["_value"] == "# Training summary"


def test_run_log_calls_client_for_spaces(temp_dir):
    client = DummyClient()
    run = Run(
        url="fake_url",
        project="proj",
        client=client,
        name="run1",
        space_id="user/space",
    )
    metrics = {"x": 1}
    run.log(metrics)

    time.sleep(0.6)
    _, kwargs = client.predict.call_args
    assert kwargs["api_name"] == "/bulk_log"
    assert len(kwargs["logs"]) == 1
    assert kwargs["logs"][0]["project"] == "proj"
    assert kwargs["logs"][0]["run"] == "run1"
    assert kwargs["logs"][0]["metrics"] == metrics
    assert kwargs["logs"][0]["step"] == 0
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
    SQLiteStorage.bulk_log("test-project", "new-run", [{"x": 1}])
    run.finish()
    first_run_id = run.id

    run = init(
        project="test-project",
        name="new-run",
        resume="must",
    )
    assert isinstance(run, Run)
    assert run.name == "new-run"
    assert run.id == first_run_id

    run = init(
        project="test-project",
        name="new-run",
        resume="allow",
    )
    assert isinstance(run, Run)
    assert run.name == "new-run"
    assert run.id == first_run_id

    run = init(
        project="test-project",
        name="new-run",
        resume="never",
    )
    assert isinstance(run, Run)
    assert run.name == "new-run"
    assert run.id != first_run_id

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


def test_resume_allow_and_must_use_latest_run_with_same_name(temp_dir):
    first = init(project="dup-project", name="same-name", resume="never")
    first.log({"x": 1})
    first.finish()

    second = init(project="dup-project", name="same-name", resume="never")
    second.log({"x": 2})
    second.finish()

    allowed = init(project="dup-project", name="same-name", resume="allow")
    assert allowed.id == second.id

    required = init(project="dup-project", name="same-name", resume="must")
    assert required.id == second.id


def test_reserved_config_keys_rejected(temp_dir):
    with pytest.raises(ValueError, match="Config key '_test' is reserved"):
        Run(
            url=None,
            project="test_project",
            client=None,
            config={"_test": "value"},
        )


def test_step_recovery_after_crash(temp_dir):
    SQLiteStorage.bulk_log(
        "proj",
        "run1",
        [{"loss": 0.5}, {"loss": 0.4}, {"loss": 0.3}],
        run_id="run-1-id",
    )

    run = Run(
        url=None,
        project="proj",
        client=None,
        name="run1",
        run_id="run-1-id",
        space_id=None,
    )
    assert run._next_step == 3

    run.log({"loss": 0.2})
    time.sleep(0.6)

    logs = SQLiteStorage.get_logs("proj", "run1", run_id="run-1-id")
    assert len(logs) == 4
    assert logs[3]["step"] == 3


def test_run_group_added(temp_dir):
    run = Run(
        url=None,
        project="test_project",
        group="test_group",
        client=None,
        config={"learning_rate": 0.01},
    )
    assert run.config["_Group"] == "test_group"


def test_log_does_not_crash_on_bad_metrics(temp_dir, monkeypatch):
    run = Run(url=None, project="proj", client=None, name="safe-run", space_id=None)

    original = utils.serialize_values

    def exploding_serialize(metrics):
        if "bad" in metrics:
            raise RuntimeError("serialize boom")
        return original(metrics)

    monkeypatch.setattr(utils, "serialize_values", exploding_serialize)

    with pytest.warns(UserWarning, match="trackio.log\\(\\) failed to process metrics"):
        run.log({"bad": 1})

    run.log({"loss": 0.5})
    run.finish()

    logs = SQLiteStorage.get_logs("proj", "safe-run")
    assert len(logs) == 1
    assert logs[0]["loss"] == 0.5


def test_init_survives_storage_read_failures(temp_dir, monkeypatch):
    def raise_db_error(*args, **kwargs):
        raise sqlite3.DatabaseError("database disk image is malformed")

    monkeypatch.setattr(SQLiteStorage, "get_runs", raise_db_error)
    monkeypatch.setattr(SQLiteStorage, "get_max_step_for_run", raise_db_error)

    with pytest.warns(UserWarning) as record:
        run = init(project="broken-project", name="safe-run")

    messages = [str(item.message) for item in record]
    assert any("could not inspect existing runs" in message for message in messages)
    assert any("could not recover the previous step" in message for message in messages)
    assert isinstance(run, Run)
    assert run.name == "safe-run"
    assert run._next_step == 0

    run.log({"loss": 0.5})
    run.finish()


def test_local_flush_failure_does_not_crash(temp_dir, monkeypatch):
    run = Run(url=None, project="proj", client=None, name="safe-run", space_id=None)

    def raise_db_error(*args, **kwargs):
        raise sqlite3.DatabaseError("database disk image is malformed")

    monkeypatch.setattr(SQLiteStorage, "bulk_log", raise_db_error)

    run.log({"loss": 0.5})

    with pytest.warns(UserWarning, match="trackio failed to flush metric logs"):
        run.finish()
