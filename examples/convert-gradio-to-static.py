"""
Example: Log locally, sync to a Gradio Space, then freeze a static snapshot.

This demonstrates the full Gradio -> freeze flow:
1. Log training metrics locally
2. Sync the project to a live Gradio Space
3. Freeze the Gradio Space into a read-only static Space (no server needed)

Usage:
    python examples/convert-gradio-to-static.py
"""

import math
import random

import trackio

PROJECT = f"gradio-to-static-{random.randint(100000, 999999)}"
EPOCHS = 10

for run in range(2):
    trackio.init(
        project=PROJECT,
        space_id=PROJECT,
        name=f"run-{run}",
        config={"epochs": EPOCHS, "lr": 0.001 * (run + 1), "batch_size": 32},
    )
    for epoch in range(EPOCHS):
        progress = epoch / EPOCHS
        loss = max(0.01, 2.0 * math.exp(-3 * progress) + 0.1 + random.gauss(0, 0.05))
        acc = min(
            0.99,
            max(
                0, 0.95 / (1 + math.exp(-6 * (progress - 0.5))) + random.gauss(0, 0.02)
            ),
        )
        trackio.log(
            {"train/loss": round(loss, 4), "train/accuracy": round(acc, 4)},
            step=epoch,
        )
    trackio.finish()


print("Freezing a static snapshot from the Gradio Space...")
static_space_id = trackio.freeze(space_id=PROJECT, project=PROJECT, new_space_id=f"{PROJECT}_static")
print(f"Static snapshot: https://huggingface.co/spaces/{static_space_id}")
