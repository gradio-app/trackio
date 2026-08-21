"""Demo: hyperparameter sweeps with trackio.

Runs three sweeps in the "sweeps-demo" project, one per search method:
1. A grid sweep over optimizer x learning rate (all 8 combinations).
2. A random sweep over a continuous space, capped at 6 trials.
3. A Bayesian sweep that stops early once the target loss is reached.

View the results with: trackio show --project sweeps-demo
"""

import math
import random

import trackio

PROJECT = "sweeps-demo"


def simulated_train():
    """One trial: simulates a loss curve whose convergence depends on the
    hyperparameters, so the sweep has a real optimum to find."""
    run = trackio.init(project=PROJECT)
    lr = run.config["lr"]
    optimizer = run.config.get("optimizer", "adam")
    dropout = run.config.get("dropout", 0.1)

    momentum_boost = 1.3 if optimizer == "adam" else 1.0
    ideal_lr = 0.01
    lr_penalty = abs(math.log10(lr) - math.log10(ideal_lr))

    loss = 4.0
    accuracy = 0.1
    for step in range(30):
        convergence = momentum_boost * lr * 40 / (1 + lr_penalty * 2)
        floor = 0.1 + 0.5 * lr_penalty + dropout
        loss = max(floor, loss * math.exp(-convergence * 0.1))
        loss += random.uniform(0, 0.03)
        accuracy = min(0.99, 1.0 - loss / 4.5 + random.uniform(0, 0.01))
        trackio.log({"loss": loss, "accuracy": accuracy})

    trackio.finish()


grid_sweep_id = trackio.sweep(
    {
        "name": "grid-optimizer-vs-lr",
        "method": "grid",
        "metric": {"name": "loss", "goal": "minimize"},
        "parameters": {
            "optimizer": {"values": ["adam", "sgd"]},
            "lr": {"values": [0.1, 0.01, 0.001, 0.0001]},
        },
    },
    project=PROJECT,
)
trackio.agent(grid_sweep_id, function=simulated_train)

random_sweep_id = trackio.sweep(
    {
        "name": "random-lr-dropout",
        "method": "random",
        "metric": {"name": "accuracy", "goal": "maximize"},
        "run_cap": 6,
        "parameters": {
            "lr": {"distribution": "log_uniform_values", "min": 1e-4, "max": 1e-1},
            "dropout": {"min": 0.0, "max": 0.5},
            "optimizer": {"value": "adam"},
        },
    },
    project=PROJECT,
)
trackio.agent(random_sweep_id, function=simulated_train)

bayes_sweep_id = trackio.sweep(
    {
        "name": "bayes-lr-search",
        "method": "bayes",
        "metric": {"name": "loss", "goal": "minimize", "target": 0.2},
        "run_cap": 10,
        "parameters": {
            "lr": {"distribution": "log_uniform_values", "min": 1e-4, "max": 1e-1},
            "optimizer": {"values": ["adam", "sgd"]},
        },
    },
    project=PROJECT,
)
trackio.agent(bayes_sweep_id, function=simulated_train)

print("\nDone! Inspect the sweeps with:")
for sweep_id in (grid_sweep_id, random_sweep_id, bayes_sweep_id):
    print(f"  trackio sweep status {PROJECT}/{sweep_id} --trials")
print(f'  trackio show --project "{PROJECT}"')
