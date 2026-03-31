"""
Example: deploy a Gradio Space during training, then convert it to a static Space once done.

This demonstrates the Gradio -> Static conversion flow:
1. Start training with a live Gradio dashboard (real-time updates)
2. After training finishes, convert the Space to static (no server needed, cheaper)

Usage:
    python examples/convert-gradio-to-static.py
"""

import math
import random
import time

import trackio

PROJECT = f"gradio-to-static-{random.randint(100000, 999999)}"
SPACE_ID = f"convert-demo-{random.randint(100000, 999999)}"
EPOCHS = 10

for run in range(2):
    trackio.init(
        project=PROJECT,
        name=f"run-{run}",
        config={"epochs": EPOCHS, "lr": 0.001 * (run + 1), "batch_size": 32},
        space_id=SPACE_ID,
        auto_log_gpu=False,
    )

    for epoch in range(EPOCHS):
        progress = epoch / EPOCHS
        loss = 2.0 * math.exp(-3 * progress) + 0.1 + random.gauss(0, 0.05)
        acc = 0.95 / (1 + math.exp(-6 * (progress - 0.5))) + random.gauss(0, 0.02)

        trackio.log(
            {
                "train/loss": round(max(0.01, loss), 4),
                "train/accuracy": round(min(0.99, max(0, acc)), 4),
            },
            step=epoch,
        )

        trackio.log_system(
            {
                "cpu_percent": round(40 + epoch * 3 + random.uniform(-2, 2), 1),
                "memory_gb": round(4.0 + epoch * 0.1 + random.uniform(-0.05, 0.05), 2),
            }
        )

        time.sleep(0.3)

    trackio.finish()

print("\nTraining complete. Converting Gradio Space to static...")
space_id = trackio.sync(project=PROJECT, space_id=SPACE_ID, sdk="static")
print(f"Static dashboard: https://huggingface.co/spaces/{space_id}")
