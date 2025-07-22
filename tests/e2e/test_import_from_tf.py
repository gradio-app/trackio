from pathlib import Path
import trackio
from trackio.sqlite_storage import SQLiteStorage


def test_import_from_tf_events(temp_db):
    # Use the pre-generated TensorFlow events directory
    log_dir = Path(__file__).parent / "simple_tf_run"
    trackio.import_tf_events(
        log_dir=str(log_dir),
        project="test_tf_project",
        name="test_run",
    )

    results = SQLiteStorage.get_metrics(project="test_tf_project", run="test_run_main")
    # There should be 3 steps × 2 metrics = 6 entries
    assert len(results) == 6

    # Check values for each step
    expected = [
        {"step": 0, "loss": 1.0, "accuracy": 0.8},
        {"step": 1, "loss": 0.5, "accuracy": 0.9},
        {"step": 2, "loss": 0.33333334, "accuracy": 1.0},
    ]
    for exp in expected:
        step_metrics = [r for r in results if r["step"] == exp["step"]]
        assert len(step_metrics) == 2
        loss_metric = next(r for r in step_metrics if "loss" in r)
        accuracy_metric = next(r for r in step_metrics if "accuracy" in r)
        assert abs(loss_metric["loss"] - exp["loss"]) < 1e-5
        assert abs(accuracy_metric["accuracy"] - exp["accuracy"]) < 1e-5
        assert "timestamp" in loss_metric
        assert "timestamp" in accuracy_metric
