"""
Example: log metrics + system metrics + media + table + report + files locally.

Usage:
    python examples/kitchen-sink-local-only.py
"""

import math
import random
import time
from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image as PILImage
from PIL import ImageDraw

import trackio

PROJECT = f"local-full-demo-{random.randint(100000, 999999)}"
STEPS = 8
N_RUNS = 3


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


def main() -> None:
    examples_dir = Path(__file__).parent
    files_dir = examples_dir / "files"

    run_names = [f"run-{run_idx}" for run_idx in range(N_RUNS)]

    for run_idx in range(N_RUNS):
        trackio.init(
            project=PROJECT,
            name=f"run-{run_idx}",
            config={"steps": STEPS, "run_idx": run_idx, "mode": "local-only"},
            auto_log_gpu=False,
        )

        trackio.alert(
            title="Run started",
            text=f"Project: {PROJECT} | Run: run-{run_idx}",
            level=trackio.AlertLevel.INFO,
        )

        if run_idx == 0:
            trackio.save(files_dir / "config1.yml", project=PROJECT)
            trackio.save(files_dir / "config2.yml", project=PROJECT)

        for step in range(STEPS):
            train_loss = round(
                max(0.05, 1.8 * math.exp(-0.35 * step) + random.gauss(0, 0.03)),
                4,
            )
            train_acc = round(min(0.99, 0.45 + 0.07 * step + random.gauss(0, 0.015)), 4)

            img = make_image(step + run_idx)
            audio = make_audio(step + run_idx)

            table_df = pd.DataFrame(
                {
                    "sample_id": [f"s-{step}-a", f"s-{step}-b"],
                    "prediction": ["cat", "dog"],
                    "confidence": [
                        round(0.65 + 0.03 * step + 0.01 * run_idx, 3),
                        round(0.58 + 0.025 * step + 0.01 * run_idx, 3),
                    ],
                }
            )

            trackio.log(
                {
                    "train/loss": train_loss,
                    "train/accuracy": train_acc,
                    "media/preview_image": trackio.Image(
                        img, caption="this is a caption"
                    ),
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
                    "memory_gb": round(
                        3.2 + step * 0.05 + random.uniform(-0.03, 0.03), 3
                    ),
                }
            )

            if step == STEPS - 2:
                trackio.alert(
                    title="Loss is drifting",
                    text=f"Run run-{run_idx} step={step} loss={train_loss}",
                    level=trackio.AlertLevel.WARN,
                )

        report_md = f"""# Local Full Sync Report

Project: `{PROJECT}`
Run: `run-{run_idx}`

This run logs:
- scalar metrics
- system metrics
- media (image + audio)
- a table artifact
"""
        trackio.log({"reports/summary": trackio.Markdown(report_md)})

        if run_idx == N_RUNS - 1:
            final_report_md = f"""# Final Local Kitchen Sink Report

Project: `{PROJECT}`
Runs: {", ".join(f"`{name}`" for name in run_names)}

What to look for:
- Alerts on this page and in the alert panel (run started + one drift warning).
- Reports entries in the Reports tab (summary per run + this final report).
"""
            trackio.log(
                {"reports/final_report": trackio.Markdown(final_report_md)},
                step=STEPS - 1,
            )

        trackio.alert(
            title="Run finished",
            text=f"Completed run-{run_idx} ({STEPS} steps).",
            level=trackio.AlertLevel.INFO,
        )
        trackio.finish()

    result = trackio.show(
        project=PROJECT,
        open_browser=False,
        block_thread=False,
    )
    full_url = result[3]
    print(f"Dashboard: {full_url}")
    time.sleep(3600)


if __name__ == "__main__":
    main()
