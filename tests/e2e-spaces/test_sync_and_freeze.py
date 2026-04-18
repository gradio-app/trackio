import secrets
import tempfile
import time
from pathlib import Path

import huggingface_hub
import pyarrow.parquet as pq
from huggingface_hub import Volume

import trackio
from trackio import deploy, utils
from trackio.remote_client import RemoteClient as Client


def _wait_for_space_ready(space_id, timeout=300):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            Client(space_id, verbose=False)
            return
        except Exception:
            time.sleep(10)
    raise TimeoutError(f"Space {space_id} not ready after {timeout}s")


def _download_parquet_from_bucket(bucket_id, remote_name="metrics.parquet"):
    with tempfile.TemporaryDirectory() as tmp:
        local_path = Path(tmp) / remote_name
        huggingface_hub.download_bucket_files(
            bucket_id,
            files=[(remote_name, str(local_path))],
            token=huggingface_hub.utils.get_token(),
        )
        return pq.read_table(local_path).to_pylist()


def _cleanup_space(space_id):
    try:
        huggingface_hub.delete_repo(space_id, repo_type="space")
    except Exception:
        pass


def _cleanup_bucket(bucket_id):
    try:
        huggingface_hub.delete_bucket(
            bucket_id, token=huggingface_hub.utils.get_token()
        )
    except Exception:
        pass


def _namespace_scoped_repo_id(test_space_id: str, repo_name: str) -> str:
    if "/" in test_space_id:
        namespace = test_space_id.split("/", 1)[0]
        return f"{namespace}/{repo_name}"
    return repo_name


def _repo_safe_suffix(nbytes: int = 6) -> str:
    return secrets.token_hex(nbytes)


def test_sync_to_gradio_space(test_space_id, temp_dir):
    project_name = f"test_sync_gradio_{secrets.token_urlsafe(8)}"
    run_name = "run1"

    trackio.init(project=project_name, name=run_name)
    trackio.log({"loss": 0.5, "acc": 0.8})
    trackio.log({"loss": 0.3, "acc": 0.85})
    trackio.log({"loss": 0.1, "acc": 0.9})
    trackio.finish()

    space_id = deploy.sync(project=project_name, space_id=test_space_id)

    client = Client(space_id, verbose=False)
    summary = client.predict(
        project=project_name, run=run_name, api_name="/get_run_summary"
    )
    assert summary["num_logs"] == 3
    assert "loss" in summary["metrics"]
    assert "acc" in summary["metrics"]

    loss_values = client.predict(
        project=project_name,
        run=run_name,
        metric_name="loss",
        api_name="/get_metric_values",
    )
    assert len(loss_values) == 3
    assert loss_values[0]["value"] == 0.5
    assert loss_values[2]["value"] == 0.1


def test_sync_to_static_space_incremental(test_space_id, temp_dir):
    project_name = f"test_sync_static_{secrets.token_urlsafe(8)}"
    run_name = "run1"
    suffix = _repo_safe_suffix()
    space_id = _namespace_scoped_repo_id(test_space_id, f"trackio-test-static-{suffix}")
    space_id, _, bucket_id = utils.preprocess_space_and_dataset_ids(space_id, None)

    try:
        trackio.init(project=project_name, name=run_name)
        trackio.log({"loss": 0.5})
        trackio.log({"loss": 0.3})
        trackio.finish()

        deploy.sync(project=project_name, space_id=space_id, sdk="static")

        df1 = _download_parquet_from_bucket(bucket_id)
        assert len(df1) == 2
        assert "loss" in df1[0]

        trackio.init(project=project_name, name=run_name)
        trackio.log({"loss": 0.1})
        trackio.log({"loss": 0.05})
        trackio.finish()

        deploy.sync(project=project_name, space_id=space_id, sdk="static")

        df2 = _download_parquet_from_bucket(bucket_id)
        assert len(df2) == 4
        assert sorted(row["loss"] for row in df2) == [0.05, 0.1, 0.3, 0.5]
    finally:
        _cleanup_space(space_id)
        _cleanup_bucket(bucket_id)


def test_sync_gradio_then_freeze_to_static(test_space_id, temp_dir):
    project_name = f"test_freeze_{secrets.token_urlsafe(8)}"
    run_name = "run1"

    trackio.init(project=project_name, name=run_name)
    trackio.log({"loss": 0.5, "acc": 0.8})
    trackio.log({"loss": 0.3, "acc": 0.85})
    trackio.log({"loss": 0.1, "acc": 0.9})
    trackio.finish()

    deploy.sync(project=project_name, space_id=test_space_id)

    client = Client(test_space_id, verbose=False)
    client.predict(api_name="/force_sync")
    time.sleep(5)

    suffix = _repo_safe_suffix()
    frozen_space_id = _namespace_scoped_repo_id(
        test_space_id, f"trackio-test-frozen-{suffix}"
    )
    frozen_space_id, _, frozen_bucket_id = utils.preprocess_space_and_dataset_ids(
        frozen_space_id, None
    )

    try:
        deploy.freeze(
            space_id=test_space_id,
            project=project_name,
            new_space_id=frozen_space_id,
        )

        df = _download_parquet_from_bucket(frozen_bucket_id)
        assert len(df) == 3
        assert "loss" in df[0]
        assert "acc" in df[0]
        assert sorted(row["loss"] for row in df) == [0.1, 0.3, 0.5]
    finally:
        _cleanup_space(frozen_space_id)
        _cleanup_bucket(frozen_bucket_id)


def test_sync_reuses_existing_space_bucket_across_projects(test_space_id, temp_dir):
    suffix = _repo_safe_suffix()
    space_id = _namespace_scoped_repo_id(
        test_space_id, f"trackio-test-auto-bucket-reuse-{suffix}"
    )
    first_project = f"test_auto_bucket_reuse_first_{suffix}"
    second_project = f"test_auto_bucket_reuse_second_{suffix}"
    created_bucket_id = None

    try:
        trackio.init(project=first_project, name="run1")
        trackio.log({"loss": 0.5})
        trackio.finish()

        deploy.sync(project=first_project, space_id=space_id)
        created_bucket_id = deploy._get_source_bucket(space_id)
        huggingface_hub.HfApi().set_space_volumes(
            space_id,
            [
                Volume(
                    type="bucket", source=created_bucket_id, mount_path="/trackio-data"
                )
            ],
        )

        trackio.init(project=second_project, name="run1")
        trackio.log({"acc": 0.9})
        trackio.finish()

        deploy.sync(project=second_project, space_id=space_id)
        reused_bucket_id = deploy._get_source_bucket(space_id)
        volumes = deploy._get_space_volumes(space_id)

        assert reused_bucket_id == created_bucket_id
        assert any(
            v.type == "bucket"
            and v.source == created_bucket_id
            and v.mount_path == "/data"
            for v in volumes
        )
        assert not any(
            v.type == "bucket"
            and v.source == created_bucket_id
            and v.mount_path == "/trackio-data"
            for v in volumes
        )
    finally:
        _cleanup_space(space_id)
        if created_bucket_id is not None:
            _cleanup_bucket(created_bucket_id)


def test_sync_uses_fresh_auto_bucket_for_new_space_when_default_exists(
    test_space_id, temp_dir
):
    suffix = _repo_safe_suffix()
    project_name = f"test_auto_bucket_collision_{suffix}"
    space_id = _namespace_scoped_repo_id(
        test_space_id, f"trackio-test-auto-bucket-collision-{suffix}"
    )
    space_id, _, preferred_bucket_id = utils.preprocess_space_and_dataset_ids(
        space_id, None
    )
    created_bucket_ids = {preferred_bucket_id}

    try:
        huggingface_hub.create_bucket(preferred_bucket_id)

        trackio.init(project=project_name, name="run1")
        trackio.log({"loss": 0.5})
        trackio.finish()

        deploy.sync(project=project_name, space_id=space_id)
        actual_bucket_id = deploy._get_source_bucket(space_id)
        created_bucket_ids.add(actual_bucket_id)

        assert actual_bucket_id != preferred_bucket_id
        assert actual_bucket_id.startswith(f"{preferred_bucket_id}-")
    finally:
        _cleanup_space(space_id)
        for bucket_id in created_bucket_ids:
            _cleanup_bucket(bucket_id)
