import secrets
import time

import numpy as np
import pytest

import trackio
from trackio.remote_client import RemoteClient as Client


def _predict_run_summary(
    test_space_id: str,
    project_name: str,
    run_name: str,
    *,
    min_num_logs: int = 0,
    timeout: float = 240,
):
    deadline = time.time() + timeout
    last_err: Exception | None = None
    flush_attempted = False
    while time.time() < deadline:
        try:
            client = Client(test_space_id, verbose=False)
            summary = client.predict(
                project=project_name, run=run_name, api_name="/get_run_summary"
            )
            if summary["num_logs"] >= min_num_logs:
                return summary
            last_err = None
        except Exception as e:
            last_err = e
        if not flush_attempted and time.time() > deadline - max(timeout - 60, 0):
            flush_run = trackio.init(
                project=project_name,
                name=f"flush_{secrets.token_urlsafe(4)}",
                space_id=test_space_id,
                auto_log_gpu=False,
            )
            flush_deadline = time.time() + 30
            while flush_run._client is None and time.time() < flush_deadline:
                time.sleep(0.1)
            flush_run.finish()
            flush_attempted = True
        time.sleep(5)
    if last_err is not None:
        raise last_err
    raise TimeoutError("get_run_summary timed out before logs appeared")


def test_config_persisted_on_spaces(test_space_id, wait_for_client):
    project_name = f"test_config_{secrets.token_urlsafe(8)}"
    run_name = f"config_run_{secrets.token_urlsafe(6)}"

    run = trackio.init(
        project=project_name,
        name=run_name,
        space_id=test_space_id,
        config={"lr": 0.001, "batch_size": 32, "model": "resnet50"},
    )
    wait_for_client(run)

    trackio.log({"loss": 0.5, "acc": 0.8})
    trackio.log({"loss": 0.3, "acc": 0.9})
    trackio.finish()

    summary = _predict_run_summary(
        test_space_id, project_name, run_name, min_num_logs=2
    )
    assert summary["num_logs"] == 2
    assert "loss" in summary["metrics"]
    assert "acc" in summary["metrics"]


def test_system_metrics_on_spaces(test_space_id, wait_for_client):
    project_name = f"test_system_{secrets.token_urlsafe(8)}"
    run_name = f"system_run_{secrets.token_urlsafe(6)}"
    run = trackio.init(
        project=project_name,
        name=run_name,
        space_id=test_space_id,
        auto_log_gpu=False,
    )
    wait_for_client(run)
    run.log_system(
        {
            "gpu/0/utilization": 75,
            "gpu/0/allocated_memory": 4.5,
            "gpu/0/total_memory": 12.0,
            "gpu/0/temp": 65,
            "gpu/0/power": 150.0,
            "gpu/mean_utilization": 75,
        }
    )
    run.log({"loss": 0.5})
    run.finish()

    try:
        summary = _predict_run_summary(
            test_space_id, project_name, run_name, min_num_logs=1, timeout=360
        )
    except TimeoutError:
        pytest.skip("Space did not surface run summary within timeout")
    assert summary["num_logs"] >= 1

    deadline = time.time() + 120
    system_logs = []
    while time.time() < deadline:
        try:
            client = Client(test_space_id, verbose=False)
            system_logs = client.predict(
                project=project_name, run=run_name, api_name="/get_system_logs"
            )
            if system_logs:
                break
        except Exception:
            pass
        time.sleep(5)
    if not system_logs:
        pytest.skip("Space did not surface system logs within timeout")


def test_image_upload_on_spaces(test_space_id, wait_for_client, temp_dir):
    project_name = f"test_image_{secrets.token_urlsafe(8)}"
    run_name = "image_run"

    run = trackio.init(
        project=project_name,
        name=run_name,
        space_id=test_space_id,
    )
    wait_for_client(run)

    img_array = np.random.randint(0, 255, (64, 64, 3), dtype=np.uint8)
    image = trackio.Image(img_array, caption="test_image")

    trackio.log({"loss": 0.5, "sample": image})
    trackio.finish()

    summary = _predict_run_summary(
        test_space_id, project_name, run_name, min_num_logs=1
    )
    assert summary["num_logs"] == 1
    assert "loss" in summary["metrics"]
    assert "sample" in summary["metrics"]
