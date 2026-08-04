"""Live version of the mixed-cadence reproduction from Trackio issue #653.

Run from the repository root:

    .venv/bin/python examples/live-metric-sampling.py

The dashboard opens before logging begins. Each training step writes nine
``dense/metric_*`` rows, while ``sparse/value`` is written every 10 steps. This
is the same 7,280-row layout as the issue reproduction. ``train/loss`` is added
to the same sparse row with a deliberately jagged value so dropped points are
easy to see in a connected line chart.

On the Metrics page, watch ``train/loss`` as the row count crosses 3,000. The
terminal also prints the displayed sparse-point count and how many selected
points changed since the previous one-second dashboard poll. A broken build
drops points and reports large changes; a fixed build keeps the complete
10-step cadence and never drops an existing point.

The defaults log for about 40 seconds and leave the dashboard running until
Ctrl+C. Override them when needed, for example:

    STEPS=400 STEP_DELAY=0.02 .venv/bin/python examples/live-metric-sampling.py
"""

import math
import os
import random
import time

import trackio
from trackio.sqlite_storage import SQLiteStorage

STEPS = int(os.environ.get("STEPS", "800"))
STEP_DELAY = float(os.environ.get("STEP_DELAY", "0.05"))
DENSE_METRICS = 9
POLL_INTERVAL = float(os.environ.get("POLL_INTERVAL", "1.0"))
PROJECT = os.environ.get("PROJECT", f"repro-653-live-{random.randint(100000, 999999)}")
RUN_NAME = "run-1"
OPEN_BROWSER = os.environ.get("OPEN_BROWSER", "1") != "0"
KEEP_OPEN = os.environ.get("KEEP_OPEN", "1") != "0"


def log_step(step: int) -> None:
    for metric_index in range(DENSE_METRICS):
        trackio.log({f"dense/metric_{metric_index}": 0.0}, step=step)

    if step % 10 == 0:
        loss = 2.0 + (0.75 if (step // 10) % 2 else -0.75) + 0.15 * math.sin(step / 20)
        trackio.log(
            {"sparse/value": float(step), "train/loss": round(loss, 5)}, step=step
        )


def rows_through_step(step: int) -> int:
    return (step + 1) * DENSE_METRICS + step // 10 + 1


def read_sparse_steps(max_points: int | None) -> set[int]:
    logs = SQLiteStorage.get_logs(
        PROJECT,
        RUN_NAME,
        max_points=max_points,
        scalar_only=True,
    )
    return {row["step"] for row in logs if "sparse/value" in row}


def print_poll(previous_steps: set[int]) -> set[int]:
    stored_steps = read_sparse_steps(None)
    displayed_steps = read_sparse_steps(3000)
    changed_steps = displayed_steps ^ previous_steps
    dropped_steps = previous_steps - displayed_steps
    missing_steps = stored_steps - displayed_steps
    row_count = SQLiteStorage.get_log_count(PROJECT, RUN_NAME)

    print(
        f"poll rows={row_count:5d}  "
        f"sparse={len(displayed_steps):2d}/{len(stored_steps):2d}  "
        f"missing={len(missing_steps):2d}  "
        f"changed={len(changed_steps):2d}  "
        f"dropped={len(dropped_steps):2d}"
    )
    return displayed_steps


def print_integrity_check() -> None:
    stored_logs = SQLiteStorage.get_logs(PROJECT, RUN_NAME)
    display_logs = SQLiteStorage.get_logs(
        PROJECT, RUN_NAME, max_points=3000, scalar_only=True
    )
    stored_sparse_steps = [row["step"] for row in stored_logs if "sparse/value" in row]
    displayed_sparse_steps = [
        row["step"] for row in display_logs if "sparse/value" in row
    ]
    expected_sparse_steps = list(range(0, STEPS, 10))

    print("\nIntegrity check")
    print(f"  stored rows:              {len(stored_logs)}")
    print(f"  display rows:             {len(display_logs)}")
    print(f"  stored sparse/value:      {len(stored_sparse_steps)}")
    print(f"  shown sparse/value:       {len(displayed_sparse_steps)}")
    print(
        f"  expected cadence intact:  {displayed_sparse_steps == expected_sparse_steps}"
    )


def main() -> None:
    dashboard = None
    run_active = False
    try:
        trackio.init(
            project=PROJECT,
            name=RUN_NAME,
            config={
                "steps": STEPS,
                "dense_metrics_per_step": DENSE_METRICS,
                "sparse_logging_steps": 10,
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
        print("\nOpen the Metrics page and watch train/loss for visible movement.")
        print("sparse/value mirrors the exact linear metric from issue #653.")
        print("The sampling threshold is crossed after roughly 330 training steps.\n")

        threshold_announced = False
        displayed_sparse_steps: set[int] = set()
        next_poll = time.monotonic() + POLL_INTERVAL
        for step in range(1, STEPS):
            log_step(step)
            row_count = rows_through_step(step)
            if not threshold_announced and row_count > 3000:
                print(f"Crossed 3,000 metric rows at step {step}.")
                threshold_announced = True
            if time.monotonic() >= next_poll:
                displayed_sparse_steps = print_poll(displayed_sparse_steps)
                next_poll = time.monotonic() + POLL_INTERVAL
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
