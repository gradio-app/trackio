# Trackio Hyperparameter Sweeps

Sweeps run a training function across a hyperparameter search space. The API is compatible with `wandb.sweep()` / `wandb.agent()`.

## Core API

### trackio.sweep()

```python
sweep_id = trackio.sweep(
    {
        "method": "grid",                                # "grid" or "random"
        "metric": {"name": "loss", "goal": "minimize"},  # metric to optimize
        "run_cap": 20,                                   # optional total-trial cap
        "parameters": {
            "lr": {"values": [0.1, 0.01, 0.001]},
            "batch_size": {"min": 16, "max": 64},        # int range
            "wd": {"distribution": "log_uniform_values", "min": 1e-6, "max": 1e-2},
        },
    },
    project="my-project",
)
```

### trackio.agent()

```python
def train():
    run = trackio.init(project="my-project")
    lr = run.config["lr"]                # sweep params injected into config
    for step in range(100):
        trackio.log({"loss": compute_loss(lr)})
    trackio.finish()

trackio.agent(sweep_id, function=train, count=10)  # count = max trials (optional)
```

Key facts:
- `trackio.init()` inside `function` auto-attaches the run to the sweep; sweep params override `init(config=...)` defaults.
- The optimized metric must be logged as a **top-level key** via `trackio.log()`.
- Multiple agents can share a sweep id (parallel machines/processes); trial assignment is atomic.
- Grid sweeps finish when exhausted; random sweeps need `run_cap` or `count`.
- An agent aborts after 3 consecutive failed trials; failed trials are recorded with state `failed`.

## CLI

```bash
trackio sweep new sweep.yaml --project P     # create from .yaml (needs pyyaml) / .json / .toml
trackio sweep list --project P [--json]
trackio sweep status P/SWEEP_ID --trials [--json]
trackio sweep pause|resume|stop|cancel P/SWEEP_ID
```

`--json` output includes sweep state, trial counts, `best_metric_value`, and `best_run_id` — poll `trackio sweep status` to monitor a running sweep.

## Python inspection

```python
from trackio import Api
sweep = Api().sweep("my-project", sweep_id)
sweep.state          # running | paused | finished | stopped | cancelled
sweep.trials         # list of dicts: trial_id, state, params, metric_value, run_id
sweep.best_run()     # trackio.api.Run or None
```

## Not supported yet (fails loudly or warns)

- `method: "bayes"` — raises an error; use `random` + `run_cap`.
- `early_terminate` (hyperband) — accepted with a warning, but trials are not pruned.
- Command-based agents (`program`/`command` config keys, `trackio agent` CLI) — `trackio.agent()` requires `function=`.
- `entity` / `prior_runs` arguments — accepted for wandb compatibility, ignored.
