# Trackio Hyperparameter Sweeps — wandb Parity Plan

## Context

Trackio markets itself as a drop-in wandb replacement, but had no sweep support (the README comparison table listed it as missing). This plan documents wandb's sweeps feature set (researched from official docs and the `wandb/sweeps` engine source), the trackio design chosen for parity, the milestone breakdown, and what is explicitly out of scope. **Milestone 1 is implemented** — see "M1 implementation notes (as built)" below for the file-level map future contributors should start from.

## wandb feature inventory (what parity means)

In rough priority order:

1. **`wandb.sweep(config) -> sweep_id`** and **`wandb.agent(sweep_id, function=..., count=...)`** Python API; CLI `wandb sweep config.yaml` / `wandb agent SWEEP_ID --count N`.
2. **Sweep config schema**: `method` (grid | random | bayes), `metric {name, goal, target}`, `parameters` with ~18 distributions, distribution inference (`values`→categorical, `value`→constant, int min/max→int_uniform, float→uniform), nested parameters, `run_cap`, `program`/`command` with macros (`${env}`, `${interpreter}`, `${program}`, `${args}`, ...).
3. **Search methods**: grid (product + seen-hash dedup), random (i.i.d.), bayes (GP Matern ν=1.5 + Expected Improvement, random fallback until 2 completed runs, failed runs imputed as worst, fantasy points for parallel agents).
4. **Multi-agent coordination**: N agents share a sweep_id; a central controller hands out distinct configs; agents are dumb pollers receiving run/stop/exit commands.
5. **Lifecycle**: pause / resume / stop (graceful) / cancel (kill running trials); global stops: `run_cap`, `metric.target`, grid exhaustion; per-agent `count`.
6. **Run↔sweep association**: agent sets env vars; `wandb.init()` auto-attaches and merges sweep params into config (sweep values override `init(config=)` defaults); `run.sweep_id` exposed.
7. **Early termination**: hyperband only (bands from `min_iter*eta^i` or `max_iter/eta^i`; prune below the 1/eta percentile at each band; strict vs best-so-far).
8. **UI**: sweep list with state/progress, trial leaderboard + best-run highlight, lifecycle buttons, parallel-coordinates plot, scatter, parameter-importance panel.

wandb itself lacks: native multi-objective, conditional search spaces, parameter constraints, any early-stop besides hyperband. Trackio does not need to exceed wandb here.

## Architecture: pure controller module, dual-mode invocation

Sweep logic lives in a pure module; sweep state lives in the per-project SQLite DB; trial suggestion is a synchronous, request-driven function — **no daemon controller**.

- **Local mode** (no server running): `trackio.agent()` calls `SQLiteStorage.suggest_trial(...)` directly.
- **Remote mode** (HF Space / self-hosted server): the agent calls the `sweep_suggest_trial` endpoint via `RemoteClient`; the endpoint invokes the same storage function server-side.

**Concurrency invariant — the `ProcessLock` is the invariant, not the server:** `suggest_trial` atomically (reads trial history → computes next params → INSERTs the trial row) inside one `ProcessLock`-guarded transaction, so two agents never receive the same grid cell. This holds in both modes because the endpoint calls the same function taking the same lock. Grid dedup happens in code inside this transaction; there is deliberately **no** `UNIQUE(sweep_id, param_hash)` constraint, because duplicate parameter sets are legitimate for random (and possible for bayes).

## Data model

Two tables in the per-project DB, created idempotently in `SQLiteStorage.init_db`:

- `sweeps(sweep_id PK, name, config JSON, method, metric_name, metric_goal, state, created_at, updated_at)` — state: running | paused | finished | stopped | cancelled (created directly in `running`; no `pending` state).
- `sweep_trials(trial_id AUTOINCREMENT, sweep_id, params JSON, param_hash, state, run_id, agent_id, metric_value, created_at, updated_at)` — state: assigned | running | finished | failed | pruned.

**Metric-value semantics (pinned):** `metric_value` is the **last-logged** value of `metric.name` at trial finish, matching wandb's summary semantics. It drives leaderboard ordering and will feed bayes. Hyperband (M3) reads full metric history from the existing metrics table, not this cache.

**Run linkage, both directions:** `sweep_trials.run_id` is authoritative; additionally the run's config gets the reserved key `_Sweep = sweep_id` (like `_Group`), which gives sweep runs free sidebar grouping via `PROMOTED_RESERVED_KEYS` in the frontend.

**Space-restart caveat:** on a deployed Space, `CommitScheduler` syncs SQLite → parquet every 5 minutes, so a Space restart can lose up to 5 minutes of trial assignments (in-flight `assigned` trials vanish; grid cells get re-issued or orphaned). Documented limitation, interacts with the stale-trial-reclamation open question.

## Milestones

- **M1 (done)** — grid + random, `run_cap`, `trackio.sweep()`/`trackio.agent()` (function mode), CLI `sweep new/list/status/pause/resume/stop/cancel`, storage + endpoints + parquet/static export, Sweeps dashboard tab, docs + skills + example + tests.
- **M2** — bayes (numpy-only GP + EI: input normalization, one-hot categoricals, log-transforms, jitter, fantasy points, worst-imputation for failed trials; scoped wandb-comparable, not bit-identical — realistically 300–500 lines); command-mode agent with the full wandb macro set + `trackio agent` CLI (inseparable: the CLI agent only works with command-mode sweeps); `metric.target` global stop.
- **M3** — should-stop polling channel (`Run` background thread polls a `sweep_should_stop` endpoint; doubles as the graceful-kill channel for `cancel`), hyperband pruning, `run.should_stop`, `SweepDetail.svelte` + parallel-coordinates + scatter plots (Vega-Lite supports both natively).
- **M4 (optional)** — correlation-only importance panel (Pearson/Spearman), `prior_runs` retro-attach, `trackio sweep delete`, optional optuna backend extra behind the `Suggester` protocol.

## Out of scope (documented, not built)

- wandb Launch / queue-based remote scheduling.
- `method: custom`, external schedulers, and the `wandb.controller()` local-controller API (the `Suggester` protocol + public suggest endpoint leave the door open).
- Multi-objective optimization (wandb itself only offers it via custom schedulers).
- Random-forest parameter importance (needs sklearn; correlation-only panel in M4 instead).
- Agent heartbeats / crash detection with trial reclamation (agents mark trials failed on exceptions; orphaned `assigned` trials are left alone in M1).
- Conditional/hierarchical search spaces and inter-parameter constraints (wandb doesn't have them either; nested `parameters` namespacing IS supported).
- `${args_json_file}` macro; cross-project sweeps.

## Decisions made

- **Bayes backend:** numpy-only GP + EI (numpy is already a hard dep; zero new deps), pluggable via the `Suggester` protocol.
- **Early termination:** M3, sharing the should-stop channel built for `cancel`; configs with `early_terminate` warn loudly until then.
- **UI scope:** sweep list + lifecycle in M1; parallel coordinates + scatter in M3; correlation-only importance in M4.
- **YAML:** soft-optional pyyaml; JSON/TOML natively.
- **CLI shape:** top-level `trackio agent` (M2, wandb parity) rather than `trackio sweep agent`.
- **Stale trials:** left orphaned in M1 (a grid may not auto-finish if an agent dies mid-trial; re-suggest works after the orphan is the only cell left — revisit with reclamation in a later milestone).

---

## M1 implementation notes (as built)

Read this before extending sweeps. Everything below exists on this branch.

### Module map

| File | What it contains |
|---|---|
| `trackio/sweeps.py` | Pure, no I/O. `validate_sweep_config()` (wandb schema; rejects `bayes` with a clear error, warns on `early_terminate`), the 18 distributions (`sample_parameter`, numpy `Generator`-based), inference rules (`infer_distribution`), nested-parameter flatten/unflatten (dotted paths), `GridSuggester` / `RandomSuggester`, `next_trial(config, trials, rng)` (also enforces `run_cap`), `param_hash()` (sha256 of key-sorted JSON), sweep/trial state constants + `can_transition_sweep_state()`, env-var name constants (`TRACKIO_SWEEP_ID`, `TRACKIO_SWEEP_TRIAL_ID`, `TRACKIO_SWEEP_PARAMS`, `TRACKIO_SWEEP_PROJECT`). |
| `trackio/sweep_agent.py` | `SweepClient` — local/remote shim: every operation has a `SQLiteStorage.*` branch and a `RemoteClient.predict(api_name="/sweep_*")` branch. `agent()` — the run loop: suggest → set `context_vars.current_sweep_trial` → call `function()` → finish run → safety-net `report_trial(finished)` (no-op if the run already reported, see state guard below). Aborts after `MAX_INITIAL_FAILURES=3` consecutive failures; `wait` commands sleep `AGENT_POLL_INTERVAL=5s`. `split_sweep_path()` parses `{project}/{sweep_id}`. `trial_context_from_env()` / `resolve_trial_context()` feed `init()`. |
| `trackio/sqlite_storage.py` | DDL in `init_db` (sweeps + sweep_trials + index). `_SWEEP_PARQUET_TABLES` constant drives parquet export/import/static-export/reserved-suffix validation (mirrors `_ARTIFACT_PARQUET_TABLES`; the import sidecar detector is the shared `_table_sidecar()` in `import_from_parquet`). Methods: `create_sweep`, `get_sweep` (includes `num_trials`/`trial_counts`/`best_metric_value`/`best_run_id` via `_sweep_trial_summary`), `list_sweeps`, `set_sweep_state` (validates transitions), `suggest_trial` (the atomic controller — see invariant above; returns `{"command": "run"|"wait"|"exit", ...}` and flips the sweep to `finished` on exhaustion/run_cap), `mark_trial_running`, `report_trial`, `get_sweep_trials`, `get_sweep_count`. `get_tab_availability_flags` gained a `sweeps` flag. |
| `trackio/server.py` | 8 endpoints registered in `_api_registry()`: `sweep_create`, `sweep_get`, `sweep_list`, `sweep_set_state`, `sweep_suggest_trial`, `sweep_mark_trial_running`, `sweep_report_trial`, `sweep_get_trials`. Mutating ones call `assert_can_mutate_runs(request)` — remote agents authenticate with the existing write token; no new auth. |
| `trackio/__init__.py` | `sweep()` / `agent()` (wandb-compatible signatures; `entity`/`prior_runs` accepted-and-warned). `init()` resolves the trial context (contextvar first, env second), merges `config = {**user_config, **trial_params}`, passes `sweep_id`/`sweep_trial_id`/`sweep_metric_name` into `Run`, and calls `mark_trial_running` after the run exists (local SQLite or `remote_client.predict`). Rejects attach with a warning if the trial's project ≠ `init()`'s project. |
| `trackio/run.py` | `Run` stores `sweep_id` (public attr, wandb parity) and sets `config["_Sweep"]`. `log()` tracks the last numeric value of the sweep metric in `_sweep_metric_last`. `finish()` calls `_report_sweep_trial("finished")` with that value (local or via `_client`). |
| `trackio/context_vars.py` | `current_sweep_trial` contextvar (`{sweep_id, trial_id, params, project, metric_name}`); reset in `tests/conftest.py::temp_dir`. |
| `trackio/api.py` | `Api.sweeps(project)` / `Api.sweep(project, id)` → `Sweeps`/`Sweep` (`.state`, `.config`, `.trials`, `.best_run()`, `.pause()/.resume()/.stop()/.cancel()`), mirroring `Runs`/`Run`. |
| `trackio/cli.py` + `cli_helpers.py` | `trackio sweep new CONFIG --project P` (JSON/TOML native, YAML via soft pyyaml import), `list`, `status [--trials]`, `pause/resume/stop/cancel`; all take `--json` and accept `{project}/{sweep_id}` qualified ids; `--space` routes through `SweepClient`. Formatters: `format_sweeps`, `format_sweep_summary`, `format_sweep_trials`. |
| Frontend | `pages/Sweeps.svelte` (sweep table, expandable per-sweep trial table, best-run highlight + links to run detail, lifecycle buttons disabled when mutation not allowed). Wiring: `router.js` (`sweeps` path), `Navbar.ALL_LINKS`, `App.svelte` (import + switch + `OPTIONAL_EMPTY_TABS`/`AUTO_OPEN_TAB_ORDER`/`initialAvailability`), `lib/api.js` (`getSweeps`, `getSweepTrials`, `setSweepState`) **and** `lib/staticApi.js` (reads `aux/sweeps.parquet` + `aux/sweep_trials.parquet`, computes best/counts client-side, `setSweepState` throws in static mode), `grouping.js` `PROMOTED_RESERVED_KEYS._Sweep`. |
| Tests | `tests/unit/test_sweeps.py` (pure logic: schema, inference, sampling determinism/bounds, grid values, nested params, suggesters incl. random-repeats-allowed regression), `test_sweep_storage.py` (lifecycle, run_cap reason, transition enforcement, first-report-wins, best-metric min/max, reserved suffixes, tab flag, parquet round-trip), `test_sweep_agent.py` (grid e2e exactly-once, config-merge override, `_Sweep` in stored config, count, qualified ids, failure abort + recovery, no-init safety net, 4-thread concurrency exactly-once, env-var attach path, `Api.sweeps`). Frontend: `grouping.test.js` `_Sweep` promotion cases. |
| Docs | `docs/source/sweeps.md` (+ `_toctree.yml`), `.agents/skills/trackio/sweeps.md` (+ SKILL.md row), `examples/sweep-basic.py`, README table flipped to supported. |

### Invariants and gotchas for future work

1. **First terminal report wins.** `report_trial` only updates rows whose state is `assigned`/`running`. This is what makes the ordering safe when both the agent and `Run.finish()` report (agent reports `failed` before finishing the run → the run's later `finished` report is a no-op, and vice versa). Don't remove the guard.
2. **`suggest_trial` must stay atomic** under `_get_process_lock(project)`. Never move params computation outside the lock, and never add a UNIQUE constraint on `param_hash` (random search legitimately repeats params; a schema constraint with `ON CONFLICT IGNORE` would silently deadlock small categorical spaces).
3. **New sweep-related tables/columns** must be threaded through `_SWEEP_PARQUET_TABLES`, otherwise `trackio sync` / `freeze` silently drops the data. Column lists there must match the DDL exactly (import replays rows positionally by those names).
4. **`Run.sweep_id` is public API** (wandb parity); `_sweep_trial_id` / `_sweep_metric_name` / `_sweep_metric_last` are internal.
5. **Trial context resolution order** in `init()`: `context_vars.current_sweep_trial` (function-mode agent) then env vars (future command-mode). M2's command-mode agent should set the env vars on the child process and needs no `init()` changes.
6. **`suggest_trial` flips the sweep to `finished`** when `next_trial` returns None; the exit reason distinguishes `run_cap` vs `exhausted`. `metric.target` (M2) belongs in the same place.
7. **Bayes (M2)** plugs in as a third `Suggester` in `sweeps.SUGGESTERS`; `suggest_trial` already passes full trial history (params + state; extend the row projection with `metric_value` when bayes lands — it's already stored).
8. **Should-stop channel (M3):** add a `sweep_should_stop` endpoint + storage method; `Run` already has the `_start_background_thread` helper for the client-side poller. The `cancel` state currently only stops *new* trials — in-flight runs are not killed until M3.
9. **Dev environment:** HF-internal npm/pip proxies may be unreachable; use `--index-url https://pypi.org/simple` / `--registry https://registry.npmjs.org`, and `SKIP_FRONTEND_BUILD=1` for `pip install -e`. Parquet tests need `pyarrow` (the `spaces` extra).
