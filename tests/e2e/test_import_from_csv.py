import trackio
from trackio.sqlite_storage import SQLiteStorage


def test_basic_logging(temp_db):
    trackio.init(project="test_project", name="test_run")
    trackio.log(metrics={"loss": 0.1})
    trackio.log(metrics={"loss": 0.2, "acc": 0.9})
    trackio.finish()

    results = SQLiteStorage.get_metrics(project="test_project", run="test_run")
    assert len(results) == 2
    assert results[0]["loss"] == 0.1
    assert results[0]["step"] == 0
    assert results[1]["loss"] == 0.2
    assert results[1]["acc"] == 0.9
    assert results[1]["step"] == 1
    assert "timestamp" in results[0]
    assert "timestamp" in results[1]
