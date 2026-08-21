import os
import sqlite3

import pytest

from trackio import Run, Trace
from trackio.media import TrackioImage
from trackio.sqlite_storage import SQLiteStorage


def test_trace_schema_migrates_existing_database(temp_dir):
    db_path = SQLiteStorage.get_project_db_path("legacy-proj")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE traces (
                id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                run_name TEXT NOT NULL,
                step INTEGER NOT NULL,
                key TEXT NOT NULL,
                trace_index INTEGER,
                messages TEXT NOT NULL,
                metadata TEXT NOT NULL,
                search_text TEXT NOT NULL,
                log_id TEXT,
                space_id TEXT
            )
            """
        )
        conn.execute(
            """
            INSERT INTO traces
            (id, run_id, timestamp, run_name, step, key, messages, metadata, search_text)
            VALUES ('trace-1', 'run-1', '2026-08-19T12:00:00Z', 'run', 0, 'trace', '[]', '{}', '')
            """
        )

    legacy_traces = SQLiteStorage.get_traces("legacy-proj", "run", run_id="run-1")
    assert legacy_traces[0]["spans"] == []

    SQLiteStorage.init_db("legacy-proj")

    with sqlite3.connect(db_path) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(traces)")}
        spans = conn.execute("SELECT spans FROM traces").fetchone()[0]
    assert "spans" in columns
    assert spans == "[]"


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
        spans=[
            {
                "id": "inspect-page",
                "name": "inspect-page",
                "kind": "tool",
                "input": image,
            }
        ],
    )

    payload = trace._to_dict(project="proj", run="run1", step=0)

    assert payload["_type"] == Trace.TYPE
    assert payload["metadata"]["label"] == "demo-trace"
    assert payload["messages"][1]["content"][1]["_type"] == "trackio.image"
    assert payload["spans"][0]["input"]["_type"] == "trackio.image"


def test_trace_requires_message_dicts():
    with pytest.raises(TypeError, match="list of dictionaries"):
        Trace(messages=["bad"])  # type: ignore[arg-type]


def test_trace_requires_span_dicts():
    with pytest.raises(TypeError, match="list of dictionaries"):
        Trace(messages=[], spans=["bad"])  # type: ignore[list-item]


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
                spans=[
                    {
                        "id": "generation-a",
                        "name": "provider-request",
                        "kind": "generation",
                        "start_time": "2026-08-19T12:00:00Z",
                        "end_time": "2026-08-19T12:00:01Z",
                        "model": "tiny-model",
                        "usage": {"input_tokens": 8, "output_tokens": 2},
                        "cost_usd": 0.001,
                        "status": "success",
                    }
                ],
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
    assert traces[1]["spans"][0]["usage"]["input_tokens"] == 8

    searched = SQLiteStorage.get_traces("proj", "trace-run", search="canberra")
    assert len(searched) == 1
    assert searched[0]["metadata"]["label"] == "candidate-b"

    searched_spans = SQLiteStorage.get_traces("proj", "trace-run", search="tiny-model")
    assert len(searched_spans) == 1
    assert searched_spans[0]["metadata"]["label"] == "candidate-a"


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


def test_trace_spans_survive_run_rename(temp_dir):
    run = Run(url=None, project="proj", client=None, name="old-run", space_id=None)
    run.log(
        {
            "conversation": Trace(
                messages=[{"role": "user", "content": "rename me"}],
                spans=[
                    {
                        "id": "tool-1",
                        "name": "hf search",
                        "kind": "tool",
                        "input": {"query": "datasets"},
                    }
                ],
            )
        }
    )
    run.finish()

    SQLiteStorage.rename_run("proj", "old-run", "new-run", run_id=run.id)

    traces = SQLiteStorage.get_traces("proj", "new-run", run_id=run.id)
    assert traces[0]["spans"][0]["name"] == "hf search"


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
                spans=[
                    {
                        "id": "tool-1",
                        "name": "hf search",
                        "kind": "tool",
                        "input": {"query": "agent datasets"},
                        "output": {"matches": 3},
                        "status": "success",
                    }
                ],
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
