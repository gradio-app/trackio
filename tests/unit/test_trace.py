import os
import sqlite3

import pytest

from trackio import Run, Trace, VerifiersTrace
from trackio.media import TrackioImage
from trackio.sqlite_storage import SQLiteStorage


def verifiers_record(trace_id="vf-trace-1"):
    return {
        "id": trace_id,
        "version": 2,
        "agent": {"model": "org/model"},
        "task": {"type": "ExampleTask", "data": {"idx": 7}},
        "nodes": [
            {"message": {"role": "user", "content": "solve this"}},
            {
                "parent": 0,
                "sampled": True,
                "message": {"role": "assistant", "content": "first branch"},
            },
            {
                "parent": 0,
                "sampled": True,
                "message": {"role": "assistant", "content": "final branch"},
            },
        ],
        "calls": [{"finish_reason": "length", "usage": {"completion_tokens": 8}}],
        "rewards": {"correct": 0.5},
        "metrics": {"format": 1.0},
        "errors": [],
        "stop_condition": "agent_completed",
        "is_completed": True,
    }


def test_trace_to_dict(image_ndarray, temp_dir):
    image = TrackioImage(image_ndarray, caption="browser screenshot")
    trace = Trace(
        messages=[
            {"role": "system", "content": "You are a browser agent."},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "What do you see?"},
                    image,
                ],
            },
        ],
        metadata={"label": "demo-trace"},
    )

    payload = trace._to_dict(project="proj", run="run1", step=0)

    assert payload["_type"] == Trace.TYPE
    assert payload["metadata"]["label"] == "demo-trace"
    assert payload["messages"][1]["content"][1]["_type"] == "trackio.image"


def test_trace_requires_message_dicts():
    with pytest.raises(TypeError, match="list of dictionaries"):
        Trace(messages=["bad"])  # type: ignore[arg-type]


def test_verifiers_trace_preserves_native_record_and_projects_final_branch():
    record = verifiers_record()
    trace = VerifiersTrace(record)

    payload = trace._to_dict(project="proj", run="run1", step=0)

    assert payload["_type"] == VerifiersTrace.TYPE
    assert payload["external_id"] == "vf-trace-1"
    assert payload["schema_version"] == 2
    assert payload["payload"] == record
    assert payload["messages"][-1]["content"] == "final branch"
    assert payload["metadata"]["model"] == "org/model"
    assert payload["metadata"]["reward"] == 0.5
    assert payload["metadata"]["is_truncated"] is True


def test_verifiers_trace_requires_native_identity():
    with pytest.raises(TypeError, match="non-empty string"):
        VerifiersTrace({"version": 2})
    with pytest.raises(TypeError, match="integer"):
        VerifiersTrace({"id": "trace", "version": "2"})


def test_trace_logging_and_query(temp_dir):
    run = Run(url=None, project="proj", client=None, name="trace-run", space_id=None)
    run.log(
        {
            "conversation": Trace(
                messages=[
                    {"role": "system", "content": "Answer directly."},
                    {"role": "user", "content": "What is the capital of Australia?"},
                    {"role": "assistant", "content": "Sydney."},
                ],
                metadata={"label": "candidate-a", "group": "capitals"},
            )
        }
    )
    run.log(
        {
            "conversation": Trace(
                messages=[
                    {"role": "system", "content": "Answer directly."},
                    {"role": "user", "content": "What is the capital of Australia?"},
                    {"role": "assistant", "content": "Canberra."},
                ],
                metadata={"label": "candidate-b", "group": "capitals"},
            )
        }
    )
    run.finish()

    logs = SQLiteStorage.get_logs("proj", "trace-run")
    assert "conversation" not in logs[0]

    traces = SQLiteStorage.get_traces("proj", "trace-run", sort="step_desc")
    assert len(traces) == 2
    assert traces[0]["messages"][2]["content"] == "Canberra."

    searched = SQLiteStorage.get_traces("proj", "trace-run", search="canberra")
    assert len(searched) == 1
    assert searched[0]["metadata"]["label"] == "candidate-b"


def test_trace_limit_offset_are_applied_in_storage(temp_dir):
    run = Run(url=None, project="proj", client=None, name="trace-run", space_id=None)
    for index in range(5):
        run.log(
            {
                "conversation": Trace(
                    messages=[
                        {"role": "user", "content": f"question {index}"},
                        {"role": "assistant", "content": f"answer {index}"},
                    ],
                    metadata={"index": index},
                )
            }
        )
    run.finish()

    traces = SQLiteStorage.get_traces(
        "proj", "trace-run", sort="step_asc", limit=2, offset=2
    )
    assert [trace["metadata"]["index"] for trace in traces] == [2, 3]


def test_trace_logging_keeps_scalar_metrics_separate(temp_dir):
    run = Run(url=None, project="proj", client=None, name="trace-run", space_id=None)
    run.log(
        {
            "loss": 0.5,
            "conversation": Trace(
                messages=[
                    {"role": "user", "content": "hello"},
                    {"role": "assistant", "content": "hi"},
                ],
            ),
        }
    )
    run.finish()

    logs = SQLiteStorage.get_logs("proj", "trace-run")
    assert logs[0]["loss"] == 0.5
    assert "conversation" not in logs[0]
    assert len(SQLiteStorage.get_traces("proj", "trace-run")) == 1


def test_verifiers_trace_logging_is_idempotent_and_filterable(temp_dir):
    run = Run(url=None, project="proj", client=None, name="trace-run", space_id=None)
    native = VerifiersTrace(verifiers_record())
    run.log({"rollout": native})
    run.log({"rollout": native})
    run.log(
        {
            "conversation": Trace(
                messages=[{"role": "user", "content": "standard"}]
            )
        }
    )
    run.finish()

    all_traces = SQLiteStorage.get_traces("proj", "trace-run")
    verifiers = SQLiteStorage.get_traces(
        "proj", "trace-run", trace_type="verifiers"
    )
    standard = SQLiteStorage.get_traces("proj", "trace-run", trace_type="trackio")

    assert len(all_traces) == 2
    assert len(verifiers) == 1
    assert len(standard) == 1
    assert verifiers[0]["external_id"] == "vf-trace-1"
    assert verifiers[0]["payload"]["task"]["type"] == "ExampleTask"


def test_verifiers_trace_search_does_not_index_native_payload(temp_dir):
    run = Run(url=None, project="proj", client=None, name="trace-run", space_id=None)
    record = verifiers_record()
    record["private_runtime_detail"] = "payload-only-secret"
    run.log({"rollout": VerifiersTrace(record)})
    run.finish()

    assert SQLiteStorage.get_traces(
        "proj", "trace-run", search="final branch"
    )
    assert not SQLiteStorage.get_traces(
        "proj", "trace-run", search="payload-only-secret"
    )


def test_existing_trace_table_migrates_additively(temp_dir):
    db_path = SQLiteStorage.get_project_db_path("proj")
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """CREATE TABLE traces (
                id TEXT PRIMARY KEY, run_id TEXT NOT NULL, timestamp TEXT NOT NULL,
                run_name TEXT NOT NULL, step INTEGER NOT NULL, key TEXT NOT NULL,
                trace_index INTEGER, messages TEXT NOT NULL, metadata TEXT NOT NULL,
                search_text TEXT NOT NULL, log_id TEXT, space_id TEXT
            )"""
        )

    SQLiteStorage.init_db("proj")

    with sqlite3.connect(db_path) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(traces)")}
    assert {"trace_type", "external_id", "schema_version", "payload"} <= columns


def test_trace_export_import_roundtrip(temp_dir):
    run = Run(url=None, project="proj", client=None, name="trace-run", space_id=None)
    run.log(
        {
            "conversation": Trace(
                messages=[
                    {"role": "user", "content": "export me"},
                    {"role": "assistant", "content": "imported"},
                ],
                metadata={"source": "roundtrip"},
            ),
        }
    )
    run.finish()

    before = SQLiteStorage.get_traces("proj", "trace-run")
    db_path = SQLiteStorage.get_project_db_path("proj")
    SQLiteStorage._dataset_import_attempted = True
    SQLiteStorage.export_to_parquet()
    os.unlink(db_path)
    SQLiteStorage.import_from_parquet()

    after = SQLiteStorage.get_traces("proj", "trace-run")
    assert after == before


def test_verifiers_trace_export_import_roundtrip(temp_dir):
    pytest.importorskip("pyarrow")
    run = Run(url=None, project="proj", client=None, name="trace-run", space_id=None)
    run.log({"rollout": VerifiersTrace(verifiers_record())})
    run.finish()

    before = SQLiteStorage.get_traces("proj", "trace-run")
    db_path = SQLiteStorage.get_project_db_path("proj")
    SQLiteStorage._dataset_import_attempted = True
    SQLiteStorage.export_to_parquet()
    os.unlink(db_path)
    SQLiteStorage.import_from_parquet()

    after = SQLiteStorage.get_traces("proj", "trace-run")
    assert after == before
