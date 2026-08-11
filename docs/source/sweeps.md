# Hyperparameter Sweeps

Trackio can run hyperparameter sweeps: define a search space once, then run one or more agents that execute your training function with different hyperparameter combinations. The API is compatible with `wandb.sweep()` / `wandb.agent()`, so existing wandb sweep configs work unchanged.

## Quickstart

```python
import trackio

sweep_config = {
    "method": "grid",
    "metric": {"name": "loss", "goal": "minimize"},
    "parameters": {
        "lr": {"values": [0.1, 0.01, 0.001]},
        "batch_size": {"values": [16, 32]},
    },
}

sweep_id = trackio.sweep(sweep_config, project="my-project")

def train():
    run = trackio.init(project="my-project")
    lr = run.config["lr"]
    batch_size = run.config["batch_size"]
    for step in range(100):
        loss = train_step(lr, batch_size)
        trackio.log({"loss": loss})
    trackio.finish()

trackio.agent(sweep_id, function=train)
```

The agent asks the sweep for the next hyperparameter combination, calls `function()`, and repeats until the sweep is exhausted, capped, or stopped. Inside `function`, `trackio.init()` automatically attaches the run to the sweep and merges the trial's hyperparameters into `run.config` (sweep values override any defaults passed via `init(config=...)`).

Results appear in the **Sweeps** tab of the dashboard (`trackio show`): each sweep shows its state, trial leaderboard, and best run, with pause/resume/stop/cancel controls. In the sidebar, you can also group runs by sweep.

## Sweep configuration

The config schema follows wandb's:

| Key | Description |
|---|---|
| `method` | Search strategy: `"grid"` or `"random"` (required). |
| `parameters` | The search space (required). |
| `metric` | `{"name": ..., "goal": "minimize"\|"maximize"}` — the metric to optimize. Must be logged as a top-level key via `trackio.log()`. |
| `run_cap` | Maximum total number of trials in the sweep. |
| `name` | Display name for the sweep. |

### Parameter specifications

```python
"parameters": {
    "constant_param": {"value": 42},
    "choice_param": {"values": ["adam", "sgd"]},
    "weighted_choice": {"values": ["a", "b"], "probabilities": [0.7, 0.3]},
    "int_param": {"min": 1, "max": 10},
    "float_param": {"min": 0.0, "max": 1.0},
    "log_param": {"distribution": "log_uniform_values", "min": 1e-5, "max": 1e-1},
    "nested": {
        "parameters": {
            "sub_param": {"values": [1, 2]},
        }
    },
}
```

When `distribution` is omitted, it is inferred: `values` becomes `categorical`, `value` becomes `constant`, integer `min`/`max` becomes `int_uniform`, and float bounds become `uniform`. Explicit distributions include `uniform`, `int_uniform`, `log_uniform_values`, `q_uniform`, `normal`, `log_normal`, `beta`, and their `q_`-quantized variants — the same set wandb supports.

Grid search requires discrete parameters (`value`, `values`, `int_uniform`, or `q_uniform`); continuous distributions raise an error. Random search never terminates on its own — bound it with `run_cap` or the agent's `count`.

## Parallel agents

Multiple agents can share one sweep — trial assignment is atomic, so two agents never receive the same grid cell:

```python
trackio.agent(sweep_id, function=train, count=10)
```

Each agent runs at most `count` trials (unlimited if omitted). Agents on different machines coordinate through a shared trackio server: pass `space_id=` or `server_url=` to both `trackio.sweep()` and `trackio.agent()` to coordinate via a Hugging Face Space or a self-hosted server (requires a write token).

## Managing sweeps from the CLI

```bash
trackio sweep new sweep.yaml --project my-project   # also accepts .json / .toml
trackio sweep list --project my-project
trackio sweep status my-project/abcd1234 --trials
trackio sweep pause my-project/abcd1234
trackio sweep resume my-project/abcd1234
trackio sweep stop my-project/abcd1234
trackio sweep cancel my-project/abcd1234
```

YAML configs require `pyyaml` (`pip install pyyaml`); JSON and TOML work without extra dependencies. Paused sweeps make agents wait; stopped/cancelled sweeps make agents exit.

## Inspecting sweeps from Python

```python
from trackio import Api

api = Api()
for sweep in api.sweeps("my-project"):
    print(sweep.sweep_id, sweep.state)
    print(sweep.trials)
    best = sweep.best_run()
    if best is not None:
        print(best.name, best.config)
```

## Differences from wandb (current limitations)

- **`method: "bayes"` is not supported yet** — configs using it raise a clear error. Use `random` with a `run_cap` in the meantime.
- **`early_terminate` (hyperband) is not supported yet** — it is accepted but ignored, with a warning.
- **Command-based agents are not supported yet** — `trackio.agent()` requires `function=`; sweep configs with `program`/`command` cannot be executed by an agent. There is no `trackio agent` CLI command yet for the same reason.
- `entity` and `prior_runs` are accepted for wandb compatibility but ignored.
- Sweeps are scoped to a single project.
