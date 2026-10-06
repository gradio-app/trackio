import secrets
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import huggingface_hub
import pytest
from huggingface_hub import Volume

import trackio
from trackio.bucket_storage import _list_bucket_file_paths
from trackio.bump import BACKUP_PREFIX, bump
from trackio.remote_client import RemoteClient as Client

sys.path.insert(0, str(Path(__file__).parent / "legacy"))
from legacy_spaces import (  # noqa: E402
    ALERT_TITLE,
    IMAGE_STEP,
    LEGACY_SPACES,
    NUM_STEPS,
    PROJECTS,
    metrics_at,
)


def _cleanup(space_id, bucket_id):
    try:
        huggingface_hub.delete_repo(space_id, repo_type="space")
    except Exception:
        pass
    try:
        huggingface_hub.delete_bucket(bucket_id)
    except Exception:
        pass


def _delete_stale_copies(namespace, max_age_hours=2):
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
    prefix = f"{namespace}/bump_inplace_"
    for space in huggingface_hub.list_spaces(author=namespace, search="bump_inplace_"):
        if space.id.startswith(prefix) and space.created_at < cutoff:
            huggingface_hub.delete_repo(space.id, repo_type="space", missing_ok=True)
    for bucket in huggingface_hub.list_buckets(namespace):
        if bucket.id.startswith(prefix) and bucket.created_at < cutoff:
            huggingface_hub.delete_bucket(bucket.id, missing_ok=True)


def _temp_ids(namespace, label):
    space_id = f"{namespace}/bump_{label}_{secrets.token_hex(4)}"
    return space_id, f"{space_id}-bucket"


def _wait_for_stage(space_id, stage, timeout=900):
    hf_api = huggingface_hub.HfApi()
    deadline = time.time() + timeout
    while time.time() < deadline:
        if str(hf_api.get_space_runtime(space_id).stage) == stage:
            return
        time.sleep(5)
    raise TimeoutError(f"{space_id} did not reach {stage} within {timeout}s")


def _wait_for_runs(client, project, expected_runs, timeout=300):
    deadline = time.time() + timeout
    names = set()
    while time.time() < deadline:
        names = {
            r["name"] for r in client.predict(project, api_name="/get_runs_for_project")
        }
        if expected_runs <= names:
            return
        time.sleep(10)
    raise AssertionError(f"Runs {expected_runs - names} never appeared in {project}")


def _assert_serves_seed_data(space_id, bucket_id):
    client = Client(space_id, verbose=False)
    assert set(client.predict(api_name="/get_all_projects")) >= set(PROJECTS)
    media_files = set(_list_bucket_file_paths(bucket_id, prefix="trackio/media/"))

    for project, runs in PROJECTS.items():
        _wait_for_runs(client, project, set(runs))
        configs = list(client.predict(project, api_name="/get_run_configs").values())
        for run, config in runs.items():
            assert any(config.items() <= c.items() for c in configs), (project, run)

            logs = client.predict(project, run, api_name="/get_logs")
            assert [log["step"] for log in logs] == list(range(NUM_STEPS))
            for log in logs:
                expected = metrics_at(run, log["step"])
                assert {k: log[k] for k in expected} == expected

            if project == "bump-compat" and run == "run-a":
                image = logs[IMAGE_STEP]["samples"]
                assert image["_type"] == "trackio.image"
                assert f"trackio/media/{image['file_path']}" in media_files

    alerts = client.predict("bump-compat", api_name="/get_alerts")
    assert [(a["run"], a["title"]) for a in alerts] == [("run-b", ALERT_TITLE)]


def _log_run(space_id, bucket_id, project, run, steps=5):
    trackio.init(project=project, name=run, space_id=space_id, bucket_id=bucket_id)
    for step in range(steps):
        trackio.log({"after_bump/value": float(step)}, step=step)
    trackio.finish()


def _assert_run_logged(space_id, project, run, steps=5):
    client = Client(space_id, verbose=False)
    _wait_for_runs(client, project, {run})
    deadline = time.time() + 300
    while time.time() < deadline:
        logs = client.predict(project, run, api_name="/get_logs")
        if len(logs) == steps:
            break
        time.sleep(10)
    assert [log["after_bump/value"] for log in logs] == [float(s) for s in range(steps)]


def _create_legacy_copy(version, space_id, bucket_id):
    legacy = LEGACY_SPACES[version]
    huggingface_hub.create_bucket(bucket_id, private=False)
    huggingface_hub.copy_files(
        f"hf://buckets/{legacy['bucket_id']}/", f"hf://buckets/{bucket_id}/"
    )
    huggingface_hub.HfApi().duplicate_repo(
        legacy["space_id"],
        space_id,
        repo_type="space",
        private=False,
        space_hardware="cpu-upgrade",
        space_sleep_time=-1,
        space_secrets=[{"key": "HF_TOKEN", "value": huggingface_hub.get_token()}],
        space_variables=[
            {"key": "TRACKIO_DIR", "value": "/data/trackio"},
            {"key": "TRACKIO_BUCKET_ID", "value": bucket_id},
        ],
        space_volumes=[Volume(type="bucket", source=bucket_id, mount_path="/data")],
    )
    _wait_for_stage(space_id, "RUNNING")


@pytest.mark.parametrize("version", sorted(LEGACY_SPACES))
def test_bump_in_place_migrates_legacy_data_and_inbox(version):
    namespace = LEGACY_SPACES[version]["space_id"].split("/")[0]
    _delete_stale_copies(namespace)
    space_id, bucket_id = _temp_ids(namespace, "inplace")

    try:
        _create_legacy_copy(version, space_id, bucket_id)

        errors = []

        def run_bump():
            try:
                bump(space_id)
            except Exception as e:
                errors.append(e)

        bump_thread = threading.Thread(target=run_bump)
        bump_thread.start()
        _wait_for_stage(space_id, "PAUSED", timeout=300)
        _log_run(space_id, bucket_id, "bump-compat", "during-bump")
        bump_thread.join()
        assert not errors, errors

        _assert_serves_seed_data(space_id, bucket_id)
        _assert_run_logged(space_id, "bump-compat", "during-bump")
        backups = _list_bucket_file_paths(bucket_id, prefix=f"{BACKUP_PREFIX}/")
        assert {p.rsplit("/", 1)[-1] for p in backups} >= {
            f"{project}.db" for project in PROJECTS
        }
    finally:
        _cleanup(space_id, bucket_id)
