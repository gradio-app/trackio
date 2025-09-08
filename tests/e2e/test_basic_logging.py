import math

import trackio
from trackio.sqlite_storage import SQLiteStorage


def test_basic_logging(temp_dir):
    trackio.init(project="test_project", name="test_run")
    trackio.log(metrics={"loss": 0.1})
    trackio.log(metrics={"loss": 0.2, "acc": 0.9})
    trackio.finish()

    results = SQLiteStorage.get_logs(project="test_project", run="test_run")
    assert len(results) == 2
    assert results[0]["loss"] == 0.1
    assert results[0]["step"] == 0

    assert results[1]["loss"] == 0.2
    assert results[1]["acc"] == 0.9
    assert results[1]["step"] == 1
    assert "timestamp" in results[0]
    assert "timestamp" in results[1]


def test_basic_logging_with_step(temp_dir):
    trackio.init(project="test_project", name="test_run")
    trackio.log(metrics={"loss": 0.1}, step=0)
    trackio.log(metrics={"loss": 0.2, "acc": 0.9}, step=2)
    trackio.finish()

    results = SQLiteStorage.get_logs(project="test_project", run="test_run")
    assert len(results) == 2
    assert results[0]["loss"] == 0.1
    assert results[0]["step"] == 0

    assert results[1]["loss"] == 0.2
    assert results[1]["acc"] == 0.9
    assert results[1]["step"] == 2
    assert "timestamp" in results[0]
    assert "timestamp" in results[1]


def test_infinity_logging(temp_dir):
    """Test end-to-end logging of infinity and NaN values."""
    trackio.init(project="test_infinity", name="test_run")
    trackio.log(
        metrics={
            "loss": float("inf"),
            "accuracy": float("-inf"),
            "f1_score": float("nan"),
            "normal_value": 0.95,
        }
    )
    trackio.finish()

    results = SQLiteStorage.get_logs(project="test_infinity", run="test_run")
    assert len(results) == 1
    log = results[0]

    assert math.isinf(log["loss"]) and log["loss"] > 0
    assert math.isinf(log["accuracy"]) and log["accuracy"] < 0
    assert math.isnan(log["f1_score"])
    assert log["normal_value"] == 0.95
