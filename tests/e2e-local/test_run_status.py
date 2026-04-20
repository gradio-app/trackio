import trackio
from trackio.sqlite_storage import SQLiteStorage


def test_status_running_then_finished(temp_dir):
    run = trackio.init(project="status_test", name="run1", config={"lr": 0.01})
    trackio.log({"loss": 0.5}, step=0)

    status = SQLiteStorage.get_run_status("status_test", "run1", run_id=run.id)
    assert status == "running"

    trackio.finish()

    status = SQLiteStorage.get_run_status("status_test", "run1", run_id=run.id)
    assert status == "finished"


def test_status_failed_on_unclean_exit(temp_dir):
    run = trackio.init(project="status_test_fail", name="crash_run")
    trackio.log({"loss": 0.5}, step=0)

    assert not run._finished
    run.finish(status="failed")

    status = SQLiteStorage.get_run_status(
        "status_test_fail", "crash_run", run_id=run.id
    )
    assert status == "failed"


def test_status_failed_not_overwritten_by_finish(temp_dir):
    run = trackio.init(project="status_overwrite", name="run1")
    trackio.log({"loss": 0.5}, step=0)

    run.finish(status="failed")
    run.finish()

    status = SQLiteStorage.get_run_status("status_overwrite", "run1", run_id=run.id)
    assert status == "failed"


def test_finish_idempotent(temp_dir):
    run = trackio.init(project="status_idempotent", name="run1")
    trackio.log({"loss": 0.5}, step=0)
    run.finish()
    run.finish()

    status = SQLiteStorage.get_run_status("status_idempotent", "run1", run_id=run.id)
    assert status == "finished"


def test_api_run_status(temp_dir):
    trackio.init(project="api_status", name="run1")
    trackio.log({"loss": 0.5}, step=0)
    trackio.finish()

    api = trackio.Api()
    runs = api.runs("api_status")
    run = runs[0]
    assert run.status == "finished"


def test_status_survives_multiple_runs(temp_dir):
    run1 = trackio.init(project="multi_status", name="run1")
    trackio.log({"loss": 0.5}, step=0)
    trackio.finish()

    run2 = trackio.init(project="multi_status", name="run2")
    trackio.log({"loss": 0.3}, step=0)

    status1 = SQLiteStorage.get_run_status("multi_status", "run1", run_id=run1.id)
    status2 = SQLiteStorage.get_run_status("multi_status", "run2", run_id=run2.id)
    assert status1 == "finished"
    assert status2 == "running"

    trackio.finish()
    status2 = SQLiteStorage.get_run_status("multi_status", "run2", run_id=run2.id)
    assert status2 == "finished"
