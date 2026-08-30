"""Hyperparameter sweep recipes using plain Python loops.

Trackio intentionally has no first-class sweep API: a sweep is just a loop
that creates one run per configuration. This example shows a grid search and
a random search, grouped so they are easy to compare in the dashboard.

Run with: python examples/sweep-recipes.py
"""

import itertools
import math
import random

import trackio

PROJECT_ID = random.randint(100000, 999999)
PROJECT = f"fake-sweep-{PROJECT_ID}"
EPOCHS = 10


def train(config: dict, group: str, name: str) -> float:
    """Fake training loop: logs a loss curve shaped by the config."""
    trackio.init(project=PROJECT, name=name, group=group, config=config)

    # Pretend lower lr + larger batch converge better, with noise.
    quality = 1.0 / (1 + abs(math.log10(config["lr"]) + 3)) + config["batch_size"] / 512
    final_loss = None
    for epoch in range(EPOCHS):
        progress = (epoch + 1) / EPOCHS
        loss = 2.5 * math.exp(-3 * progress * quality) + random.gauss(0, 0.05)
        final_loss = max(0.05, loss)
        trackio.log({"loss": final_loss, "epoch": epoch})

    trackio.finish()
    return final_loss


# --- Recipe 1: grid search -------------------------------------------------
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

print(f"[grid] best config: {best[0]} (loss {best[1]:.3f})")

# --- Recipe 2: random search -----------------------------------------------
N_TRIALS = 6
rng = random.Random(42)  # seed so the sweep is reproducible

best = None
for trial in range(N_TRIALS):
    config = {
        "lr": 10 ** rng.uniform(-5, -1),
        "batch_size": rng.choice([16, 32, 64, 128, 256]),
    }
    loss = train(config, group="random-search", name=f"random-{trial}")
    if best is None or loss < best[1]:
        best = (config, loss)

print(f"[random] best config: {best[0]} (loss {best[1]:.3f})")
print(f"\nView results: trackio show --project {PROJECT}")
