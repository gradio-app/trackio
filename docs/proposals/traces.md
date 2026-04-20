# Trackio Traces: Generic Conversational Trace Logging & Viewer

## Context

Trackio needs a native trace primitive for logging and inspecting conversational and agent-style executions: multi-turn messages, assistant responses, tool calls, and associated metadata. Today, `trackio.Table()` can store some of this shape, but the viewing experience is still a flat table, which makes long exchanges, tool use, and inline media hard to inspect.

The motivating use case is GRPO and TRL-style training, but the product surface should not be defined around GRPO alone. The v1 should stay generic enough to support agent runs, environment interactions, and future OTEL-compatible directions without prematurely committing to a full span hierarchy.

Goal: introduce a native `trackio.Trace()` primitive plus a lightweight viewer for browsing and expanding traces in the dashboard, while reusing the existing SQLite -> parquet -> HF Space export path.

## Product position for v1

`trackio.Trace` is a generic conversational / agent trace primitive for logging message sequences, tool calls, metadata, and multimodal content, with a lightweight viewer for inspection and search.

GRPO remains an important motivating example, but not the product definition.

## Non-goals for v1

- Full `Project -> Run/Group -> Trace -> Span` hierarchy
- Parent / child span trees
- OTEL / OpenInference / Phoenix exporter
- Reward-specific or GRPO-specific UX as the default product surface
- Advanced metadata query builder
- Side-by-side completion diffing
- Dataset-per-run push

## Proposed Python API

```python
import trackio

trackio.init(project="agent-run")

trackio.log({
    "trace": trackio.Trace(
        messages=[
            {"role": "system", "content": "You are a concise math tutor."},
            {"role": "user", "content": "What is 2+2?"},
            {"role": "assistant", "content": "2+2 = 4"},
        ],
        metadata={"model_version": "step-2000", "group_id": "g42"},
    )
})
```

### Trace constructor

```python
class Trace:
    def __init__(
        self,
        messages: list[dict],
        metadata: dict | None = None,
    ): ...
```

- `messages` follows OpenAI chat-style structure so it works naturally with existing LLM tooling.
- `messages` should support `role`, `content`, and optional tool / function-call fields.
- `metadata` stays user-defined and unopinionated. No special reward schema in the core type.

### Message shape for v1

Supported message shapes in v1:

- Standard conversational roles: `system`, `user`, `assistant`
- Tool / function-related entries represented using OpenAI-compatible fields
- `content` can be plain text in v1
- The schema should leave room for image content parts so environment screenshots can be rendered inline when present

We should align as closely as possible with OpenAI chat format rather than inventing a custom message schema.

## Example usage tracks

We should ship three examples alongside the feature so users can immediately understand how `Trace` is meant to be used:

1. **Basic example**
   Log a simple single-turn or short multi-turn trace with plain text messages and metadata.
2. **More complex example**
   Show a richer trace with multiple turns, a tool / function call, and optionally inline image content.
3. **TRL integration example**
   Show how a TRL training loop or callback logs traces during training.

These examples should live in a discoverable place and be referenced from the README / docs for the feature.

## Using with TRL

TRL remains a key integration story for v1, but it should be presented as one example of `Trace`, not the defining abstraction.

```python
from trl import GRPOTrainer, GRPOConfig
import trackio

trackio.init(project="trl-grpo")

def log_rollouts(prompts, completions, rewards, step, model_version):
    trackio.log({
        "traces": [
            trackio.Trace(
                messages=[
                    {"role": "user", "content": p},
                    {"role": "assistant", "content": c},
                ],
                metadata={
                    "reward": float(r),
                    "step": step,
                    "model_version": model_version,
                },
            )
            for p, c, r in zip(prompts, completions, rewards)
        ]
    }, step=step)

trainer = GRPOTrainer(
    model="Qwen/Qwen2.5-0.5B",
    reward_funcs=[my_reward_fn],
    args=GRPOConfig(output_dir="out", report_to="trackio"),
    train_dataset=ds,
)
trainer.train()
```

Once `trackio` is listed in TRL's `report_to`, `trackio.init` is called automatically. The logging callback can live in user code in v1; a tighter `trl.trackio` integration can follow later.

## UI / UX notes

The dashboard gets a **Traces** page / tab, visible only when a run contains trace-typed logs.

The v1 UI should stay consistent with the rest of Trackio:

- No bespoke gradient-heavy styling
- No oversized exploratory control surface
- Filters should live in the sidebar where possible
- The main page should primarily be the trace list itself

### Main page structure

Top row:

- Search box: `Search traces by request`
- Sort dropdown
- Result count

Sidebar filters for v1:

- Minimal only
- Example: model version
- Avoid opinionated controls like a dedicated reward slider as the core default experience

Main body:

- Compact table / list of traces, closer to observability tooling than a custom chat app
- Each row shows trace id, request preview, step / time, selected metadata, and state if available
- Clicking a row expands it inline to reveal the full conversation

Expanded trace view:

- Render multi-turn conversations cleanly
- Use collapsible sections or max-height scroll constraints for very long content
- Distinguish normal messages from tool / function calls
- Render inline images when present in message content

### Search behavior

The search bar should semantically search across trace content, not just trace id.

For v1:

- Simple substring matching across flattened request / response / message content / metadata is acceptable
- Do not promise true FTS unless backend work is explicitly added

### Filtering behavior

The filtering model should remain generic and metadata-driven over time, but the v1 UI should be intentionally narrow.

For v1:

- Keep the visible filter set small
- Avoid hard-coding reward as a privileged first-class product concept
- Leave room for generic metadata filtering later, based on detected field types

## Storage & export

No schema change in v1. Traces are serialized via `_to_dict()` and ride inside the existing `metrics` JSON blob, same path as `Table` and `Histogram`.

`SQLiteStorage.export_for_static_space()` already flattens `metrics` into `metrics.parquet`, so traces sync to HF Datasets automatically when a run is deployed to a Space.

A read-side helper such as `SQLiteStorage.get_traces(project, run, search, sort, limit, offset)` can walk the metrics JSON, pull rows where `_type == "trackio.trace"`, and apply simple filtering / search in memory. This is acceptable for v1 scale; a materialized `traces` table can be introduced later if needed.

## Files to modify

- `trackio/trace.py` — new `Trace` class
- `trackio/__init__.py` — export `Trace`
- `trackio/run.py` — handle `Trace` in `log()`
- `trackio/ui/main.py` — new `get_traces` endpoint via `gr.api()`
- `trackio/sqlite_storage.py` — new `get_traces()` helper
- `trackio/frontend/src/` — wire `Traces` into the dashboard
- `tests/test_trace.py` — unit round-trip tests
- `tests/e2e/` — end-to-end logging + query tests
- `README.md` — usage section
- `examples/` or docs examples — three usage examples: basic, complex, TRL integration

## Reuse (don't re-invent)

- `serialize_values()` — `trackio/utils.py:898`
- `Table._to_dict` pattern — `trackio/table.py`
- `TrackioMedia` — path forward for images inside trace messages
- `SQLiteStorage.bulk_log` / `export_for_static_space` — `trackio/sqlite_storage.py`
- Existing frontend table / layout patterns instead of introducing a bespoke trace-only design system

## Verification

1. `pytest tests/test_trace.py tests/e2e/`
   Covers trace round-trip, simple search, and inline expansion data loading.
2. `ruff check --fix --select I && ruff format`
3. Manual dashboard verification:
   - Traces page appears only when trace logs exist
   - Search narrows traces by content, not just id
   - Expanded rows render multi-turn conversations
   - Tool / function-call messages render distinctly
   - Very long content is constrained and remains readable
   - Inline images render when present
4. Docs / examples verification:
   - Basic example runs
   - Complex example runs
   - TRL example runs
5. Deploy to an HF Space and confirm `metrics.parquet` contains trace rows that are loadable via `datasets.load_dataset`

## Deferred (explicitly out of v1)

- Full span hierarchy with parent / child relationships
- OTEL / OpenInference exporter
- Advanced metadata filter builder
- True full-text search indexing
- Nested span tree viewer
- Side-by-side completion diff
- Dataset-per-run push
