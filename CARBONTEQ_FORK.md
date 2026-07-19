# CarbonTeq AI Trackio fork

This repository is an additive fork of
[`gradio-app/trackio`](https://github.com/gradio-app/trackio). It preserves the
Trackio Python package, HTTP API, SQLite and Parquet persistence, artifacts, and
the existing UI while adding platform-specific observability integrations.

## Current extension

`trackio.VerifiersTrace` stores a queryable display projection alongside the
complete JSON-safe Verifiers trace record. Native Verifiers `traces.jsonl`
remains authoritative. Trackio is an idempotent, query-optimized copy keyed by
`(run_id, trace_type, external_id)`.

The existing `trackio.Trace` type is unchanged. The existing UI renders the
projected messages; there is no fork-specific trace UI in this phase.

## Upstream baseline

| CarbonTeq release | Upstream repository | Upstream commit |
| --- | --- | --- |
| Unreleased | `gradio-app/trackio` | `438cb28d2c82c7b7d42431e45d5677a8cc90eb77` |

Every CarbonTeq release must add a row before it is tagged. Platform consumers
must pin an immutable CarbonTeq commit rather than a branch or tag.

## Updating from upstream

```bash
git fetch upstream
git switch main
git pull --ff-only origin main
git switch -c maintenance/upstream-YYYY-MM-DD
git merge --no-ff upstream/main
uv sync --extra dev --extra spaces
uv run pytest tests/unit -q
git push -u origin maintenance/upstream-YYYY-MM-DD
```

Open a pull request into `carbonteq-ai/trackio:main`. Resolve conflicts by
keeping upstream behavior intact and reapplying only the additive Verifiers
fields. Before merging, verify standard traces, metrics, artifacts, API queries,
SQLite migrations, and Parquet round trips as well as the Verifiers tests.

The repository should keep these remotes:

```text
origin    git@github.com:carbonteq-ai/trackio.git
upstream  https://github.com/gradio-app/trackio.git
```

Rust, Tokio, Doris, object-storage redesign, and a custom frontend are deferred
and are not part of this fork contract.
