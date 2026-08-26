import json
import os
import sqlite3
from pathlib import Path

import pytest

from trackio import Run, Trace, agent_sessions, fragments
from trackio.cli_helpers import (
    format_trace,
    parse_span_timestamp,
    short_trace_id,
    trace_id_matches,
    trace_rollup,
)
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


def test_trace_logging_and_query(temp_dir):
    run = Run(url=None, project="proj", client=None, name="trace-run", space_id=None)
    run.log(
        {
            "loss": 0.5,
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
            ),
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
    assert logs[0]["loss"] == 0.5
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


def test_trace_search_text_excludes_span_payloads(temp_dir):
    run = Run(url=None, project="proj", client=None, name="trace-run", space_id=None)
    run.log(
        {
            "conversation": Trace(
                messages=[{"role": "user", "content": "find datasets"}],
                spans=[
                    {
                        "id": "generation-a",
                        "name": "provider-request",
                        "kind": "generation",
                        "model": "tiny-model",
                        "status": "success",
                        "metadata": {"attempt": "retry-1"},
                        "input": {"secret_prompt_text": "unindexed-input"},
                        "output": {"text": "unindexed-output"},
                    }
                ],
            )
        }
    )
    run.finish()

    for needle in ("provider-request", "tiny-model", "retry-1", "generation-a"):
        assert len(SQLiteStorage.get_traces("proj", "trace-run", search=needle)) == 1

    for needle in ("unindexed-input", "unindexed-output"):
        assert SQLiteStorage.get_traces("proj", "trace-run", search=needle) == []

    traces = SQLiteStorage.get_traces("proj", "trace-run")
    assert traces[0]["spans"][0]["input"]["secret_prompt_text"] == "unindexed-input"


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


def _pending_trace_project(project: str, log_id: str = "log-1") -> dict:
    SQLiteStorage.bulk_log(
        project=project,
        run="buffered-run",
        run_id="run-1",
        metrics_list=[
            {
                "loss": 0.5,
                "conversation": {
                    "_type": "trackio.trace",
                    "messages": [{"role": "user", "content": "buffered question"}],
                    "metadata": {"session_id": "s-1"},
                    "spans": [
                        {
                            "id": "gen-1",
                            "name": "provider-request",
                            "kind": "generation",
                            "model": "tiny-model",
                            "usage": {"input_tokens": 11, "output_tokens": 3},
                        }
                    ],
                },
            }
        ],
        steps=[0],
        timestamps=["2026-08-19T12:00:00+00:00"],
        log_ids=[log_id],
        space_id="user/space",
    )
    return SQLiteStorage.get_traces(project, "buffered-run", run_id="run-1")[0]


def test_buffered_traces_count_as_pending_data(temp_dir):
    _pending_trace_project("pending-proj")

    pending = SQLiteStorage.get_pending_traces("pending-proj")
    assert pending is not None
    assert pending["space_id"] == "user/space"
    assert pending["traces"][0]["key"] == "conversation"
    assert pending["traces"][0]["log_id"] == "log-1"
    assert SQLiteStorage.has_pending_data("pending-proj") is True

    SQLiteStorage.clear_pending_traces("pending-proj", pending["ids"])
    SQLiteStorage.clear_pending_logs(
        "pending-proj", SQLiteStorage.get_pending_logs("pending-proj")["ids"]
    )
    assert SQLiteStorage.get_pending_traces("pending-proj") is None
    assert SQLiteStorage.has_pending_data("pending-proj") is False
    assert len(SQLiteStorage.get_traces("pending-proj", "buffered-run")) == 1


def test_buffered_traces_replay_into_their_original_log_entry(temp_dir):
    original = _pending_trace_project("replay-source")
    run = Run(url=None, project="unused", client=None, name="r", space_id=None)

    entries = run._pending_entries_with_traces(
        SQLiteStorage.get_pending_logs("replay-source"),
        SQLiteStorage.get_pending_traces("replay-source"),
    )

    assert len(entries) == 1
    metrics = entries[0]["metrics"]
    assert metrics["loss"] == 0.5
    assert metrics["conversation"]["_type"] == "trackio.trace"
    assert metrics["conversation"]["spans"][0]["model"] == "tiny-model"

    imported = fragments.import_records(
        [
            fragments.metric_record(dict(entry, project="replay-target"))
            for entry in entries
        ]
    )
    assert imported == 1

    replayed = SQLiteStorage.get_traces("replay-target", "buffered-run", run_id="run-1")
    assert len(replayed) == 1
    assert replayed[0]["id"] == original["id"]
    assert replayed[0]["spans"] == original["spans"]
    assert replayed[0]["messages"] == original["messages"]
    logs = SQLiteStorage.get_logs("replay-target", "buffered-run")
    assert logs[0]["loss"] == 0.5


def test_buffered_trace_list_keeps_its_index(temp_dir):
    SQLiteStorage.bulk_log(
        project="replay-list",
        run="buffered-run",
        run_id="run-1",
        metrics_list=[
            {
                "conversations": [
                    {
                        "_type": "trackio.trace",
                        "messages": [{"role": "user", "content": "a"}],
                    },
                    {
                        "_type": "trackio.trace",
                        "messages": [{"role": "user", "content": "b"}],
                    },
                ]
            }
        ],
        steps=[0],
        log_ids=["log-list"],
        space_id="user/space",
    )
    original = SQLiteStorage.get_traces("replay-list", "buffered-run", run_id="run-1")
    run = Run(url=None, project="unused", client=None, name="r", space_id=None)

    entries = run._pending_entries_with_traces(
        SQLiteStorage.get_pending_logs("replay-list"),
        SQLiteStorage.get_pending_traces("replay-list"),
    )
    fragments.import_records(
        [
            fragments.metric_record(dict(entry, project="replay-list-target"))
            for entry in entries
        ]
    )

    replayed = SQLiteStorage.get_traces(
        "replay-list-target", "buffered-run", run_id="run-1", sort="step_asc"
    )
    assert sorted(t["index"] for t in replayed) == [0, 1]
    assert sorted(t["id"] for t in replayed) == sorted(t["id"] for t in original)


@pytest.mark.parametrize(
    "timestamp",
    [
        "2026-08-19T12:00:01.2Z",
        "2026-08-19T12:00:01.25Z",
        "2026-08-19T12:00:01.250000+00:00",
        "2026-08-19T12:00:01",
    ],
)
def test_span_timestamps_parse_with_any_fractional_precision(timestamp):
    parsed = parse_span_timestamp(timestamp)
    assert parsed is not None
    assert parsed.tzinfo is not None
    assert parsed.year == 2026


def test_trace_rollup_uses_wall_clock_and_flags_errors():
    rollup = trace_rollup(
        {
            "spans": [
                {
                    "id": "root",
                    "start_time": "2026-08-19T12:00:00Z",
                    "end_time": "2026-08-19T12:00:23.79Z",
                    "status": "success",
                },
                {
                    "id": "gen",
                    "parent_id": "root",
                    "start_time": "2026-08-19T12:00:01Z",
                    "end_time": "2026-08-19T12:00:03Z",
                    "usage": {"input_tokens": 8439, "output_tokens": 188},
                    "cost_usd": 0.0042,
                    "status": "success",
                },
                {"id": "tool", "parent_id": "root", "status": "error"},
            ]
        }
    )
    assert rollup["duration_ms"] == pytest.approx(23790)
    assert rollup["cost_usd"] == pytest.approx(0.0042)
    assert rollup["input_tokens"] == 8439
    assert rollup["output_tokens"] == 188
    assert rollup["status"] == "error"
    assert rollup["span_count"] == 3


def test_short_trace_id_round_trips_to_matching():
    trace = {"id": "run-1:log-abc:conversation"}
    assert short_trace_id(trace["id"]) == "log-abc"
    assert trace_id_matches(trace, "log-abc")
    assert trace_id_matches(trace, "run-1:log-abc:conversation")
    assert not trace_id_matches(trace, "log-xyz")

    indexed = {"id": "run-1:log-abc:conversations:2"}
    assert short_trace_id(indexed["id"]) == "log-abc:2"
    assert trace_id_matches(indexed, "log-abc:2")


def test_format_trace_renders_span_tree_and_errors():
    rendered = format_trace(
        {
            "id": "run-1:log-abc:session",
            "run": "production",
            "step": 3,
            "spans": [
                {
                    "id": "root",
                    "name": "answer-question",
                    "kind": "span",
                    "start_time": "2026-08-19T12:00:00Z",
                    "end_time": "2026-08-19T12:00:02Z",
                },
                {
                    "id": "tool",
                    "parent_id": "root",
                    "name": "run-bash-command",
                    "kind": "tool",
                    "status": "error",
                    "error": {"stderr": "unrecognized arguments: --full"},
                },
            ],
        }
    )
    assert "Trace log-abc" in rendered
    assert "answer-question [span]  2.00s" in rendered
    assert "  ERROR run-bash-command [tool]" in rendered
    assert "unrecognized arguments: --full" in rendered


def _session_records(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _session_files(root):
    return sorted(Path(root).rglob("*.jsonl"))


def _log_trace(project, run, trace, **kwargs):
    SQLiteStorage.bulk_log(
        project=project,
        run=run,
        metrics_list=[{"trace": {"_type": "trackio.trace", **trace}}],
        **kwargs,
    )


def test_logging_a_trace_writes_a_hub_native_session(temp_dir, monkeypatch, tmp_path):
    sessions = tmp_path / "sessions"
    monkeypatch.setenv("TRACKIO_TRACE_SESSIONS_DIR", str(sessions))

    _log_trace(
        "sts",
        "run-a",
        {
            "messages": [
                {"role": "system", "content": "be helpful"},
                {"role": "user", "content": "hello"},
                {
                    "role": "assistant",
                    "content": "looking",
                    "tool_calls": [
                        {
                            "id": "t1",
                            "function": {"name": "search", "arguments": {"q": "x"}},
                        }
                    ],
                },
                {"role": "tool", "tool_call_id": "t1", "content": "done"},
            ],
            "metadata": {"session_id": "s1"},
            "spans": [
                {
                    "id": "g1",
                    "name": "provider-request",
                    "kind": "generation",
                    "model": "my-model",
                    "usage": {"input_tokens": 10, "output_tokens": 2},
                    "cost_usd": 0.5,
                    "status": "success",
                }
            ],
        },
    )

    files = _session_files(sessions)
    assert len(files) == 1
    assert agent_sessions.is_hub_native_jsonl(files[0])

    header, *entries = _session_records(files[0])
    assert header["type"] == "session"
    assert header["version"] == 3
    assert header["harness"] == "trackio"
    assert header["name"] == "hello"
    assert header["trackio"]["run_name"] == "run-a"
    assert header["trackio"]["metadata"] == {"session_id": "s1"}

    # Every entry chains to the one before it.
    parents = [e["parentId"] for e in entries]
    assert parents[0] is None
    assert parents[1:] == [e["id"] for e in entries[:-1]]

    assert entries[0]["type"] == "model_change"
    assert entries[0]["modelId"] == "my-model"

    roles = [e["message"]["role"] for e in entries if e["type"] == "message"]
    assert roles == ["developer", "user", "assistant", "toolResult"]

    assistant = next(
        e["message"] for e in entries if e.get("message", {}).get("role") == "assistant"
    )
    call = next(b for b in assistant["content"] if b["type"] == "toolCall")
    assert call["arguments"] == {"q": "x"}  # a real object, not a JSON string
    assert assistant["usage"]["totalTokens"] == 12
    assert assistant["usage"]["cost"]["total"] == 0.5

    result = next(
        e["message"]
        for e in entries
        if e.get("message", {}).get("role") == "toolResult"
    )
    assert result["toolCallId"] == "t1"
    assert result["toolName"] == "search"
    assert "isError" not in result


def test_tool_failure_marks_the_result_as_an_error(temp_dir, monkeypatch, tmp_path):
    sessions = tmp_path / "sessions"
    monkeypatch.setenv("TRACKIO_TRACE_SESSIONS_DIR", str(sessions))

    _log_trace(
        "sts",
        "run-a",
        {
            "messages": [
                {"role": "user", "content": "run it"},
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {"id": "t1", "function": {"name": "bash", "arguments": "{}"}}
                    ],
                },
                {"role": "tool", "tool_call_id": "t1", "content": "boom"},
            ],
            "metadata": {},
            "spans": [
                {
                    "id": "span-tool",
                    "name": "bash",
                    "kind": "tool",
                    "status": "error",
                    "error": {"code": 2},
                }
            ],
        },
    )

    _, *entries = _session_records(_session_files(sessions)[0])
    result = next(
        e["message"]
        for e in entries
        if e.get("message", {}).get("role") == "toolResult"
    )
    assert result["isError"] is True
    assert result["toolName"] == "bash"


def test_usage_is_paired_per_assistant_turn_not_repeated(
    temp_dir, monkeypatch, tmp_path
):
    """Repeating one span's totals on every turn would double-count in the viewer."""
    sessions = tmp_path / "sessions"
    monkeypatch.setenv("TRACKIO_TRACE_SESSIONS_DIR", str(sessions))

    _log_trace(
        "sts",
        "run-a",
        {
            "messages": [
                {"role": "user", "content": "hi"},
                {"role": "assistant", "content": "one"},
                {"role": "assistant", "content": "two"},
            ],
            "metadata": {},
            "spans": [
                {
                    "id": "g1",
                    "kind": "generation",
                    "start_time": "2026-08-19T12:00:00Z",
                    "usage": {"input_tokens": 10, "output_tokens": 1},
                },
                {
                    "id": "g2",
                    "kind": "generation",
                    "start_time": "2026-08-19T12:00:05Z",
                    "usage": {"input_tokens": 20, "output_tokens": 2},
                },
            ],
        },
    )

    _, *entries = _session_records(_session_files(sessions)[0])
    totals = [
        e["message"]["usage"]["totalTokens"]
        for e in entries
        if e.get("message", {}).get("role") == "assistant"
    ]
    assert totals == [11, 22]


def test_session_omits_span_payloads_but_sqlite_keeps_them(
    temp_dir, monkeypatch, tmp_path
):
    sessions = tmp_path / "sessions"
    monkeypatch.setenv("TRACKIO_TRACE_SESSIONS_DIR", str(sessions))
    spans = [
        {
            "id": "g1",
            "name": "provider-request",
            "kind": "generation",
            "duration_ms": 1234,
            "metadata": {"cold_start": True},
            "input": {"messages": ["a very large payload"]},
        }
    ]

    _log_trace(
        "sts",
        "run-a",
        {
            "messages": [{"role": "user", "content": "hello"}],
            "metadata": {},
            "spans": spans,
        },
    )

    text = _session_files(sessions)[0].read_text()
    assert "a very large payload" not in text

    stored = SQLiteStorage.get_traces("sts", "run-a")
    assert stored[0]["spans"] == spans


def test_span_only_trace_synthesizes_renderable_entries(
    temp_dir, monkeypatch, tmp_path
):
    sessions = tmp_path / "sessions"
    monkeypatch.setenv("TRACKIO_TRACE_SESSIONS_DIR", str(sessions))

    _log_trace(
        "sts",
        "run-a",
        {
            "messages": [],
            "metadata": {},
            "spans": [
                {
                    "id": "b1",
                    "name": "run-bash",
                    "kind": "tool",
                    "start_time": "2026-08-19T12:00:01Z",
                    "input": {"command": "ls"},
                    "output": "ok",
                }
            ],
        },
    )

    _, *entries = _session_records(_session_files(sessions)[0])
    roles = [e["message"]["role"] for e in entries]
    assert roles == ["assistant", "toolResult"]
    call = entries[0]["message"]["content"][0]
    assert call["type"] == "toolCall"
    assert call["arguments"] == {"command": "ls"}
    assert entries[1]["message"]["toolCallId"] == call["id"]


def test_trace_session_write_failure_does_not_break_logging(
    temp_dir, monkeypatch, tmp_path
):
    monkeypatch.setenv("TRACKIO_TRACE_SESSIONS_DIR", str(tmp_path / "sessions"))
    monkeypatch.setattr(
        agent_sessions,
        "write_session",
        lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")),
    )

    with pytest.warns(UserWarning, match="Could not write trace session file"):
        _log_trace(
            "sts",
            "run-a",
            {
                "messages": [{"role": "user", "content": "hello"}],
                "metadata": {},
                "spans": [],
            },
        )

    assert len(SQLiteStorage.get_traces("sts", "run-a")) == 1


def test_sts_files_are_not_treated_as_hub_native(tmp_path):
    """STS is a documented format the viewer does not render, so it needs converting."""
    sts_file = tmp_path / "sts.jsonl"
    sts_file.write_text(
        json.dumps({"type": "session", "harness": "trackio", "id": "abc"}) + "\n"
    )
    assert not agent_sessions.is_hub_native_jsonl(sts_file)

    pi_file = tmp_path / "pi.jsonl"
    pi_file.write_text(
        json.dumps({"type": "session", "version": 3, "id": "abc"}) + "\n"
    )
    assert agent_sessions.is_hub_native_jsonl(pi_file)
