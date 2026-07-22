import sqlite3
from pathlib import Path

import pytest

import trackio
import trackio.api as api_module
from trackio.sqlite_storage import SQLiteStorage


def _verifiers_record() -> dict:
    return {
        "id": "vf-api-1",
        "version": 2,
        "agent": {"model": "org/model"},
        "task": {"type": "ExampleTask", "data": {"idx": 1}},
        "nodes": [
            {"message": {"role": "user", "content": "question"}},
            {
                "parent": 0,
                "message": {"role": "assistant", "content": "answer"},
            },
        ],
        "calls": [],
        "rewards": {"correct": 1.0},
        "metrics": {},
        "errors": [],
        "stop_condition": "agent_completed",
        "is_completed": True,
    }


def test_api_exposes_stable_run_reads(temp_dir):
    project = "api-read-surface"
    writer = trackio.init(
        project=project,
        name="train-run",
        config={"model": {"id": "org/model"}},
        group="package-1",
    )
    run_id = writer.id
    writer.log({"train/loss": 2.0, "event/name": "started"}, step=0)
    writer.log({"train/loss": 1.0}, step=1)
    writer.log(
        {
            "trace": trackio.Trace(
                [{"role": "user", "content": "hello"}],
                {"kind": "standard"},
            ),
            "rollout": trackio.VerifiersTrace(_verifiers_record()),
        },
        step=2,
    )

    artifact_path = Path(temp_dir) / "model.txt"
    artifact_path.write_text("weights")
    output = writer.log_artifact(artifact_path, name="trained-model", type="model")
    writer.finish()

    consumer = trackio.init(project=project, name="eval-run")
    consumer_id = consumer.id
    consumer.use_artifact(f"{output.name}:{output.version}", type="model")
    consumer.log({"eval/score": 0.9}, step=0)
    consumer.finish()

    api = trackio.Api()
    runs = {run.id: run for run in api.runs(project)}
    run = api.run(project, run_id)

    assert api.capabilities() == {
        "run_summaries": True,
        "full_history": True,
        "explicit_metric_steps": True,
        "standard_traces": True,
        "verifiers_traces": True,
        "live_traces": True,
        "artifact_lineage": True,
        "alerts": True,
    }
    assert run.created_at is not None
    assert run.summary()["config"]["model"] == {"id": "org/model"}
    assert run.summary()["last_step"] == 2
    assert run.history(keys=["train/loss"]) == [
        {
            "train/loss": 2.0,
            "timestamp": run.history()[0]["timestamp"],
            "step": 0,
        },
        {
            "train/loss": 1.0,
            "timestamp": run.history()[1]["timestamp"],
            "step": 1,
        },
        {"timestamp": run.history()[2]["timestamp"], "step": 2},
    ]
    assert [point["value"] for point in run.metric_series(["train/loss"])["train/loss"]] == [2.0, 1.0]

    traces = run.traces(sort="step_asc")
    assert {trace["trace_type"] for trace in traces} == {"trackio", "verifiers"}
    assert run.traces(trace_type="verifiers")[0]["external_id"] == "vf-api-1"
    output_link = run.artifacts()["output"][0]
    assert output_link["name"] == "trained-model"
    assert output_link["digest"] == output.digest
    assert runs[consumer_id].artifacts()["input"][0]["name"] == "trained-model"

    with pytest.raises(ValueError, match="does not exist"):
        api.run(project, "missing-run")


def test_api_reads_empty_run_created_by_artifact_link(temp_dir):
    project = "api-empty-run"
    producer = trackio.init(project=project, name="producer")
    artifact_path = Path(temp_dir) / "dataset.txt"
    artifact_path.write_text("row")
    artifact = producer.log_artifact(artifact_path, name="dataset", type="dataset")
    producer.finish()

    consumer = trackio.init(project=project, name="consumer")
    consumer_id = consumer.id
    consumer.use_artifact(f"dataset:{artifact.version}", type="dataset")
    consumer.finish()

    run = next(run for run in trackio.Api().runs(project) if run.id == consumer_id)
    assert run.summary()["num_logs"] == 0
    assert run.history() == []
    assert run.metric_series() == {}
    assert run.traces() == []
    assert run.artifacts()["input"][0]["version"] == 0


def test_api_read_only_mode_sees_new_runs_without_reopening_storage(temp_dir, monkeypatch):
    project = "api-live-read-only"
    first = trackio.init(project=project, name="first")
    first.log({"loss": 2.0}, step=0)
    first.finish()

    api = trackio.Api()
    monkeypatch.setenv("TRACKIO_READ_ONLY", "1")
    assert [run.name for run in api.runs(project)] == ["first"]
    with pytest.raises(sqlite3.OperationalError, match="readonly"):
        SQLiteStorage.bulk_log(
            project,
            "blocked",
            [{"loss": 1.0}],
        )

    monkeypatch.delenv("TRACKIO_READ_ONLY")
    second = trackio.init(project=project, name="second")
    second.log({"loss": 1.0}, step=1)
    second.finish()
    monkeypatch.setenv("TRACKIO_READ_ONLY", "1")

    assert {run.name for run in api.runs(project)} == {"first", "second"}


def test_api_remote_reader_uses_live_server_queries(monkeypatch):
    class FakeRemoteClient:
        runs = [
            {"id": "run-1", "name": "first", "created_at": "2026-01-01T00:00:00+00:00"}
        ]

        def __init__(self, server_url, hf_token=None):
            assert server_url == "http://trackio:7860"
            assert hf_token is None

        def predict(self, *, api_name, **kwargs):
            assert kwargs["project"] == "live-project"
            if api_name == "/get_runs_for_project":
                return list(self.runs)
            if api_name == "/get_run_summary":
                return {
                    "config": {"schema_version": 4},
                    "num_logs": 1,
                    "last_step": 7,
                    "metrics": ["train/loss"],
                }
            if api_name == "/get_run_history":
                return [{"step": 7, "timestamp": "now", "train/loss": 0.5}]
            raise AssertionError(f"unexpected API call {api_name}")

    monkeypatch.setattr(api_module, "RemoteClient", FakeRemoteClient)
    api = trackio.Api(server_url="http://trackio:7860")

    first = api.run("live-project", "run-1")
    assert first.summary()["last_step"] == 7
    assert first.metric_series()["train/loss"][0]["value"] == 0.5

    FakeRemoteClient.runs.append(
        {"id": "run-2", "name": "second", "created_at": "2026-01-02T00:00:00+00:00"}
    )
    assert {run.id for run in api.runs("live-project")} == {"run-1", "run-2"}
