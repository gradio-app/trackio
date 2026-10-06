import sys
import time
from pathlib import Path

import huggingface_hub
import pytest
from huggingface_hub import Volume

from trackio.bump import bump
from trackio.remote_client import RemoteClient

sys.path.insert(0, str(Path(__file__).parent / "legacy"))
from legacy_spaces import (  # noqa: E402
    ALERT_TITLE,
    IMAGE_STEP,
    LEGACY_SPACES,
    NUM_STEPS,
    PROJECTS,
    metrics_at,
)


def _delete(space_id, bucket_id):
    huggingface_hub.delete_repo(space_id, repo_type="space", missing_ok=True)
    huggingface_hub.delete_bucket(bucket_id, missing_ok=True)


def _duplicate(legacy, space_id, bucket_id):
    huggingface_hub.create_bucket(bucket_id)
    huggingface_hub.copy_files(
        f"hf://buckets/{legacy['bucket_id']}/", f"hf://buckets/{bucket_id}/"
    )
    huggingface_hub.HfApi().duplicate_repo(
        legacy["space_id"],
        space_id,
        repo_type="space",
        space_hardware="cpu-upgrade",
        space_sleep_time=-1,
        space_secrets=[{"key": "HF_TOKEN", "value": huggingface_hub.get_token()}],
        space_variables=[
            {"key": "TRACKIO_DIR", "value": "/data/trackio"},
            {"key": "TRACKIO_BUCKET_ID", "value": bucket_id},
        ],
        space_volumes=[Volume(type="bucket", source=bucket_id, mount_path="/data")],
    )
    while str(huggingface_hub.HfApi().get_space_runtime(space_id).stage) != "RUNNING":
        time.sleep(10)


@pytest.mark.parametrize("version", sorted(LEGACY_SPACES))
def test_bump_migrates_legacy_space(test_space_id, version):
    namespace, name = test_space_id.split("/")
    space_id = f"{namespace}/bump_in_place_{name.removeprefix('test_')}_{version}"
    bucket_id = f"{space_id}-bucket"
    _delete(space_id, bucket_id)

    try:
        _duplicate(LEGACY_SPACES[version], space_id, bucket_id)
        bump(space_id)

        client = RemoteClient(space_id)
        for project, runs in PROJECTS.items():
            configs = client.predict(project, api_name="/get_run_configs").values()
            for run, config in runs.items():
                assert any(config.items() <= c.items() for c in configs)
                logs = client.predict(project, run, api_name="/get_logs")
                assert [log["step"] for log in logs] == list(range(NUM_STEPS))
                for log in logs:
                    assert metrics_at(run, log["step"]).items() <= log.items()

        logs = client.predict("bump-compat", "run-a", api_name="/get_logs")
        assert logs[IMAGE_STEP]["samples"]["_type"] == "trackio.image"
        alerts = client.predict("bump-compat", api_name="/get_alerts")
        assert [alert["title"] for alert in alerts] == [ALERT_TITLE]
    finally:
        _delete(space_id, bucket_id)
