---
"trackio": minor
---

feat: Add additional support for autonomous ML experiments

- `trackio.watch()` / `trackio.should_stop()`: register metric watchers (NaN/Inf, threshold, spike, stagnation, custom fn) that fire alerts automatically on every `trackio.log()` call
- `AlertReason` constants for programmatic alert filtering
- Run lifecycle status tracking (`running` → `finished` / `failed`) persisted in SQLite, routed through `/set_run_status` for Space / self-hosted runs (no more local-DB stub pollution)
- New CLI commands: `trackio best`, `trackio compare`, `trackio summary` — work in both local and `--space` remote mode
- New `trackio.Api(space=..., hf_token=...)` for reading remote-hosted projects from Python; `Run.status`, `Run.final_metrics()`, `Run.metrics()`, `Run.history()`, `Run.alerts()` on the Python API
- `alerts.data` column (SQL migration) for structured alert metadata, propagated through `server.bulk_alert` to remote dashboards
