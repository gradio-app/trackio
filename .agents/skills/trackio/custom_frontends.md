# Building Custom Frontends for Trackio Logs

Use this reference when a user wants a custom dashboard, report page, or one-off visualization on top of Trackio data — i.e. "vibecoding" a UI against their runs. You do **not** need to fork or rebuild Trackio's Svelte dashboard. Every piece of data the built-in dashboard renders is also reachable through a stable Python API, CLI, or HTTP endpoint.

## Three Data Access Surfaces

| Surface | Use when |
|---|---|
| **Python `trackio.Api`** | You're writing a Python script, Jupyter notebook, Gradio/Streamlit/FastAPI app, or any backend that runs alongside Trackio data |
| **`trackio query` CLI with `--json`** | You're writing a shell script, a static site generator, or an LLM agent that shells out |
| **HTTP API** (`POST {server}/api/<name>`) | You're building a frontend (JS/HTML, Next.js, etc.) that talks to a running `trackio show` server or HF Space |

All three are read-only-safe by default. The SQLite schema (`metrics`, `configs`, `alerts`, `system_metrics`) is documented in [storage_schema.md](storage_schema.md).

## Python: `trackio.Api`

```python
import trackio

api = trackio.Api()
runs = api.runs("my-project")        # iterable of Run objects
for run in runs:
    print(run.name, run.config)
    print(run.alerts(level="error")) # list of alert dicts

alerts = api.alerts("my-project", run="my-run", since="2026-04-01T00:00:00")
```

For metric values, go directly through `SQLiteStorage` or the SQL path:

```python
from trackio.sqlite_storage import SQLiteStorage

logs = SQLiteStorage.get_logs(project="my-project", run="my-run")  # list of flat dicts
rows = SQLiteStorage.query_project(
    "my-project",
    "SELECT step, json_extract(metrics, '$.loss') AS loss FROM metrics WHERE run_name = 'my-run' ORDER BY step",
)
```

## CLI → JSON (piping into any frontend)

Every read command accepts `--json`. The output is stable and safe to parse from a build script or LLM agent:

```bash
trackio list projects --json
trackio get run --project my-project --run my-run --json
trackio query project --project my-project --sql "SELECT run_name, MAX(step) FROM metrics GROUP BY run_name" --json
```

Add `--space <space_id_or_url>` to any of these to hit a remote Trackio server (HF Space or self-hosted) instead of local data.

## HTTP API (for browser-based frontends)

A running `trackio show` server (or an HF Space) exposes the same endpoints the built-in dashboard uses. Handler names come from `trackio/server.py::_api_registry()`:

```
POST {server}/api/get_all_projects           -> { "data": ["proj1", "proj2", ...] }
POST {server}/api/get_runs_for_project       -> { "data": [ { "name": ..., "id": ..., "created_at": ... }, ... ] }
POST {server}/api/get_run_summary            -> { "data": { "last_step": ..., "metrics": {...} } }
POST {server}/api/get_metrics_for_run        -> { "data": [...] }     # timeseries
POST {server}/api/get_metric_values          -> { "data": [...] }     # single metric
POST {server}/api/get_system_metrics_for_run -> { "data": [...] }
POST {server}/api/get_alerts                 -> { "data": [...] }
POST {server}/api/query_project              -> { "data": {...} }     # read-only SQL
POST {server}/api/get_settings               -> { "data": {...} }     # logo, palette, etc.
```

Every request body is JSON; required parameters go as top-level keys. Example:

```bash
curl -s -X POST http://127.0.0.1:7860/api/get_metric_values \
     -H "content-type: application/json" \
     -d '{"project":"my-project","run":"my-run","metric":"loss"}'
```

Responses always wrap the payload in `{"data": ...}`, or `{"error": ...}` on failure. See [api_mcp_server.md](../../../docs/source/api_mcp_server.md) for the same endpoints exposed as an MCP server.

## Parquet Export (for dbt, DuckDB, Observable, etc.)

For offline or BI-style visualization, Trackio ships a parquet export. Trigger it from Python:

```python
from trackio.sqlite_storage import SQLiteStorage
SQLiteStorage.export_to_parquet()   # writes {project}.parquet + aux/*.parquet under TRACKIO_DIR
```

Files are flattened — one column per JSON key, plus `step`, `run_name`, `timestamp`. DuckDB can read them directly:

```sql
-- duckdb shell
SELECT run_name, MAX(step) FROM '~/.cache/huggingface/trackio/my-project.parquet' GROUP BY run_name;
```

See [storage_schema.md](storage_schema.md) for the full layout.

## Suggested Workflow for a Vibecoded Dashboard

1. **Decide the surface.**
   - Python/Jupyter → `trackio.Api` + `SQLiteStorage.query_project`.
   - Static HTML/React/Next.js → hit the HTTP API of a running Trackio server.
   - Shell/static site → `trackio ... --json` in a Makefile.
2. **Scope the SQL.** Inspect `trackio/sqlite_storage.py::SQLiteStorage.init_db()` or [storage_schema.md](storage_schema.md) to find the right tables, then prototype the query with `trackio query project --project ... --sql "..."`.
3. **Keep it read-only.** `query_project` rejects writes; use the same SQL when you move to the HTTP `query_project` endpoint. No need to touch SQLite files directly.
4. **Reuse existing settings.** `get_settings` returns logo URLs, color palette, plot order, and `media_dir` — pull them so a custom dashboard matches the main one's look without hardcoding.
5. **Point at whichever server you want.** All three surfaces accept either local data or a remote server URL / HF Space id, so the same code works against a dev laptop and a production Space with a single string change.

## What Not to Do

- Don't edit the SQLite files directly from a frontend — use the HTTP `query_project` or `SQLiteStorage.query_project` so the same validation and concurrency rules apply.
- Don't reverse-engineer endpoints that aren't in `_api_registry()` — they're internal and will change.
- Don't hold a long-lived `RemoteClient` from a web frontend; it's a Python helper. Hit the HTTP endpoints with `fetch` instead.
