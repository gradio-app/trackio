"""
Example: test automatic CPU, RAM, disk, network, and sensor metrics logging.

Usage:
    python examples/test_cpu_metrics.py
"""

import math
import time

import trackio

PROJECT = "cpu-metrics-test"
STEPS = 20


def main():
    run = trackio.init(
        project=PROJECT,
        name="cpu-test-run",
        auto_log_cpu=True,
        cpu_log_interval=2.0,
    )

    for i in range(STEPS):
        loss = math.exp(-0.3 * i) + 0.05
        run.log({"train/loss": round(loss, 4)}, step=i)
        time.sleep(2)

    run.finish()

    trackio.show(project=PROJECT)


if __name__ == "__main__":
    main()
