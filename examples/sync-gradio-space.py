"""
Example: Log training data locally, then sync the project to a Gradio Space.

Usage:
    python examples/sync-gradio-space.py

This will:
1. Log a few runs of fake training metrics locally (no space_id in init)
2. Call trackio.sync() to upload the local project to a live Gradio Space

Set HF_TOKEN or run `huggingface-cli login` first.
"""

import math
import random

import trackio

PROJECT = f"sync-gradio-demo-{random.randint(100000, 999999)}"
EPOCHS = 15

for run_idx in range(3):
    trackio.init(
        project=PROJECT,
        name=f"run-{run_idx}",
        config={"lr": 0.001 * (run_idx + 1), "epochs": EPOCHS},
    )
    for epoch in range(EPOCHS):
        progress = epoch / EPOCHS
        loss = max(0.05, 2.5 * math.exp(-3 * progress) + random.gauss(0, 0.1))
        acc = min(
            0.95, 0.9 / (1 + math.exp(-6 * (progress - 0.5))) + random.gauss(0, 0.03)
        )
        trackio.log({"train/loss": round(loss, 4), "train/accuracy": round(acc, 4)})
    trackio.finish()

print("Training complete. Syncing to a Gradio Space...")
space_id = trackio.sync(project=PROJECT)
print(f"Dashboard: https://huggingface.co/spaces/{space_id}")
