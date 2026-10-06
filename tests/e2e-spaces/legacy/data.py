LEGACY_SPACES = {
    "0.39.0": {
        "space_id": "trackio-tests/trackio-0.39.0",
        "bucket_id": "trackio-tests/trackio-0.39.0-bucket",
    },
}

NUM_STEPS = 40

PROJECTS = {
    "bump-compat": {
        "run-a": {"lr": 0.01, "batch_size": 32, "optimizer": "sgd"},
        "run-b": {"lr": 0.001, "batch_size": 64, "optimizer": "adam"},
    },
    "bump-compat-extra": {
        "solo": {"seed": 7},
    },
}

IMAGE_STEP = 10
ALERT_TITLE = "loss plateau"


def metrics_at(run: str, step: int) -> dict:
    offset = sum(ord(c) for c in run) % 10
    return {
        "train/loss": round(1.0 / (step + 1) + offset / 100, 6),
        "train/accuracy": round(step / NUM_STEPS, 6),
        "val/loss": round(2.0 / (step + 2), 6),
    }
