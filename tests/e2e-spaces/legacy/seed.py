"""Seed a permanent Trackio Space running an older Trackio release.

Run with the release being seeded, for example:

    uv run --no-project --with trackio==0.39.0 --with numpy \
        python tests/e2e-spaces/legacy/seed.py 0.39.0
"""

import sys
from pathlib import Path

import numpy as np

import trackio

sys.path.insert(0, str(Path(__file__).parent))
from data import (  # noqa: E402
    ALERT_TITLE,
    IMAGE_STEP,
    LEGACY_SPACES,
    NUM_STEPS,
    PROJECTS,
    metrics_at,
)


def main(version: str) -> None:
    if trackio.__version__ != version:
        raise SystemExit(f"Expected trackio {version}, found {trackio.__version__}")
    target = LEGACY_SPACES[version]
    for project, runs in PROJECTS.items():
        for run, config in runs.items():
            trackio.init(
                project=project,
                name=run,
                config=config,
                space_id=target["space_id"],
                bucket_id=target["bucket_id"],
            )
            for step in range(NUM_STEPS):
                metrics = metrics_at(run, step)
                if project == "bump-compat" and run == "run-a" and step == IMAGE_STEP:
                    pixels = np.full((8, 8, 3), 128, dtype=np.uint8)
                    metrics["samples"] = trackio.Image(pixels, caption="gray")
                trackio.log(metrics, step=step)
            if run == "run-b":
                trackio.alert(title=ALERT_TITLE, text="seeded alert")
            trackio.finish()


if __name__ == "__main__":
    main(sys.argv[1])
