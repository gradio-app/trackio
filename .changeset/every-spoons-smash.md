---
"trackio": minor
---

feat: Add additional support for autonomous ML experiments

- `trackio.watch()` / `trackio.should_stop()`: register metric watchers (NaN/Inf, threshold, spike, stagnation, custom fn) that fire alerts automatically on every `trackio.log()` call
- `AlertReason` constants for programmatic alert filtering
- Run lifecycle status tracking (`running` → `finished` / `failed`) persisted in SQLite
- New CLI commands: `trackio best`, `trackio compare`, `trackio summary`
- `Run.status`, `Run.final_metrics`, `Run.metrics()`, `Run.history()` on the Python API
- `alerts.data` column (SQL migration) for structured alert metadata
