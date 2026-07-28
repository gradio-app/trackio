# CarbonTeq AI Trackio fork

This repository is an additive fork of
[`gradio-app/trackio`](https://github.com/gradio-app/trackio). It preserves the
Trackio Python package, HTTP API, SQLite-compatible and Parquet persistence,
artifacts, and the existing UI while adding platform-specific observability
integrations.

## Python distribution

CarbonTeq publishes the fork as `carbonteq-trackio` while preserving the
`trackio` import package and `trackio` console command. The current fork release
is `0.31.5.post5`, derived from upstream Trackio `0.31.5`.
Post-release numbers advance when CarbonTeq publishes additional fork changes
without moving the upstream base.

Framework packages must depend on `carbonteq-trackio`, not the upstream-owned
`trackio` distribution and not a transitive Git URL. Self-deployed Trackio
Spaces use the same CarbonTeq distribution identity so the deployed runtime
retains the fork's storage, trace, and query behavior.

## Current extension

`trackio.VerifiersTrace` stores a queryable display projection alongside the
complete JSON-safe Verifiers trace record. Native Verifiers `traces.jsonl`
remains authoritative. Trackio is an idempotent, query-optimized copy keyed by
`(run_id, trace_type, external_id)`.

The existing `trackio.Trace` type and trace UI are unchanged. Verifiers traces
have a separate `/verifiers` workspace because a rollout is a graph with
branches, rewards, model calls, tools, phase timing, and environment errors—not
just a conversation. The Verifiers UI renders structured projections and links
each rollout to its producing experiment; it never displays the raw payload.
For an evaluation run, it also joins the selected rollout to the run's aggregate
`eval/*` metrics so per-rollout evidence and overall results remain distinct but
visible together.

The bundled dashboard uses the secure Vega 6 dependency line (`vega` 6.3.1,
`vega-lite` 6.4.3, and `vega-embed` 7.1.0). Trackio emits Vega-Lite v6 schemas,
keeps the canvas renderer explicit across the Embed 7 default-renderer change,
and escapes dashboard-generated axis-label lookup expressions before Vega
parses them. Frontend release gates include a production dependency audit,
representative hostile-label compilation/execution, the complete frontend test
suite, and a reproducible wheel build containing the generated dashboard. This
upgrade closes `GHSA-7f2v-3qq3-vvjf` in Vega expressions and
`GHSA-m9rg-mr6g-75gm` in `vega-functions`; the lock also carries patched
Svelte, Vite, and Vitest releases and both full and production-only audits must
remain at zero.

The self-hosted artifact API supports bounded, resumable uploads for model-sized
blobs. The client negotiates an 8 MiB chunk size, acknowledges chunks
idempotently, resumes a deterministic upload session after a client or server
restart, verifies every chunk and the complete SHA-256, and commits an artifact
version only after every manifest blob is durable. Servers without this
capability retain the legacy path for files up to 32 MiB; the client refuses
larger legacy uploads instead of buffering them in server memory.

Incomplete upload sessions are project-scoped staging state. Cleanup reports
reclaimable bytes in dry-run mode and expires only incomplete, aged sessions.
Completed content-addressed blobs and artifact versions are not eligible for
session cleanup.

## Storage engine

Turso is the default SQL metadata engine through the `pyturso` embedded driver.
It retains Trackio's SQLite-compatible database-per-project model and local-first
operation. Set `TRACKIO_DATABASE_ENGINE=sqlite` for the stdlib SQLite fallback.

Apache Doris is implemented as a first-class engine selected with
`TRACKIO_DATABASE_ENGINE=doris`. Its native provider and migration path have
passed real-Doris SDK/HTTP, clean-schema bootstrap, content-reconciled
migration, artifact, restart, concurrency, SQLite/Turso regression,
backup/restore, retained-project migration, and deployed Trackio/Observatory
checks. Metric time windows, canonical run listing, tab classification,
artifact relogging, legacy-link folding, and stable ordering match the logical
SQLite provider behavior. Doris is authoritative for run, metric,
system-metric, trace, alert, artifact-metadata, and lineage records; it is not
a downstream analytical projection. Model and media bytes remain behind
Trackio's existing server-managed artifact boundary.

This implementation is published on the CarbonTeq fork and must be consumed by
immutable commit. The current deployment is still bound to an older
source-diff and wheel-digest receipt until the corrected Trackio/Observatory
services are rebuilt and promoted. Operate one Trackio server replica until
artifact-version allocation is made safe across replicas.

Raw project SQL remains deliberately unavailable with Doris because its tables
are shared across projects rather than stored in one project-local database.
The first release remains single-server: the process lock and idempotent
artifact operations do not provide cross-process version allocation or a
multi-table transaction. HA requires a staged or optimistic artifact protocol
and schema-level coordination before additional Trackio writers are allowed.

Turso stores run, metric, trace, artifact-manifest, and lineage metadata. It is
not the object store: media, model bytes, and native evaluation bundles remain
under Trackio's existing artifact/file storage boundary. A hosted Hugging Face
Space is optional and is not required for local operation. Remote sync can be
added later without changing the Trackio SDK contract.

## Upstream baseline

| CarbonTeq release | Upstream repository | Upstream commit |
| --- | --- | --- |
| `0.31.5.post1` | `gradio-app/trackio` | `438cb28d2c82c7b7d42431e45d5677a8cc90eb77` |
| `0.31.5.post2` | `gradio-app/trackio` | `438cb28d2c82c7b7d42431e45d5677a8cc90eb77` |
| `0.31.5.post3` | `gradio-app/trackio` | `438cb28d2c82c7b7d42431e45d5677a8cc90eb77` |
| `0.31.5.post4` | `gradio-app/trackio` | `438cb28d2c82c7b7d42431e45d5677a8cc90eb77` |
| `0.31.5.post5` | `gradio-app/trackio` | `438cb28d2c82c7b7d42431e45d5677a8cc90eb77` |

`0.31.5.post4` adds project-scoped bulk read APIs so a client can describe every
run without one configuration request and one history request per run:

- `SQLiteStorage.get_run_lifecycles` / `DorisStorage.get_run_lifecycles` and
  shared shaping in `trackio/lifecycle.py`
- server `/get_run_lifecycles`
- client `Api.run_lifecycles` and `Api.run_configs`

`0.31.5.post4` on `carbonteq/stable` was published with distribution metadata
`post4` while `trackio._version.__version__` still said `post3`. That index is
non-volatile, so `0.31.5.post5` is the corrected release: same APIs, matching
import and distribution versions. Do not install `post4` from the index.

Every CarbonTeq release must add a row before it is tagged. Platform consumers
should prefer the published `carbonteq-trackio` distribution once it is on the
configured index; until then they may pin an immutable CarbonTeq commit.

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
fields. Before merging, verify both Turso and SQLite modes, standard traces,
metrics, artifacts, API queries, SQLite-compatible migrations, Parquet round
trips, and both trace UIs as well as the Verifiers tests.

The repository should keep these remotes:

```text
origin    git@github.com:carbonteq-ai/trackio.git
upstream  https://github.com/gradio-app/trackio.git
```

Rust, Tokio, and direct worker access to object-storage credentials remain
deferred. Native Doris support is additive; Trackio's existing server-managed
artifact store remains the byte-storage boundary.
