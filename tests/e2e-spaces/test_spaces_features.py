import secrets
import time
from unittest.mock import patch

import numpy as np
from gradio_client import Client

import trackio
from trackio import gpu


def test_config_persisted_on_spaces(test_space_id, wait_for_client):
    project_name = f"test_config_{secrets.token_urlsafe(8)}"
    run_name = "config_run"

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

    client = Client(test_space_id)

    summary = client.predict(
        project=project_name, run=run_name, api_name="/get_run_summary"
    )
    assert summary["num_logs"] == 2
    assert "loss" in summary["metrics"]
    assert "acc" in summary["metrics"]


def test_system_metrics_on_spaces(test_space_id, wait_for_client):
    project_name = f"test_system_{secrets.token_urlsafe(8)}"
    run_name = "system_run"

    def fake_gpu_metrics(device=None):
        return {
            "gpu/0/utilization": 75,
            "gpu/0/allocated_memory": 4.5,
            "gpu/0/total_memory": 12.0,
            "gpu/0/temp": 65,
            "gpu/0/power": 150.0,
            "gpu/mean_utilization": 75,
        }

    with patch.object(gpu, "collect_gpu_metrics", fake_gpu_metrics):
        with patch.object(gpu, "get_gpu_count", return_value=(1, [0])):
            run = trackio.init(
                project=project_name,
                name=run_name,
                space_id=test_space_id,
                auto_log_gpu=True,
                gpu_log_interval=0.2,
            )
            wait_for_client(run)

            trackio.log({"loss": 0.5})
            time.sleep(1)
            trackio.finish()

    client = Client(test_space_id)
    summary = client.predict(
        project=project_name, run=run_name, api_name="/get_run_summary"
    )
    assert summary["num_logs"] >= 1


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

    client = Client(test_space_id)
    summary = client.predict(
        project=project_name, run=run_name, api_name="/get_run_summary"
    )
    assert summary["num_logs"] == 1
    assert "loss" in summary["metrics"]
    assert "sample" in summary["metrics"]
