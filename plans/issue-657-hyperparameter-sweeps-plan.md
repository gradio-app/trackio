## Issue 657 Plan: Hyperparameter Sweeps

### Goal

Add the ability to define and run a hyperparameter search with Trackio, and
group the resulting runs so they can be compared in the dashboard.

Full scope of #657 ("define, launch, and monitor sweeps... view results
along with parallel coordinates chart") is large. This first PR covers the
backend piece only:

- Define a search space (grid or random) as a small dict/YAML-shaped config.
- Run it locally, in-process, by calling a user-supplied training function
  once per configuration.
- Automatically merge the sweep-selected hyperparameters into `config` and
  group the resulting runs under a shared sweep id when `trackio.init()` is
  called from inside that function.

Out of scope for this PR (left for follow-ups):

- A parallel-coordinates chart in the Svelte dashboard.
- Bayesian / other advanced search strategies.
- A hosted sweep controller or distributed/remote agents (`wandb agent`-style).
- CLI-driven sweeps over an arbitrary subprocess command.

### Decisions

- No new storage/schema changes: sweeps reuse the existing `config` (per-run
  hyperparameters) and `group` (already-supported run grouping) fields, so
  existing dashboard grouping/filtering works with sweeps for free.
- Orchestration is local and synchronous (a plain `for` loop calling the
  training function), matching Trackio's "local-first" design instead of
  introducing a server-side sweep controller.
- API mirrors `wandb`'s `sweep_config` shape (`method`, `parameters` with
  `values` or `min`/`max`) so existing wandb sweep configs mostly drop in.
- Sweep-selected values take precedence over any matching keys already in
  the `config` dict passed to `trackio.init()`, since overriding local
  defaults is the point of a sweep. An explicit `group=` passed to
  `trackio.init()` still wins over the sweep's auto-assigned group.

### Implementation

1. Add `trackio/sweep.py`.
   - `SweepParameter`: one parameter's search space (`values`, or
     `min`/`max` with `distribution="uniform"|"int_uniform"`).
   - `SweepConfig`: `parameters`, `method` (`"grid"` | `"random"`), `name`.
   - `generate_configs(sweep_config, count=None)`: materializes the list of
     configs (full cartesian product for grid, `count` samples for random).
   - `sweep(sweep_config, function, count=None, sweep_id=None)`: generates
     configs, then for each one sets context vars for the sweep id/config
     and calls `function()`.

2. Add two context vars in `trackio/context_vars.py`:
   `current_sweep_id`, `current_sweep_config`.

3. Wire into `trackio.init()`: if a sweep is active (context var set), merge
   its config into the run's `config` and default `group` to the sweep id.

4. Export `sweep`, `SweepConfig`, `SweepParameter`, and
   `generate_configs` (as `sweep_generate_configs`) from `trackio/__init__.py`.

5. Add `examples/hyperparameter-sweep.py` and `tests/unit/test_sweep.py`
   (config generation edge cases + `init()` integration).

### Follow-ups (separate PRs)

- Parallel-coordinates chart component in `trackio/frontend/src/` that plots
  each run in a group/sweep as a line across parameter + metric axes.
- `trackio sweep` CLI command to launch a sweep over an external script
  (subprocess-based, injecting hyperparameters as CLI flags or env vars).
- Early stopping / pruning of underperforming sweep runs.
