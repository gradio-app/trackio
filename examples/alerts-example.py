import os
import random
import time

import trackio

PROJECT_ID = random.randint(100000, 999999)
PROJECT = f"alerts-example-{PROJECT_ID}"
WEBHOOK_URL = os.getenv("TRACKIO_WEBHOOK_URL")

trackio.init(
    project=PROJECT,
    config={
        "epochs": 20,
        "learning_rate": 0.001,
        "batch_size": 32,
    },
    webhook_min_level=trackio.AlertLevel.WARN,
)

trackio.alert(
    title="Run started",
    text=f"Project: {PROJECT}",
    level=trackio.AlertLevel.INFO,
)

warned = False
errored = False

for step in range(20):
    loss = max(0.05, 1.4 - (step * 0.06) + random.uniform(-0.12, 0.12))
    accuracy = min(0.98, 0.35 + (step * 0.03) + random.uniform(-0.03, 0.03))

    if step == 8:
        loss = 1.2
    if step == 14:
        loss = 2.1

    trackio.log(
        {
            "train/loss": round(loss, 4),
            "train/accuracy": round(max(0.0, accuracy), 4),
        },
        step=step,
    )

    if not warned and loss > 1.0:
        trackio.alert(
            title="Loss is high",
            text=f"Loss reached {loss:.4f} at step {step}",
            level=trackio.AlertLevel.WARN,
        )
        warned = True

    if not errored and loss > 2.0:
        trackio.alert(
            title="Loss spike detected",
            text=f"Loss reached {loss:.4f} at step {step}",
            level=trackio.AlertLevel.ERROR,
            webhook_url=WEBHOOK_URL,
        )
        errored = True

    time.sleep(0.2)

trackio.alert(
    title="Run finished",
    text="Training loop completed",
    level=trackio.AlertLevel.INFO,
)

trackio.finish()
