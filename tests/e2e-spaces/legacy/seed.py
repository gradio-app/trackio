"""Seed a permanent Trackio Space running an older Trackio release.

Run with the release being seeded, for example:

    uv run --no-project --with trackio==0.21.0 --with "huggingface_hub<1.32" \
        --with numpy python tests/e2e-spaces/legacy/seed.py 0.21.0
"""

import sys
import time
from pathlib import Path

import huggingface_hub
import numpy as np

import trackio

sys.path.insert(0, str(Path(__file__).parent))
from legacy_spaces import (  # noqa: E402
    ALERT_TITLE,
    IMAGE_STEP,
    LEGACY_SPACES,
    NUM_STEPS,
    PROJECTS,
    metrics_at,
)


def _deploy(target: dict) -> None:
    space_id = target["space_id"]
    trackio.deploy.create_space_if_not_exists(space_id, bucket_id=target["bucket_id"])
    hf_api = huggingface_hub.HfApi()
    requirements = Path(
        hf_api.hf_hub_download(space_id, "requirements.txt", repo_type="space")
    ).read_text()
    lines = requirements.splitlines() + target.get("extra_requirements", [])
    hf_api.upload_file(
        path_or_fileobj="\n".join(lines).encode(),
        path_in_repo="requirements.txt",
        repo_id=space_id,
        repo_type="space",
    )
    hf_api.request_space_hardware(space_id, "cpu-upgrade", sleep_time=-1)
    while str(hf_api.get_space_runtime(space_id).stage) != "RUNNING":
        time.sleep(10)


def main(version: str) -> None:
    if trackio.__version__ != version:
        raise SystemExit(f"Expected trackio {version}, found {trackio.__version__}")
    target = LEGACY_SPACES[version]
    _deploy(target)
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
