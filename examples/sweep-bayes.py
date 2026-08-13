import math
import random
import time

import trackio

sweep_config = {
    "method": "bayes",
    "metric": {"name": "loss", "goal": "minimize", "target": 0.05},
    "run_cap": 15,
    "parameters": {
        "lr": {"distribution": "log_uniform_values", "min": 1e-4, "max": 1e-1},
        "optimizer": {"values": ["adam", "sgd"]},
    },
}

sweep_id = trackio.sweep(sweep_config, project="sweep-bayes-demo")


def train():
    run = trackio.init(project="sweep-bayes-demo")
    lr = run.config["lr"]
    optimizer_bonus = 0.8 if run.config["optimizer"] == "adam" else 1.0

    loss = 5.0
    for step in range(20):
        loss = loss * math.exp(-40 * lr * optimizer_bonus) + random.uniform(0, 0.02)
        trackio.log({"loss": loss})
        time.sleep(0.02)

    trackio.finish()


trackio.agent(sweep_id, function=train)

print("\nSweep finished! View results with: trackio show --project sweep-bayes-demo")
