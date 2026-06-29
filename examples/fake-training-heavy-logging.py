"""
Example: Many runs with heavy per-step logging (Metrics-page payload stress test).

This mirrors a realistic LLM/RL training workload that logs, on every step:
  - several scalar metrics (loss, grad_norm, lr, val metrics, epoch), AND
  - a non-scalar "generation sample" string, plus a periodic eval Table.

It's useful for exercising the Metrics dashboard with a lot of data, and for
seeing the effect of the scalar-only Metrics fetch (the Metrics page only
requests scalar values, so the text samples / tables below are NOT shipped on
every refresh, while the Tables/Media pages still load them on demand).

Scale is configurable via environment variables so you can go from a quick demo
to a heavy stress test:

    NUM_RUNS=40 STEPS=800 python examples/fake-training-heavy-logging.py

Then launch the dashboard:

    trackio show --project <printed project name>

Tip: open the browser dev-tools Network tab on the Metrics page and watch the
size of the `get_logs_batch` responses to see how much data each refresh pulls.
"""

import math
import os
import random

import trackio as wandb

NUM_RUNS = int(os.environ.get("NUM_RUNS", "20"))
STEPS = int(os.environ.get("STEPS", "500"))
TEXT_EVERY = int(os.environ.get("TEXT_EVERY", "1"))
TABLE_EVERY = int(os.environ.get("TABLE_EVERY", "25"))
PROJECT = os.environ.get(
    "PROJECT", f"fake-training-heavy-{random.randint(100000, 999999)}"
)

SAMPLE_TEXT = "The quick brown fox jumps over the lazy dog. " * 18


def eval_table(step: int) -> wandb.Table:
    columns = ["prompt", "completion", "score"]
    data = [
        [
            f"Q{step}-{i}: " + ("explain this concept in detail " * 6),
            "The model responds with a fairly long answer. " * 8,
            round(0.5 + 0.4 * math.sin(step / 30 + i), 4),
        ]
        for i in range(4)
    ]
    return wandb.Table(columns=columns, data=data)


def main():
    print(
        f"Logging {NUM_RUNS} runs x {STEPS} steps to project '{PROJECT}' "
        f"(text every {TEXT_EVERY}, table every {TABLE_EVERY})"
    )
    for r in range(NUM_RUNS):
        wandb.init(
            project=PROJECT,
            name=f"run-{r:03d}",
            config=dict(epochs=STEPS // 50, learning_rate=3e-4, batch_size=32),
        )
        for s in range(STEPS):
            metrics = {
                "train/loss": round(
                    2.5 * math.exp(-s / 200) + 0.05 * math.sin(s / 7) + 0.01 * r, 5
                ),
                "train/grad_norm": round(1.0 + 0.5 * math.sin(s / 13), 5),
                "train/lr": round(3e-4 * (1 - s / STEPS), 8),
                "val/loss": round(2.6 * math.exp(-s / 180) + 0.06, 5),
                "val/accuracy": round(
                    min(0.99, 0.3 + 0.7 * (1 - math.exp(-s / 150))), 5
                ),
                "epoch": s // 50,
            }
            if TEXT_EVERY and s % TEXT_EVERY == 0:
                metrics["samples/generation"] = f"[step {s}] " + SAMPLE_TEXT
            if TABLE_EVERY and s % TABLE_EVERY == 0:
                metrics["eval/predictions"] = eval_table(s)
            wandb.log(metrics)
        wandb.finish()
        print(f"  finished run-{r:03d} ({r + 1}/{NUM_RUNS})")

    print(f"\nDone. View with:\n    trackio show --project {PROJECT}")


if __name__ == "__main__":
    main()
