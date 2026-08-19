# Traces

Trackio traces capture a user request, the assistant response, and the operations
that produced it. Open the **Traces** page in the dashboard to search requests,
inspect model and tool operations, and see latency, token, cost, and status totals.

## Log a conversation

Pass a [`Trace`](./api#trace) to `trackio.log()` with OpenAI-style
messages:

```python
import trackio

trackio.init(project="research-agent")
trackio.log(
    {
        "trace": trackio.Trace(
            messages=[
                {"role": "user", "content": "Find agent training datasets."},
                {"role": "assistant", "content": "Here are three datasets..."},
            ],
            metadata={"session_id": "session-123", "environment": "production"},
        )
    }
)
trackio.finish()
```

Messages can include `tool_calls` and `tool` results. When a trace has no explicit
spans, the dashboard pairs those calls and results into tool operations for easier
inspection.

## Add execution spans

Use `spans` when you need timings, hierarchy, model usage, cost, or operation
status. Each span is a dictionary. The minimal fields are `id`, `name`, and `kind`:

```python
trackio.Trace(
    messages=messages,
    spans=[
        {
            "id": "research",
            "name": "answer-research-question",
            "kind": "span",
            "start_time": "2026-08-19T12:00:00Z",
            "end_time": "2026-08-19T12:00:03Z",
            "status": "success",
        },
        {
            "id": "generation-1",
            "parent_id": "research",
            "name": "provider-request",
            "kind": "generation",
            "start_time": "2026-08-19T12:00:00Z",
            "end_time": "2026-08-19T12:00:01.2Z",
            "model": "my-model",
            "input": {"messages": messages},
            "output": {"text": "I will search for datasets."},
            "usage": {"input_tokens": 8439, "output_tokens": 188},
            "cost_usd": 0.0042,
            "status": "success",
        },
        {
            "id": "tool-1",
            "parent_id": "research",
            "name": "hf search",
            "kind": "tool",
            "start_time": "2026-08-19T12:00:01.3Z",
            "end_time": "2026-08-19T12:00:02Z",
            "input": {"query": "agent training datasets"},
            "output": {"datasets": ["example/dataset"]},
            "status": "success",
        },
    ],
)
```

Supported span fields:

| Field | Description |
|---|---|
| `id` | Identifier unique within the trace |
| `parent_id` | Optional parent span ID; creates the execution tree |
| `name` | Operation name shown in the inspector |
| `kind` | `span`, `generation`, or `tool` |
| `start_time`, `end_time` | ISO-8601 timestamps used to derive latency |
| `duration_ms` | Optional duration when timestamps are unavailable |
| `status` | Usually `success` or `error` |
| `error` | Structured or textual error details |
| `input`, `output` | Any JSON-serializable operation payload |
| `model` | Model identifier for a generation |
| `usage` | `input_tokens`, `output_tokens`, and optional `total_tokens` |
| `cost_usd` | Cost for this operation in US dollars |
| `metadata` | Additional operation metadata |

Trace latency is wall-clock time from the earliest span start to the latest span
end. Token and cost totals sum the values on individual spans, so `cost_usd` should
describe the local operation rather than a parent aggregate. Trackio does not
maintain a model pricing catalog; instrumentation should supply the actual cost.

Nested Trackio media values in messages, metadata, span input, or span output are
stored alongside the trace.
