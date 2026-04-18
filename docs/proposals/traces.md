# Trackio Traces: GRPO Rollout Logging & Viewer

## Context

ML researchers running GRPO-style RL training want to log and inspect rollouts — prompt/completion/reward rows across training steps — with conversation-style rendering and slicing by reward / step / model version. `trackio.Table()` already stores this data shape, but the viewer is a flat HTML table: long completions are hard to read, there's no way to filter to "low-reward rollouts at step 2000," and there's no multi-turn message structure.

Goal: a native `trackio.Trace()` primitive that renders chat-style, slices across steps by metadata, and rides the existing SQLite → parquet → HF Space export path. No OTEL in v1; the native schema has to settle first.

Non-goals for v1: nested span/tool-call tree viewers, side-by-side diff, OTEL/Phoenix exporter, dataset-per-run push.

## Proposed Python API

```python
import trackio

trackio.init(project="grpo-run")

# GRPO one-liner — the common case
trackio.log({
    "rollout": trackio.Trace(
        prompt="What is 2+2?",
        completion="2+2 = 4",
        metadata={"reward": 0.9, "model_version": "step-2000"},
    )
})

# Full multi-turn form (OpenAI chat format)
trackio.log({
    "rollout": trackio.Trace(
        messages=[
            {"role": "system", "content": "You are a math tutor."},
            {"role": "user", "content": "What is 2+2?"},
            {"role": "assistant", "content": "2+2 = 4"},
        ],
        metadata={"reward": 0.9, "model_version": "step-2000", "group_id": "g42"},
    )
})

# Batch logging — a list of traces at one step
trackio.log({
    "rollouts": [
        trackio.Trace(prompt=p, completion=c, metadata={"reward": r})
        for p, c, r in zip(prompts, completions, rewards)
    ]
})
```

### Trace constructor

```python
class Trace:
    def __init__(
        self,
        messages: list[dict] | None = None,      # OpenAI chat format
        metadata: dict | None = None,            # flat, filterable: reward, model_version, group_id, ...
        prompt: str | list[dict] | None = None,  # sugar: string → user msg
        completion: str | None = None,           # sugar: string → assistant msg
    ): ...
```

- `prompt` + `completion` is sugar for the GRPO case so users don't have to assemble `messages`.
- `metadata` is flat `dict[str, scalar]` because the UI promotes its keys to filter chips. Nested values are allowed but not indexed.
- `messages` follows OpenAI chat format (role/content, optional `tool_calls`) — the de-facto standard that TRL, vLLM, and Transformers pipelines already emit.

## Using with TRL

TRL's `GRPOTrainer` exposes completions + rewards inside the training loop. The integration is a one-line callback:

```python
from trl import GRPOTrainer, GRPOConfig
import trackio

trackio.init(project="trl-grpo")

def log_rollouts(prompts, completions, rewards, step, model_version):
    trackio.log({
        "rollouts": [
            trackio.Trace(
                prompt=p,
                completion=c,
                metadata={"reward": float(r), "step": step, "model_version": model_version},
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
# Hook log_rollouts into the trainer's on_step_end callback or inside reward_funcs.
trainer.train()
```

Once `trackio` is listed in TRL's `report_to`, `trackio.init` is called automatically. The rollout callback above can live in a `TrainerCallback` subclass in user code, or — as a follow-up — ship inside `trl.trackio` so that passing `report_to="trackio"` gives traces out of the box. That follow-up lines up with [trl#4818](https://github.com/huggingface/trl/pull/4818).

## UI / UX notes

The run view gets a new **Traces** tab (sibling of the metrics plots), visible only when a run contains any trace-typed log.

```
┌─ Run: grpo-run-2026-04-18 ─────────────────────────────────────────┐
│  [Metrics]  [Traces]  [System]  [Config]                           │
├──────────────────────┬─────────────────────────────────────────────┤
│  Filter:             │  step 2000 · reward 0.12 · model step-2000  │
│  reward: [0 ──●──1]  │  ┌──────────────────────────────────────┐   │
│  model:  step-2000 ▾ │  │ system   You are a math tutor.       │   │
│  step:   [0 ─── 5k]  │  │ user     What is 2+2?                │   │
│  sort:   reward ↑    │  │ assistant 2 plus 2 equals five.      │   │
│                      │  │          (markdown + code highlight) │   │
│  ● step 2000  r=.12  │  └──────────────────────────────────────┘   │
│    "2 plus 2..."     │                                             │
│  ○ step 2000  r=.34  │                                             │
│    "The answer..."   │                                             │
│  ○ step 2100  r=.91  │                                             │
│    ...               │                                             │
└──────────────────────┴─────────────────────────────────────────────┘
```

Two panes:

1. **Left — rollout list.** Virtualized list across all steps in the run. Each row: step, one-line preview of the assistant reply, and the most salient metadata (reward badge, model version). A filter bar on top generates chips automatically from metadata keys present in the run: numeric keys (reward) become range sliders, string keys (model_version) become dropdowns, `step` is always available. Sort dropdown supports reward asc/desc and step asc/desc.
2. **Right — chat viewer.** Selected trace renders role-tagged bubbles (system/user/assistant/tool) with markdown + code block highlighting and collapsible long content. Metadata shown as a key/value strip above the conversation.

New Svelte components (under `trackio/frontend/src/components/`):

- `TraceList.svelte` — left pane + filter bar
- `TraceViewer.svelte` — right pane chat rendering
- `TraceFilters.svelte` — metadata-driven filter controls

Reuses the markdown/code rendering utilities already in `GradioTable.svelte`.

## Storage & export

No schema change. Traces are serialized via `_to_dict()` and ride inside the existing `metrics` JSON blob (same path as `Table` and `Histogram`). `SQLiteStorage.export_for_static_space()` already flattens `metrics` into `metrics.parquet`, so traces sync to HF Datasets for free when a run is deployed to a Space — which is the "push traces to HF Dataset" story.

A read-side helper `SQLiteStorage.get_traces(project, run, filters, sort, limit, offset)` walks the metrics JSON, pulls rows where `_type == "trackio.trace"`, and filters/sorts in memory. Fine at ~10k rollouts; promote to a materialized `traces` table later if it bottlenecks.

## Files to modify

- `trackio/trace.py` — new `Trace` class
- `trackio/__init__.py` — export `Trace`
- `trackio/run.py` — handle `Trace` in `log()` (around line 818, next to the `Table` branch)
- `trackio/ui/main.py` — new `get_traces` endpoint via `gr.api()`
- `trackio/sqlite_storage.py` — new `get_traces()` helper
- `trackio/frontend/src/components/TraceList.svelte` — new
- `trackio/frontend/src/components/TraceViewer.svelte` — new
- `trackio/frontend/src/components/TraceFilters.svelte` — new
- `trackio/frontend/src/` — wire Traces tab into run view
- `tests/test_trace.py` — unit round-trip + filter/sort
- `tests/e2e/` — end-to-end logging + query
- `README.md` — usage section

## Reuse (don't re-invent)

- `serialize_values()` — `trackio/utils.py:898`
- `Table._to_dict` pattern — `trackio/table.py`
- `TrackioMedia` — the path forward for images inside messages (multimodal)
- `SQLiteStorage.bulk_log` / `export_for_static_space` — `trackio/sqlite_storage.py:375`, `:850`
- `GradioTable.svelte` markdown/image rendering utilities

## Verification

1. `pytest tests/test_trace.py tests/e2e/` — unit + e2e logging round-trip, including filter/sort queries
2. `ruff check --fix --select I && ruff format`
3. Manual: adapt [AmineDiro's GRPO gist](https://gist.github.com/AmineDiro/3df6521bd3bf9405f913120551fe9fce) to log via `trackio.Trace`. Launch `trackio show` and confirm:
   - Traces tab appears on the run
   - Filter by `reward < 0.2` narrows the list
   - Sort by reward ascending surfaces failures first
   - Chat viewer renders roles + markdown + code blocks
4. Deploy to an HF Space, confirm `metrics.parquet` contains trace rows and is loadable via `datasets.load_dataset`.

## Deferred (explicitly out of v1)

- OTEL / OpenInference exporter (revisit once schema settles; aligns with [trl#4818](https://github.com/huggingface/trl/pull/4818))
- Nested tool-call span tree viewer
- Side-by-side completion diff
- Dataset-per-run push (Aditya: "interesting feature in the future")
- Multimodal content parts in the viewer (schema allows it, viewer ignores non-text for v1)
