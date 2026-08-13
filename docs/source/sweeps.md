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
| `method` | Search strategy: `"grid"`, `"random"`, or `"bayes"` (required). |
| `parameters` | The search space (required). |
| `metric` | `{"name": ..., "goal": "minimize"\|"maximize", "target": ...}` — the metric to optimize. Must be logged as a top-level key via `trackio.log()`. When `target` is set, the sweep finishes as soon as a trial reaches it. Required for `method: "bayes"`. |
| `run_cap` | Maximum total number of trials in the sweep. |
| `name` | Display name for the sweep. |
| `program` / `command` | Command-based sweeps: the training script and optional command template (see below). |

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

Grid search requires discrete parameters (`value`, `values`, `int_uniform`, or `q_uniform`); continuous distributions raise an error. Set `randomize_order: true` at the top level of the config to visit grid combinations in random order. Random search never terminates on its own — bound it with `run_cap`, `metric.target`, or the agent's `count`.

## Bayesian optimization

`method: "bayes"` suggests trials with a Gaussian-process surrogate (Matern kernel) and Expected Improvement, comparable to wandb's bayes engine and implemented with numpy only — no extra dependencies. It requires `metric.name` so trial results can guide the search:

```python
sweep_config = {
    "method": "bayes",
    "metric": {"name": "loss", "goal": "minimize"},
    "run_cap": 40,
    "parameters": {
        "lr": {"distribution": "log_uniform_values", "min": 1e-5, "max": 1e-1},
        "optimizer": {"values": ["adam", "sgd"]},
    },
}
```

The first two trials are sampled randomly; after that, each suggestion maximizes Expected Improvement over candidates drawn from the parameter priors. Failed trials are treated as worst-case observations so the search steers away from crashing regions, and in-flight trials from parallel agents are accounted for so agents don't receive near-duplicate suggestions. Like random search, bayes never exhausts the space — bound it with `run_cap` or `metric.target`.

## Command-based sweeps and the CLI agent

Instead of a Python `function`, a sweep can launch your training script as a subprocess — set `program` (and optionally `command`) in the config, wandb-style:

```yaml
method: bayes
metric:
  name: loss
  goal: minimize
program: train.py
parameters:
  lr:
    min: 0.0001
    max: 0.1
```

Then run agents from the CLI:

```bash
trackio sweep new sweep.yaml --project my-project
trackio agent my-project/abcd1234 --count 10
```

Each trial runs `program` with the hyperparameters passed as `--key=value` arguments (nested parameters become dotted flags like `--optimizer.lr=0.001`). Inside the script, call `trackio.init()` as usual — the agent passes the trial context through environment variables, so the run attaches to the sweep and `run.config` contains the trial's hyperparameters automatically.

The default command is `${env} ${interpreter} ${program} ${args}`. Set `command` to customize it, using wandb's macros:

| Macro | Expands to |
|---|---|
| `${env}` | `/usr/bin/env` (omitted on Windows) |
| `${interpreter}` | The agent's Python interpreter (`sys.executable`) |
| `${program}` | The `program` value |
| `${args}` | `--key=value` for every hyperparameter |
| `${args_no_boolean_flags}` | Like `${args}`, but `True` becomes a bare `--key` and `False` is omitted |
| `${args_no_hyphens}` | `key=value` pairs |
| `${args_json}` | All hyperparameters as one JSON string |
| `${envvar:NAME}` | The value of environment variable `NAME` |

For example, to run training through a shell wrapper:

```yaml
program: train.py
command:
  - ${env}
  - bash
  - wrapper.sh
  - ${program}
  - ${args_no_hyphens}
```

`trackio.agent(sweep_id)` (without `function=`) also runs command-based sweeps from Python. Command-based agents work against remote sweeps too: `trackio agent --space ...` or `--server-url ...` forwards the connection to the subprocess so its run logs to the same server.

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

- **`early_terminate` (hyperband) is not supported yet** — it is accepted but ignored, with a warning.
- **Bayesian optimization is wandb-comparable, not identical** — trackio's numpy GP uses the same kernel family and acquisition strategy as wandb's engine but is not a bit-for-bit port, so the exact suggestion sequence differs.
- `${interpreter}` expands to the agent's own Python interpreter (`sys.executable`) rather than wandb's bare `python`, so command-based sweeps respect virtual environments. The `${args_json_file}` macro is not supported.
- `entity` and `prior_runs` are accepted for wandb compatibility but ignored.
- Sweeps are scoped to a single project.
