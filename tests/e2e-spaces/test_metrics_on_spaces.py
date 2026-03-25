import secrets
import time

import huggingface_hub
from gradio_client import Client

import trackio


def test_basic_logging(test_space_id):
    project_name = f"test_project_{secrets.token_urlsafe(8)}"
    run_name = "test_run"

    trackio.init(project=project_name, name=run_name, space_id=test_space_id)
    trackio.log(metrics={"loss": 0.1})
    trackio.log(metrics={"loss": 0.2, "acc": 0.9})
    trackio.finish()

    client = Client(test_space_id)

    summary = client.predict(
        project=project_name, run=run_name, api_name="/get_run_summary"
    )
    assert summary["num_logs"] == 2
    assert "loss" in summary["metrics"]
    assert "acc" in summary["metrics"]

    loss_values = client.predict(
        project=project_name,
        run=run_name,
        metric_name="loss",
        api_name="/get_metric_values",
    )
    assert len(loss_values) == 2
    assert loss_values[0]["value"] == 0.1
    assert loss_values[0]["step"] == 0
    assert loss_values[1]["value"] == 0.2
    assert loss_values[1]["step"] == 1

    acc_values = client.predict(
        project=project_name,
        run=run_name,
        metric_name="acc",
        api_name="/get_metric_values",
    )
    assert len(acc_values) == 1
    assert acc_values[0]["value"] == 0.9
    assert acc_values[0]["step"] == 1


def test_runs_data_persisted_after_restart(test_space_id):
    """Test that runs with configs are correctly restored after Space restart."""
    project_name = f"test_project_{secrets.token_urlsafe(8)}"
    run_name = "test_run_with_config"

    trackio.init(
        project=project_name,
        name=run_name,
        space_id=test_space_id,
        config={"learning_rate": 0.001, "epochs": 10},
    )
    trackio.log(metrics={"loss": 0.5})
    trackio.finish()

    client = Client(test_space_id)

    client.predict(api_name="/force_sync")

    # This will force a restart of the Space
    huggingface_hub.add_space_variable(
        test_space_id, "TRACKIO_TEST_RESTART", secrets.token_urlsafe(8)
    )

    time.sleep(10)
    deadline = time.time() + 300
    client = None
    while time.time() < deadline:
        try:
            client = Client(test_space_id, verbose=False)
            break
        except Exception:
            time.sleep(10)
    assert client is not None, "Space did not come back up after restart"

    run_names = client.predict(project=project_name, api_name="/get_runs_for_project")
    assert run_name in run_names

    summary = client.predict(
        project=project_name, run=run_name, api_name="/get_run_summary"
    )
    cfg = summary.get("config") or {}
    lr = cfg.get("learning_rate")
    assert lr is not None and abs(float(lr) - 0.001) < 1e-6
    assert cfg.get("epochs") == 10
