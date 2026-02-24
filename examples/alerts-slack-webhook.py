import random
import time

import trackio

PROJECT_ID = random.randint(100000, 999999)
PROJECT = f"alerts-slack-webhook-{PROJECT_ID}"

SLACK_WEBHOOK_URL = "PASTE_YOUR_SLACK_WEBHOOK_URL_HERE"

if SLACK_WEBHOOK_URL == "PASTE_YOUR_SLACK_WEBHOOK_URL_HERE":
    raise ValueError("Please set SLACK_WEBHOOK_URL before running this example.")

trackio.init(
    project=PROJECT,
    webhook_url=SLACK_WEBHOOK_URL,
    webhook_min_level=trackio.AlertLevel.ERROR,
    config={
        "epochs": 12,
        "learning_rate": 0.001,
        "batch_size": 32,
    },
)

trackio.alert(
    title="Run started",
    text=f"Project: {PROJECT}",
    level=trackio.AlertLevel.INFO,
)

for step in range(12):
    loss = max(0.05, 1.2 - (step * 0.08) + random.uniform(-0.1, 0.1))
    accuracy = min(0.98, 0.4 + (step * 0.035) + random.uniform(-0.03, 0.03))

    if step == 5:
        loss = 1.3
    if step == 9:
        loss = 2.3

    trackio.log(
        {
            "train/loss": round(loss, 4),
            "train/accuracy": round(max(0.0, accuracy), 4),
        },
        step=step,
    )

    if loss > 1.0:
        trackio.alert(
            title="Loss is elevated",
            text=f"Loss reached {loss:.4f} at step {step}",
            level=trackio.AlertLevel.WARN,
        )

    if loss > 2.0:
        trackio.alert(
            title="Loss spike detected",
            text=f"Loss reached {loss:.4f} at step {step}",
            level=trackio.AlertLevel.ERROR,
        )

    time.sleep(0.2)

trackio.alert(
    title="Run finished",
    text="Training loop completed",
    level=trackio.AlertLevel.INFO,
)

trackio.finish()
