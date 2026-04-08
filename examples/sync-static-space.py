"""
Example: Log training data locally, sync to a static Space, then log more and sync again.

Usage:
    python examples/sync-static-space.py

This will:
1. Log an initial run of fake training metrics locally
2. Sync to a static HF Space (uploads to an HF Bucket, no server needed)
3. Log a second run with more data
4. Sync again -- the static Space now contains both runs

Set HF_TOKEN or run `huggingface-cli login` first.
"""

import math
import random

import trackio

PROJECT = f"sync-demo-{random.randint(100000, 999999)}"
EPOCHS = 15


def fake_metrics(epoch, max_epochs):
    progress = epoch / max_epochs
    loss = max(0.05, 2.5 * math.exp(-3 * progress) + random.gauss(0, 0.1))
    acc = min(0.95, 0.9 / (1 + math.exp(-6 * (progress - 0.5))) + random.gauss(0, 0.03))
    return round(loss, 4), round(acc, 4)


trackio.init(project=PROJECT, name="run-0", config={"lr": 0.001, "epochs": EPOCHS})
for epoch in range(EPOCHS):
    loss, acc = fake_metrics(epoch, EPOCHS)
    trackio.log({"train/loss": loss, "train/accuracy": acc})
trackio.finish()

print("First run complete. Syncing to a static Space...")
space_id = trackio.sync(project=PROJECT, sdk="static")
print(f"Dashboard: https://huggingface.co/spaces/{space_id}")

trackio.init(project=PROJECT, name="run-1", config={"lr": 0.003, "epochs": EPOCHS})
for epoch in range(EPOCHS):
    loss, acc = fake_metrics(epoch, EPOCHS)
    trackio.log({"train/loss": loss, "train/accuracy": acc})
trackio.finish()

print("Second run complete. Syncing again...")
trackio.sync(project=PROJECT, sdk="static")
print("Static Space updated with both runs.")
