import trackio
from trackio.sqlite_storage import SQLiteStorage


def test_status_running_then_finished(temp_dir):
    run = trackio.init(project="status_test", name="run1", config={"lr": 0.01})
    trackio.log({"loss": 0.5}, step=0)
    assert (
        SQLiteStorage.get_run_status("status_test", "run1", run_id=run.id) == "running"
    )

    trackio.finish()
    assert (
        SQLiteStorage.get_run_status("status_test", "run1", run_id=run.id) == "finished"
    )


def test_status_failed_not_overwritten_by_finish(temp_dir):
    run = trackio.init(project="status_overwrite", name="run1")
    trackio.log({"loss": 0.5}, step=0)

    run.finish(status="failed")
    assert (
        SQLiteStorage.get_run_status("status_overwrite", "run1", run_id=run.id)
        == "failed"
    )

    run.finish()
    assert (
        SQLiteStorage.get_run_status("status_overwrite", "run1", run_id=run.id)
        == "failed"
    )


def test_api_run_status(temp_dir):
    trackio.init(project="api_status", name="run1")
    trackio.log({"loss": 0.5}, step=0)
    trackio.finish()

    run = trackio.Api().runs("api_status")[0]
    assert run.status == "finished"


def test_api_run_final_metrics(temp_dir):
    trackio.init(project="final_metrics_test", name="run1")
    trackio.log({"loss": 1.0, "acc": 0.5}, step=0)
    trackio.log({"loss": 0.5, "acc": 0.8}, step=1)
    trackio.finish()

    run = trackio.Api().runs("final_metrics_test")[0]
    fm = run.final_metrics
    assert abs(fm["loss"] - 0.5) < 1e-6
    assert abs(fm["acc"] - 0.8) < 1e-6


def test_api_run_history_with_metric_filter(temp_dir):
    trackio.init(project="history_test", name="run1")
    for step in range(5):
        trackio.log({"loss": 1.0 - step * 0.1, "acc": step * 0.1}, step=step)
    trackio.finish()

    run = trackio.Api().runs("history_test")[0]
    full = run.history()
    assert len(full) == 5

    loss_history = run.history(metric="loss")
    assert len(loss_history) == 5
    assert all("value" in entry for entry in loss_history)


def test_status_survives_multiple_runs(temp_dir):
    run1 = trackio.init(project="multi_status", name="run1")
    trackio.log({"loss": 0.5}, step=0)
    trackio.finish()

    run2 = trackio.init(project="multi_status", name="run2")
    trackio.log({"loss": 0.3}, step=0)
    assert (
        SQLiteStorage.get_run_status("multi_status", "run1", run_id=run1.id)
        == "finished"
    )
    assert (
        SQLiteStorage.get_run_status("multi_status", "run2", run_id=run2.id)
        == "running"
    )

    trackio.finish()
    assert (
        SQLiteStorage.get_run_status("multi_status", "run2", run_id=run2.id)
        == "finished"
    )
