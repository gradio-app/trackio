import os

import pytest

from trackio import Run, Trace
from trackio.media import TrackioImage
from trackio.sqlite_storage import SQLiteStorage


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
