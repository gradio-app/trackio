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
- **M2 (done)** — bayes (numpy-only GP + EI in `trackio/sweep_bayes.py`; wandb-comparable, not bit-identical); command-mode agent with the full wandb macro set + `trackio agent` CLI; `metric.target` global stop. See "M2 implementation notes (as built)" below.
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
| `trackio/sweeps.py` | Pure, no I/O. `validate_sweep_config()` (wandb schema; bayes requires `metric.name`, warns on `early_terminate`, validates `program`/`command`/`metric.target`), the 18 distributions (`sample_parameter`, numpy `Generator`-based), inference rules (`infer_distribution`), nested-parameter flatten/unflatten (dotted paths, specs and values), `GridSuggester` / `RandomSuggester` (+ lazy `_bayes_suggester` factory in `SUGGESTERS`), `next_trial(config, trials, rng)` (also enforces `run_cap`), `target_met()`, `expand_command()` + `is_command_sweep()` (wandb macro set), `param_hash()` (sha256 of key-sorted JSON), sweep/trial state constants + `can_transition_sweep_state()`, env-var name constants (`TRACKIO_SWEEP_ID`, `TRACKIO_SWEEP_TRIAL_ID`, `TRACKIO_SWEEP_PARAMS`, `TRACKIO_SWEEP_PROJECT`). |
| `trackio/sweep_bayes.py` | Pure, numpy-only bayes: `_SpaceEncoder` ([0,1]^d encoding), `_GaussianProcess` (Matern ν=1.5, escalating jitter, grid-fit length scale), `_expected_improvement`, `BayesSuggester` (random fallback < 2 completed, worst-imputation for failed/pruned, Kriging-believer fantasy points for in-flight, EI argmax over 1000 prior-sampled candidates). |
| `trackio/sweep_agent.py` | `SweepClient` — local/remote shim: every operation has a `SQLiteStorage.*` branch and a `RemoteClient.predict(api_name="/sweep_*")` branch; keeps its resolved `space_id`/`server_url` for child-env forwarding. `agent()` — the run loop: suggest → run the trial → safety-net `report_trial(finished)` (no-op if the run already reported, see state guard below). Function mode sets `context_vars.current_sweep_trial` around `function()`; command mode (config has `program`/`command`) runs `_run_command_trial` — `expand_command()` → `subprocess.Popen` with `TRACKIO_SWEEP_*` env vars (plus `TRACKIO_SPACE_ID`/`TRACKIO_SERVER_URL` when remote), nonzero exit → `failed`. Aborts after `MAX_INITIAL_FAILURES=3` consecutive failures; `wait` commands sleep `AGENT_POLL_INTERVAL=5s`. `split_sweep_path()` parses `{project}/{sweep_id}`. `trial_context_from_env()` / `resolve_trial_context()` feed `init()`. |
| `trackio/sqlite_storage.py` | DDL in `init_db` (sweeps + sweep_trials + index). `_SWEEP_PARQUET_TABLES` constant drives parquet export/import/static-export/reserved-suffix validation (mirrors `_ARTIFACT_PARQUET_TABLES`; the import sidecar detector is the shared `_table_sidecar()` in `import_from_parquet`). Methods: `create_sweep`, `get_sweep` (includes `num_trials`/`trial_counts`/`best_metric_value`/`best_run_id` via `_sweep_trial_summary`), `list_sweeps`, `set_sweep_state` (validates transitions), `suggest_trial` (the atomic controller — see invariant above; returns `{"command": "run"|"wait"|"exit", ...}` and flips the sweep to `finished` on exhaustion/run_cap), `mark_trial_running`, `report_trial`, `get_sweep_trials`, `get_sweep_count`. `get_tab_availability_flags` gained a `sweeps` flag. |
| `trackio/server.py` | 8 endpoints registered in `_api_registry()`: `sweep_create`, `sweep_get`, `sweep_list`, `sweep_set_state`, `sweep_suggest_trial`, `sweep_mark_trial_running`, `sweep_report_trial`, `sweep_get_trials`. Mutating ones call `assert_can_mutate_runs(request)` — remote agents authenticate with the existing write token; no new auth. |
| `trackio/__init__.py` | `sweep()` / `agent()` (wandb-compatible signatures; `entity`/`prior_runs` accepted-and-warned). `init()` resolves the trial context (contextvar first, env second), merges `config = {**user_config, **trial_params}`, passes `sweep_id`/`sweep_trial_id`/`sweep_metric_name` into `Run`, and calls `mark_trial_running` after the run exists (local SQLite or `remote_client.predict`). Rejects attach with a warning if the trial's project ≠ `init()`'s project. |
| `trackio/run.py` | `Run` stores `sweep_id` (public attr, wandb parity) and sets `config["_Sweep"]`. `log()` tracks the last numeric value of the sweep metric in `_sweep_metric_last`. `finish()` calls `_report_sweep_trial("finished")` with that value (local or via `_client`). |
| `trackio/context_vars.py` | `current_sweep_trial` contextvar (`{sweep_id, trial_id, params, project, metric_name}`); reset in `tests/conftest.py::temp_dir`. |
| `trackio/api.py` | `Api.sweeps(project)` / `Api.sweep(project, id)` → `Sweeps`/`Sweep` (`.state`, `.config`, `.trials`, `.best_run()`, `.pause()/.resume()/.stop()/.cancel()`), mirroring `Runs`/`Run`. |
| `trackio/cli.py` + `cli_helpers.py` | `trackio sweep new CONFIG --project P` (JSON/TOML native, YAML via soft pyyaml import; prints a `trackio agent` hint for command-mode configs), `list`, `status [--trials]`, `pause/resume/stop/cancel`; all take `--json` and accept `{project}/{sweep_id}` qualified ids; `--space` routes through `SweepClient`. Top-level `trackio agent [PROJECT/]SWEEP_ID [--count N] [--server-url URL]` (M2, command-mode sweeps only). Formatters: `format_sweeps`, `format_sweep_summary`, `format_sweep_trials`. |
| Frontend | `pages/Sweeps.svelte` (sweep table, expandable per-sweep trial table, best-run highlight + links to run detail, lifecycle buttons disabled when mutation not allowed). Wiring: `router.js` (`sweeps` path), `Navbar.ALL_LINKS`, `App.svelte` (import + switch + `OPTIONAL_EMPTY_TABS`/`AUTO_OPEN_TAB_ORDER`/`initialAvailability`), `lib/api.js` (`getSweeps`, `getSweepTrials`, `setSweepState`) **and** `lib/staticApi.js` (reads `aux/sweeps.parquet` + `aux/sweep_trials.parquet`, computes best/counts client-side, `setSweepState` throws in static mode), `grouping.js` `PROMOTED_RESERVED_KEYS._Sweep`. |
| Tests | `tests/unit/test_sweeps.py` (pure logic: schema, inference, sampling determinism/bounds, grid values, nested params, suggesters incl. random-repeats-allowed regression, `target_met`, `expand_command` macros), `test_sweep_bayes.py` (encoder, GP posterior/jitter, EI, fallback/imputation/fantasy, bayes-beats-random seeded check, storage e2e), `test_sweep_storage.py` (lifecycle, run_cap reason, target stop both paths, transition enforcement, first-report-wins, best-metric min/max, reserved suffixes, tab flag, parquet round-trip), `test_sweep_agent.py` (grid e2e exactly-once, config-merge override, `_Sweep` in stored config, count, qualified ids, failure abort + recovery, no-init safety net, 4-thread concurrency exactly-once, env-var attach path, command-mode subprocess e2e + nonzero-exit failure, bayes-through-agent, `Api.sweeps`). Frontend: `grouping.test.js` `_Sweep` promotion cases. |
| Docs | `docs/source/sweeps.md` (+ `_toctree.yml`), `.agents/skills/trackio/sweeps.md` (+ SKILL.md row), `examples/sweep-basic.py`, README table flipped to supported. |

## M2 implementation notes (as built)

M2 shipped three deliverables — `metric.target`, command-mode agents + `trackio agent` CLI, and bayes — plus doc/example updates. Everything below is implemented on this branch; the section doubles as the design rationale. YAML soft-dep was listed under M2 in the original plan but already shipped in M1 (`cli._load_sweep_config_file`).

### 2a. `metric.target` global stop

wandb semantics: once any finished run's metric meets the target, the sweep stops issuing new trials; in-flight runs finish gracefully. Killing in-flight runs is NOT part of this (that's the M3 should-stop channel).

- **Validation** (`sweeps.validate_sweep_config`): `metric.target` must be a number; meaningless without `metric.name` (already required for any `metric` block).
- **Predicate** (pure, in `sweeps.py`): `target_met(config, trials) -> bool` — any trial with `state == 'finished'` and non-null `metric_value` satisfying `value >= target` (maximize) / `value <= target` (minimize).
- **Enforcement point** (`SQLiteStorage.suggest_trial`): per M1 invariant #6, this is the same place run_cap/exhaustion already flip the sweep to `finished`. Check `target_met` on the (already-fetched) trial rows *before* calling `next_trial`; if met, flip to `finished` and return `{"command": "exit", "reason": "target"}`. Requires extending the trial-row projection in `suggest_trial` with `metric_value` — which bayes needs anyway (invariant #7), so do it here first.
- **Also flip in `report_trial`**: after a successful `finished` report whose value meets the target, transition the sweep to `finished` in the same locked transaction. Without this, a sweep whose agents all exited on `count` stays `running` in the UI forever despite having hit its target.
- **`finish_reason` column** (added post-M2, pre-release): `sweeps.finish_reason` records *why* a sweep auto-finished (`exhausted` | `run_cap` | `target`; NULL for manual stop/cancel/finish, where the state is its own reason). Written at the three auto-flip sites (`suggest_trial` exhaustion/run_cap/target, `report_trial` target); read back by `suggest_trial`'s terminal-state branch (`reason: finish_reason or state`) so every agent reports the true reason, not just the one whose call triggered the flip. Threaded through `_SWEEP_PARQUET_TABLES`, `_sweep_row_to_dict`, `staticApi.js` `getSweeps`, the state badge in `Sweeps.svelte`, and `format_sweep_summary` (`state: finished (target)`). DDL includes the column; an idempotent try-`ALTER` migrates pre-existing dev DBs (matching the `metrics` pattern at the top of `init_db`).
- **Tests** (`test_sweep_storage.py`): suggest returns `exit/target` and sweep state flips; minimize vs maximize direction; target NOT triggered by `failed` trials' values; `report_trial` path flips state.

### 2b. Command-mode agent + `trackio agent` CLI

These ship together (a CLI agent has no `function` to call, so it only works with command-mode sweeps — wandb behaves the same way).

**Config schema additions** (`sweeps.validate_sweep_config`):
- `program`: string — the training script path.
- `command`: list of string tokens, each possibly containing macros. Default when absent but `program` present: `["${env}", "${interpreter}", "${program}", "${args}"]`.
- A sweep is *command-mode* iff it has `program` or `command`. Error if `command` references `${program}` but no `program` is set. Function-mode sweeps (no program/command) are unchanged.

**Macro expansion** — pure `expand_command(config, flat_params) -> list[str]` in `sweeps.py`, operating on the *flattened* (dotted-path) params so nested parameters become `--optimizer.lr=0.01`:

| Macro | Expansion |
|---|---|
| `${env}` | `/usr/bin/env` (dropped entirely on Windows, matching wandb) |
| `${interpreter}` | `sys.executable` (deliberate divergence from wandb's bare `python` — venv-correct; document it) |
| `${program}` | `config["program"]` verbatim |
| `${args}` | one `--key=value` token per param, sorted by key |
| `${args_no_boolean_flags}` | as `${args}`, but `True` → bare `--key`, `False` → omitted |
| `${args_no_hyphens}` | `key=value` tokens |
| `${args_json}` | single token: the params dict as compact JSON (nested/unflattened form) |
| `${envvar:NAME}` | `os.environ["NAME"]` (empty string + warning if unset) |

Macros expand only when a token is exactly one macro or contains macros inline (simple string substitution per token; `${args}`-family macros must be a whole token since they expand to multiple argv entries — error otherwise). `${args_json_file}` stays out of scope (M1 decision). Value formatting: `json.dumps` for non-strings so `1e-05`, `True/true` etc. round-trip; bare strings unquoted (wandb convention).

**Runner** (`sweep_agent.py`): `agent()` drops the `function is None` ValueError; instead it branches after `get_sweep`:
- Function mode: exactly as today.
- Command mode (config has program/command): the suggest → report → failure-abort loop is shared; only the "run one trial" body differs. Spawn `subprocess.Popen(expand_command(...), env=child_env)` with inherited stdout/stderr (no tee — the logbook capture machinery isn't needed here; wandb agents also just stream through). `child_env` = `os.environ` plus:
  - `TRACKIO_SWEEP_ID`, `TRACKIO_SWEEP_TRIAL_ID`, `TRACKIO_SWEEP_PARAMS` (nested params as JSON), `TRACKIO_SWEEP_PROJECT` — the M1 env constants; `init()` already resolves them (invariant #5), so **no `init()` changes**.
  - `TRACKIO_SPACE_ID` / `TRACKIO_SERVER_URL` when the agent itself is remote — `utils.resolve_space_id_and_server_url` already reads these, so the child's `init()` attaches to the same backend without script changes.
  - Exit code 0 → safety-net `report_trial(finished)` (no-op if the child's `Run.finish()` already reported with the metric — first-report-wins, invariant #1). Nonzero → `report_trial(failed)`; counts toward `MAX_INITIAL_FAILURES`.
  - Passing `function=` for a command-mode sweep, or no function for a function-mode sweep, is a clear error either way.
- Metric flow needs no new plumbing: in local mode the child process writes to the same SQLite; in remote mode the child's own `Run._client` reports. The agent process never sees the metric value.

**CLI** (`cli.py`): top-level `trackio agent [PROJECT/]SWEEP_ID [--project P] [--count N] [--space SPACE] [--server-url URL]`, routed through `SweepClient` like the other sweep commands. Errors clearly when the target sweep has no `program`/`command` ("run agents for function-mode sweeps via trackio.agent(sweep_id, function=...)"). Update `sweep new` output to print a ready-to-copy `trackio agent {project}/{sweep_id}` line when the config is command-mode. No `-- {command override}` argv support in M2 (wandb parity doesn't require it; the `_maybe_handle_logbook_run_argv` pre-parse pattern is there if it's ever wanted).

**Server**: zero new endpoints — the CLI agent drives the existing eight.

**Tests**: `test_sweeps.py` — every macro, default command synthesis, nested-param arg formatting, boolean-flag variants, whole-token enforcement, program/command validation errors. `test_sweep_agent.py` — command-mode e2e: a tiny temp script that calls `trackio.init()/log()/finish()`, run via a grid sweep, asserting env-var attach, run linkage, metric_value recorded, exactly-once grid coverage; nonzero-exit → failed trial + abort-after-3; `--count`; CLI arg parsing + the function-mode-sweep error.

### 2c. Bayes suggester

**Scope restated (pinned in "Decisions made"):** wandb-*comparable*, not bit-identical. wandb's engine is an sklearn GP (Matern ν=1.5) + Expected Improvement; crucially it does **not** optimize the acquisition with L-BFGS — it samples a candidate pool from the parameter priors and picks the EI argmax. That candidate-set design is what makes a numpy-only port tractable, and it means categorical/quantized/log params need no special acquisition handling: candidates are already valid points in the space.

**Module**: new `trackio/sweep_bayes.py` (pure, numpy-only, ~300–500 lines), exporting `BayesSuggester` registered in `sweeps.SUGGESTERS["bayes"]`. `sweeps.py` changes: move `"bayes"` from `FUTURE_SWEEP_METHODS` into `SWEEP_METHODS`; validation requires `metric.name` + `metric.goal` for bayes.

**Algorithm per `suggest(trials, rng)` call** (stateless — refit every call, fine at sweep scale of ≤ hundreds of trials):
1. **Fallback**: if fewer than 2 trials have `state == 'finished'` with non-null `metric_value`, return a random sample (`sample_parameter` over the flat specs) — wandb's rule.
2. **Vectorize X**: each flat param → one or more [0,1]-normalized dims: bounded numerics `(x - min) / (max - min)`; log-family in log space; `normal`/`log_normal` via the distribution CDF; categoricals one-hot; constants excluded. This lives in a `_SpaceEncoder` class built from the flat specs (also used for candidates).
3. **Build y**: last-logged metric per trial (`metric_value`), sign-flipped for maximize so the GP always minimizes. Normalize to zero-mean/unit-std. **Imputation:** `failed`/`pruned` trials → worst (max) observed y, wandb's rule, so bayes learns to avoid crashing regions. **Fantasy points:** `assigned`/`running` trials enter X with y = the posterior mean of a GP fit on completed trials only (Kriging-believer), so parallel agents don't get near-duplicate proposals.
4. **GP fit**: Matern ν=1.5 kernel; length scale coarsely grid-fit over (0.1, 0.3, 1.0, 3.0) by log marginal likelihood; Cholesky factorization with escalating jitter (1e-8 → 1e-2) on failure, falling back to a random sample if no length scale factorizes. No gradient-based hyperparameter optimizer — this is the accepted deviation from sklearn.
5. **Candidates + EI**: sample ~1000 candidate param dicts from the priors (reusing `sample_parameter`, so q-quantization/int-rounding/log shapes are inherently respected), encode, compute EI against best observed y, return the argmax candidate (as a nested params dict, like the other suggesters).

**Storage plumbing**: `suggest_trial`'s row projection gains `metric_value` (shared with 2a); `next_trial` passes it through untouched. No schema, endpoint, or frontend changes — bayes rides the existing tables and the existing `rng` threading (`suggest` already takes `rng`; keep it seeded in tests).

**Duplicate params are legal** for bayes (M1 invariant #2 — no `UNIQUE(param_hash)`); EI naturally avoids exact repeats once the GP has signal, and the random fallback may repeat, which is fine.

**Tests** (`tests/unit/test_sweep_bayes.py`): encoder round-trips (one-hot, log, CDF, q); GP posterior sanity (predicts training points, uncertainty grows away from data); jitter path on degenerate/duplicate X; EI ≥ 0 and → 0 at the incumbent; fallback below 2 completed; failed-trial imputation steers away from a poisoned region; fantasy point suppresses re-proposing an in-flight optimum; seeded determinism; and one seeded end-to-end statistical test — on a 1-D quadratic, bayes-after-N-trials beats random-after-N on median best-value (loose threshold, fixed seeds, not flaky). Plus a `test_sweep_agent.py` e2e running a short bayes sweep through the real agent loop.

**Insurance policy** (unchanged from the original plan): if the numpy GP underdelivers in practice, the `Suggester` protocol admits an optional optuna-backed extra in M4 with no schema changes.

### M2 file touch list

| Area | Files |
|---|---|
| Pure logic | `trackio/sweeps.py` (target predicate, command/program validation, `expand_command`, SWEEP_METHODS), **new** `trackio/sweep_bayes.py` |
| Storage | `trackio/sqlite_storage.py` — `suggest_trial` (target check + `metric_value` projection), `report_trial` (target flip) |
| Agent | `trackio/sweep_agent.py` — command-mode branch, child-env injection, exit-code reporting |
| CLI | `trackio/cli.py` (+`cli_helpers.py` if output formatting needed) — `trackio agent`, `sweep new` hint line |
| Tests | `tests/unit/test_sweeps.py`, **new** `tests/unit/test_sweep_bayes.py`, `tests/unit/test_sweep_storage.py`, `tests/unit/test_sweep_agent.py` |
| Docs | `docs/source/sweeps.md` (bayes, command mode, `trackio agent`, target), `.agents/skills/trackio/sweeps.md`, **new** `examples/sweep-bayes.py`; `sweep()`/`agent()` docstrings in `trackio/__init__.py` |

No server, frontend, or parquet changes anywhere in M2.

### Invariants and gotchas for future work

1. **First terminal report wins.** `report_trial` only updates rows whose state is `assigned`/`running`. This is what makes the ordering safe when both the agent and `Run.finish()` report (agent reports `failed` before finishing the run → the run's later `finished` report is a no-op, and vice versa). Don't remove the guard.
2. **`suggest_trial` must stay atomic** under `_get_process_lock(project)`. Never move params computation outside the lock, and never add a UNIQUE constraint on `param_hash` (random search legitimately repeats params; a schema constraint with `ON CONFLICT IGNORE` would silently deadlock small categorical spaces).
3. **New sweep-related tables/columns** must be threaded through `_SWEEP_PARQUET_TABLES`, otherwise `trackio sync` / `freeze` silently drops the data. Column lists there must match the DDL exactly (import replays rows positionally by those names).
4. **`Run.sweep_id` is public API** (wandb parity); `_sweep_trial_id` / `_sweep_metric_name` / `_sweep_metric_last` are internal.
5. **Trial context resolution order** in `init()`: `context_vars.current_sweep_trial` (function-mode agent) then env vars (future command-mode). M2's command-mode agent should set the env vars on the child process and needs no `init()` changes.
6. **`suggest_trial` flips the sweep to `finished`** when `next_trial` returns None; the exit reason distinguishes `run_cap` vs `exhausted` vs `target` (M2). `report_trial` also flips the sweep when a finished report meets `metric.target`, so subsequent suggests return reason `finished` (state), not `target`.
7. **Bayes (M2, done)** is the lazy `_bayes_suggester` entry in `sweeps.SUGGESTERS` (lazy import avoids a `sweeps` ↔ `sweep_bayes` circular import); `suggest_trial`'s row projection includes `metric_value`.
8. **Should-stop channel (M3):** add a `sweep_should_stop` endpoint + storage method; `Run` already has the `_start_background_thread` helper for the client-side poller. The `cancel` state currently only stops *new* trials — in-flight runs are not killed until M3.
9. **Dev environment:** HF-internal npm/pip proxies may be unreachable; use `--index-url https://pypi.org/simple` / `--registry https://registry.npmjs.org`, and `SKIP_FRONTEND_BUILD=1` for `pip install -e`. Parquet tests need `pyarrow` (the `spaces` extra).
