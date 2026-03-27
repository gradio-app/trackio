"""
Example: log metrics + system metrics + media + table + report + files, then sync to a static HF Space.

Usage:
    python examples/sync-static-space-everything.py
"""

import math
import random
from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image as PILImage
from PIL import ImageDraw

import trackio

PROJECT = f"sync-full-demo-{random.randint(100000, 999999)}"
STEPS = 8


def make_image(step: int, size: int = 128) -> PILImage.Image:
    img = PILImage.new("RGB", (size, size), "black")
    draw = ImageDraw.Draw(img)
    x = int((size / 2) + (size / 3) * math.sin(step * 0.8))
    y = int((size / 2) + (size / 3) * math.cos(step * 0.6))
    draw.ellipse((x - 10, y - 10, x + 10, y + 10), fill=(255, 120, 80))
    draw.rectangle((8, 8, size - 8, size - 8), outline=(80, 160, 255), width=2)
    return img


def make_audio(step: int, sr: int = 16000, duration_s: float = 0.3) -> np.ndarray:
    t = np.linspace(0, duration_s, int(sr * duration_s), endpoint=False)
    freq = 220 + step * 20
    wave = 0.4 * np.sin(2 * np.pi * freq * t)
    return (wave * 32767).astype(np.int16)


def main():
    examples_dir = Path(__file__).parent
    files_dir = examples_dir / "files"

    trackio.init(
        project=PROJECT,
        name="run-all-artifacts",
        config={"steps": STEPS, "mode": "static-sync-full"},
        auto_log_gpu=False,
    )

    trackio.save(files_dir / "config1.yml")
    trackio.save(files_dir / "config2.yml")

    for step in range(STEPS):
        train_loss = round(
            max(0.05, 1.8 * math.exp(-0.35 * step) + random.gauss(0, 0.03)), 4
        )
        train_acc = round(min(0.99, 0.45 + 0.07 * step + random.gauss(0, 0.015)), 4)
        img = make_image(step)
        audio = make_audio(step)

        table_df = pd.DataFrame(
            {
                "sample_id": [f"s-{step}-a", f"s-{step}-b"],
                "prediction": ["cat", "dog"],
                "confidence": [
                    round(0.65 + 0.03 * step, 3),
                    round(0.58 + 0.025 * step, 3),
                ],
            }
        )

        trackio.log(
            {
                "train/loss": train_loss,
                "train/accuracy": train_acc,
                "media/preview_image": trackio.Image(img, caption=f"step {step}"),
                "media/preview_audio": trackio.Audio(
                    audio, sample_rate=16000, format="wav"
                ),
                "tables/predictions": trackio.Table(dataframe=table_df),
            },
            step=step,
        )

        trackio.log_system(
            {
                "cpu_percent": round(25 + step * 2 + random.uniform(-1.0, 1.0), 2),
                "memory_gb": round(3.2 + step * 0.05 + random.uniform(-0.03, 0.03), 3),
            }
        )

    report_md = f"""# Full Static Sync Report

Project: `{PROJECT}`

This run logs:

- scalar metrics
- system metrics
- media (image + audio)
- a table artifact
- saved files
"""
    trackio.log({"reports/summary": trackio.Markdown(report_md)})
    trackio.finish()

    space_id = trackio.sync(project=PROJECT)
    print(f"Dashboard: https://huggingface.co/spaces/{space_id}")


if __name__ == "__main__":
    main()
