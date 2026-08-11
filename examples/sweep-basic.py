import math
import random
import time

import trackio

sweep_config = {
    "method": "grid",
    "metric": {"name": "loss", "goal": "minimize"},
    "parameters": {
        "lr": {"values": [0.1, 0.01, 0.001]},
        "batch_size": {"values": [16, 32]},
    },
}

sweep_id = trackio.sweep(sweep_config, project="sweep-demo")


def train():
    run = trackio.init(project="sweep-demo")
    lr = run.config["lr"]
    batch_size = run.config["batch_size"]

    loss = 5.0
    for step in range(20):
        loss = loss * math.exp(-lr) + random.uniform(0, 0.05) * (batch_size / 16)
        trackio.log({"loss": loss, "lr": lr})
        time.sleep(0.05)

    trackio.finish()


trackio.agent(sweep_id, function=train)

print("\nSweep finished! View results with: trackio show --project sweep-demo")
