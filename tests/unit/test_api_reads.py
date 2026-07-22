from pathlib import Path

import pytest

import trackio


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
