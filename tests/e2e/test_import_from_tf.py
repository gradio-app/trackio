from pathlib import Path

from tensorboardX import SummaryWriter

import trackio
from trackio.sqlite_storage import SQLiteStorage


def test_import_from_tf_events(temp_dir):
    test_run_dir = "tf_test_run"

    def create_tfevents_tensorboardx(log_dir: Path):
        log_dir.mkdir(parents=True, exist_ok=True)
        writer = SummaryWriter(log_dir=str(log_dir))

        for step in range(10):
            writer.add_scalar("loss", 1.0 / (step + 1), step)
            writer.add_scalar("accuracy", 0.8 + 0.02 * step, step)

        writer.close()

    create_tfevents_tensorboardx(Path(test_run_dir))

    log_dir = Path(__file__).parent / test_run_dir
    trackio.import_tf_events(
        log_dir=str(log_dir),
        project="test_tf_project",
        name="test_run",
    )

    results = SQLiteStorage.get_logs(project="test_tf_project", run="test_run_main")
    # There should be 5 steps × 2 metrics = 10 entries
    assert len(results) == 10

    expected = [
        {"step": 0, "accuracy": 0.80, "loss": 1 / 1.0},
        {"step": 1, "accuracy": 0.82, "loss": 1 / 2.0},
        {"step": 2, "accuracy": 0.84, "loss": 1 / 3.0},
        {"step": 3, "accuracy": 0.86, "loss": 1 / 4.0},
        {"step": 4, "accuracy": 0.88, "loss": 1 / 5.0},
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
