import trackio
from trackio.sqlite_storage import SQLiteStorage


def test_trace_logging_round_trip(temp_dir):
    run = trackio.init(project="trace_project", name="trace_run")

    run.log(
        {
            "trace": trackio.Trace(
                messages=[
                    {"role": "system", "content": "You are a helpful assistant."},
                    {"role": "user", "content": "What is 2 + 2?"},
                    {"role": "assistant", "content": "2 + 2 = 4."},
                ],
                metadata={"model_version": "step-100"},
            )
        }
    )
    run.finish()

    traces = SQLiteStorage.get_traces("trace_project", "trace_run")
    assert len(traces) == 1
    assert traces[0]["messages"][2]["content"] == "2 + 2 = 4."
    assert traces[0]["metadata"]["model_version"] == "step-100"
