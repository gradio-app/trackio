"""Live reproduction for mixed-cadence metric sampling.

Run from the repository root:

    .venv/bin/python examples/live-metric-sampling.py

The dashboard opens before logging begins. On the Metrics page, watch
``train/loss`` as the row count crosses 3,000. A broken Trackio build drops
roughly half of its points and reshuffles them on every refresh. A fixed build
keeps the complete 10-step cadence stable throughout the run.

The defaults log for about 40 seconds and leave the dashboard running until
Ctrl+C. Override them when needed, for example:

    STEPS=400 STEP_DELAY=0.02 python examples/live-metric-sampling.py
"""

import math
import os
import random
import time

import trackio
from trackio.sqlite_storage import SQLiteStorage

STEPS = int(os.environ.get("STEPS", "800"))
STEP_DELAY = float(os.environ.get("STEP_DELAY", "0.05"))
PROFILE_METRICS = 9
PROJECT = os.environ.get(
    "PROJECT", f"live-metric-sampling-{random.randint(100000, 999999)}"
)
RUN_NAME = "mixed-cadence-run"
OPEN_BROWSER = os.environ.get("OPEN_BROWSER", "1") != "0"
KEEP_OPEN = os.environ.get("KEEP_OPEN", "1") != "0"


def log_step(step: int) -> None:
    for metric_index in range(PROFILE_METRICS):
        duration = (
            0.002 + metric_index * 0.0002 + 0.0004 * math.sin(step / (8 + metric_index))
        )
        trackio.log({f"profiling/block_{metric_index}": round(duration, 6)}, step=step)

    if step % 10 == 0:
        loss = 2.5 * math.exp(-step / 300) + 0.04 * math.sin(step / 25)
        trackio.log({"train/loss": round(loss, 5)}, step=step)


def rows_through_step(step: int) -> int:
    return (step + 1) * PROFILE_METRICS + step // 10 + 1


def print_integrity_check() -> None:
    stored_logs = SQLiteStorage.get_logs(PROJECT, RUN_NAME)
    display_logs = SQLiteStorage.get_logs(
        PROJECT, RUN_NAME, max_points=3000, scalar_only=True
    )
    stored_loss_steps = [row["step"] for row in stored_logs if "train/loss" in row]
    displayed_loss_steps = [row["step"] for row in display_logs if "train/loss" in row]
    expected_loss_steps = list(range(0, STEPS, 10))

    print("\nIntegrity check")
    print(f"  stored rows:              {len(stored_logs)}")
    print(f"  display rows:             {len(display_logs)}")
    print(f"  stored train/loss points: {len(stored_loss_steps)}")
    print(f"  shown train/loss points:  {len(displayed_loss_steps)}")
    print(f"  expected cadence intact:  {displayed_loss_steps == expected_loss_steps}")


def main() -> None:
    dashboard = None
    run_active = False
    try:
        trackio.init(
            project=PROJECT,
            name=RUN_NAME,
            config={
                "steps": STEPS,
                "profile_metrics_per_step": PROFILE_METRICS,
                "loss_logging_steps": 10,
            },
            embed=False,
            auto_log_gpu=False,
            auto_log_cpu=False,
        )
        run_active = True
        log_step(0)

        dashboard, _, _, _ = trackio.show(
            project=PROJECT,
            open_browser=OPEN_BROWSER,
            block_thread=False,
        )
        print("\nOpen the Metrics page and watch train/loss.")
        print("The sampling threshold is crossed after roughly 330 training steps.\n")

        threshold_announced = False
        for step in range(1, STEPS):
            log_step(step)
            row_count = rows_through_step(step)
            if not threshold_announced and row_count > 3000:
                print(f"Crossed 3,000 metric rows at step {step}.")
                threshold_announced = True
            if step % 50 == 0 or step == STEPS - 1:
                print(f"step={step:4d}  metric_rows={row_count:5d}")
            time.sleep(STEP_DELAY)

        trackio.finish()
        run_active = False
        print_integrity_check()

        if KEEP_OPEN:
            print("\nDashboard is still running. Press Ctrl+C to stop it.")
            while True:
                time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping the live example.")
    finally:
        if run_active:
            trackio.finish()
        if dashboard is not None:
            dashboard.close()


if __name__ == "__main__":
    main()
