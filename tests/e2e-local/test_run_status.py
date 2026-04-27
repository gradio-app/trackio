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
