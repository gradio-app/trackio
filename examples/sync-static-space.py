"""
Example: Log some fake training data, then sync to a static HF Space.

Usage:
    python examples/sync-static-space.py

This will:
1. Log a few runs of fake training metrics locally
2. Call trackio.sync() which uploads the local project to an HF Bucket
   and deploys a static dashboard Space (no running server needed)

Set HF_TOKEN or run `huggingface-cli login` first.
"""

import math
import random

import trackio

PROJECT = f"sync-demo-{random.randint(100000, 999999)}"
EPOCHS = 15


def fake_loss(epoch, max_epochs):
    progress = epoch / max_epochs
    return max(0.05, 2.5 * math.exp(-3 * progress) + random.gauss(0, 0.2))


def fake_accuracy(epoch, max_epochs):
    progress = epoch / max_epochs
    return min(
        0.95, 0.9 / (1 + math.exp(-6 * (progress - 0.5))) + random.gauss(0, 0.05)
    )


for run_idx in range(3):
    trackio.init(
        project=PROJECT,
        name=f"run-{run_idx}",
        config={"lr": 0.001 * (run_idx + 1), "epochs": EPOCHS},
    )
    for epoch in range(EPOCHS):
        trackio.log(
            {
                "train/loss": round(fake_loss(epoch, EPOCHS), 4),
                "train/accuracy": round(fake_accuracy(epoch, EPOCHS), 4),
                "val/loss": round(fake_loss(epoch, EPOCHS) * 1.1, 4),
            }
        )
    trackio.finish()

space_id = trackio.sync(project=PROJECT, sdk="static")
print(f"Dashboard: https://huggingface.co/spaces/{space_id}")
