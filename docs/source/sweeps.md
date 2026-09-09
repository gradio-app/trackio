# Hyperparameter Sweeps

Trackio intentionally does not ship a first-class sweep API. A sweep is a plain Python loop: one run per configuration, grouped so that the dashboard and queries can treat the sweep as a unit. This keeps sweeps fully under your control — any search strategy you can write (or ask a coding agent to write) works, with nothing new to learn.

This page collects recipes for the common cases.

## The Pattern

Every recipe below is a variation of the same three ingredients:

- **One run per configuration** — call [`init`] once per trial.
- **`group`** — set it to a sweep identifier so all trials of one sweep stay together (see [Grouping runs](./track#grouping-runs)).
- **`config`** — record the hyperparameters, so results are comparable later.

```python
import trackio

def train(config: dict, group: str, name: str) -> float:
    trackio.init(project="my_project", name=name, group=group, config=config)

    final_loss = None
    for epoch in range(10):
        final_loss = ...  # your actual training step
        trackio.log({"loss": final_loss, "epoch": epoch})

    trackio.finish()
    return final_loss
```

## Grid Search

Enumerate the full cartesian product of the search space with `itertools.product`:

```python
import itertools

search_space = {
    "lr": [1e-2, 1e-3, 1e-4],
    "batch_size": [32, 128],
}

best = None
for values in itertools.product(*search_space.values()):
    config = dict(zip(search_space.keys(), values))
    name = "grid-" + "-".join(f"{k}={v}" for k, v in config.items())
    loss = train(config, group="grid-search", name=name)
    if best is None or loss < best[1]:
        best = (config, loss)

print(f"best config: {best[0]} (loss {best[1]:.3f})")
```

## Random Search

Sample configurations instead of enumerating them — usually a better use of the same budget when some hyperparameters matter much more than others. Seed the generator so the sweep is reproducible:

```python
import random

N_TRIALS = 20
rng = random.Random(42)

best = None
for trial in range(N_TRIALS):
    config = {
        "lr": 10 ** rng.uniform(-5, -1),
        "batch_size": rng.choice([16, 32, 64, 128, 256]),
    }
    loss = train(config, group="random-search", name=f"random-{trial}")
    if best is None or loss < best[1]:
        best = (config, loss)
```

## Bayesian Optimization with Optuna

For smarter search strategies, use a dedicated library and let Trackio do the tracking. With [Optuna](https://optuna.org) (`pip install optuna`), each trial becomes one Trackio run:

```python
import optuna

def objective(trial):
    config = {
        "lr": trial.suggest_float("lr", 1e-5, 1e-1, log=True),
        "batch_size": trial.suggest_categorical("batch_size", [16, 32, 64, 128]),
    }
    return train(config, group="optuna-sweep", name=f"optuna-{trial.number}")

study = optuna.create_study(direction="minimize")
study.optimize(objective, n_trials=20)

print("best:", study.best_params, study.best_value)
```

## Viewing Sweep Results

In the dashboard (`trackio show`), runs that share a `group` are grouped together in the sidebar, so a sweep can be toggled on and off as a unit and its runs compared on the same charts. Since every trial records its hyperparameters in `config`, sweeps are also a natural fit for comparing run configurations side by side.

## Querying the Best Configuration

Because everything is in SQLite, "which configuration won?" is a query. The run's group is stored inside the config JSON under the `_Group` key:

```bash
trackio query project --project "my_project" --sql "
SELECT m.run_name,
       json_extract(m.metrics, '$.loss') AS final_loss
FROM metrics m
JOIN configs c ON c.run_name = m.run_name
WHERE json_extract(c.config, '$._Group') = 'grid-search'
  AND m.id = (SELECT MAX(id) FROM metrics WHERE run_name = m.run_name)
ORDER BY final_loss ASC
LIMIT 5"
```

Add `--json` for machine-readable output. See [Storage Schema and Direct Queries](./storage_schema) for the full schema.

## Running Sweeps with a Coding Agent

Sweeps are a natural task to delegate: the loop is mechanical, and Trackio gives agents programmatic access to results (CLI with `--json`, the Python API, and direct SQL). A prompt as simple as:

> Run a random search over lr (log-uniform, 1e-5 to 1e-1) and batch_size (16–256) for my training script. Create one Trackio run per trial in the group "sweep-aug30", 20 trials, then query the results and report the best three configurations.

is enough for an agent to write the loop, run it, and read back the results. See [Running ML Experiments with Agents](./ml_agents) for how to structure the full feedback loop, including alerts and monitoring.

## Runnable Example

A complete, self-contained script with the grid and random recipes lives at [`examples/sweep-recipes.py`](https://github.com/gradio-app/trackio/blob/main/examples/sweep-recipes.py).
