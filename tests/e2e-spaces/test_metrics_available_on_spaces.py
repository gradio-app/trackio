import os
import time
import secrets

import pytest
from gradio_client import Client

import trackio


def get_pr_number():
    pr_number = os.environ.get("PR_NUMBER")
    if not pr_number:
        pytest.skip("PR_NUMBER environment variable not set")
    return pr_number


def wait_for_space_ready(space_url, max_retries=30, initial_delay=5):
    delay = initial_delay
    for attempt in range(max_retries):
        try:
            client = Client(space_url, verbose=False)
            client.predict(api_name="/get_all_projects")
            return client
        except Exception:
            if attempt < max_retries - 1:
                time.sleep(delay)
                delay = min(delay * 1.5, 60)
            else:
                raise TimeoutError(f"Space {space_url} not ready after {max_retries} attempts")


def test_basic_logging():
    pr_number = get_pr_number()
    space_id = f"trackio-tests/test_{pr_number}"
    project_name = f"test_project_{secrets.token_urlsafe(8)}"
    run_name = "test_run"

    trackio.init(project=project_name, name=run_name, space_id=space_id)
    trackio.log(metrics={"loss": 0.1})
    trackio.log(metrics={"loss": 0.2, "acc": 0.9})
    trackio.finish()

    user_name, space_name = space_id.split("/")
    space_url = f"https://{user_name}-{space_name}.hf.space/"

    client = wait_for_space_ready(space_url)

    summary = client.predict(project_name, run_name, api_name="/get_run_summary")
    assert summary["num_logs"] == 2
    assert "loss" in summary["metrics"]
    assert "acc" in summary["metrics"]
    assert summary["last_step"] == 1

    loss_values = client.predict(project_name, run_name, "loss", api_name="/get_metric_values")
    assert len(loss_values) == 2
    assert loss_values[0]["value"] == 0.1
    assert loss_values[0]["step"] == 0
    assert loss_values[1]["value"] == 0.2
    assert loss_values[1]["step"] == 1

    acc_values = client.predict(project_name, run_name, "acc", api_name="/get_metric_values")
    assert len(acc_values) == 1
    assert acc_values[0]["value"] == 0.9
    assert acc_values[0]["step"] == 1
