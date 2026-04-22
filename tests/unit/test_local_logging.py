import math
import time
import warnings
from unittest.mock import patch

import trackio
from trackio import gpu
from trackio.sqlite_storage import SQLiteStorage


def test_infinity_logging(temp_dir):
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


def test_import_from_csv(temp_dir, tmp_path):
    csv_path = tmp_path / "logs.csv"
    csv_path.write_text(
        "\n".join(
            [
                "step,timestamp,train/loss,train/acc",
                "4,2024-01-01T00:00:00+00:00,12.2,82.2",
                "52,2024-01-01T00:01:00+00:00,9.5,93.5",
                "72,2024-01-01T00:02:00+00:00,8.9,94.9",
                "82,2024-01-01T00:03:00+00:00,8.8,95.8",
            ]
        )
    )

    trackio.import_csv(
        csv_path=str(csv_path),
        project="test_project",
        name="test_run",
    )

    results = SQLiteStorage.get_logs(project="test_project", run="test_run")
    assert len(results) == 4
    assert results[0]["train/loss"] == 12.2
    assert results[0]["train/acc"] == 82.2
    assert results[0]["step"] == 4
    assert results[1]["train/loss"] == 9.5
    assert results[1]["train/acc"] == 93.5
    assert results[1]["step"] == 52
    assert results[2]["train/loss"] == 8.9
    assert results[2]["train/acc"] == 94.9
    assert results[2]["step"] == 72
    assert results[3]["train/loss"] == 8.8
    assert results[3]["train/acc"] == 95.8
    assert results[3]["step"] == 82
    assert "timestamp" in results[0]
    assert "timestamp" in results[1]
    assert "timestamp" in results[2]
    assert "timestamp" in results[3]


def test_reserved_keys_are_renamed(temp_dir):
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        run = trackio.init(project="test_reserved", name="test_run")

        run.log({"step": 100, "time": 200, "project": "test", "normal_key": 42})

        reserved_warnings = [
            warning
            for warning in captured
            if "Reserved keys renamed" in str(warning.message)
        ]
        assert len(reserved_warnings) == 1
        assert "['step', 'time', 'project']" in str(reserved_warnings[0].message)

        run.finish()

    results = SQLiteStorage.get_logs(project="test_reserved", run="test_run")
    assert len(results) == 1
    log = results[0]

    assert "__step" in log
    assert "__time" in log
    assert "__project" in log
    assert "normal_key" in log
    assert log["__step"] == 100
    assert log["__time"] == 200
    assert log["__project"] == "test"
    assert log["normal_key"] == 42


def test_auto_log_gpu(temp_dir):
    def fake_gpu_metrics(device=None, all_gpus=False):
        return {
            "gpu/0/utilization": 75,
            "gpu/0/allocated_memory": 4.5,
            "gpu/0/total_memory": 12.0,
            "gpu/0/temp": 65,
            "gpu/0/power": 150.0,
            "gpu/mean_utilization": 75,
        }

    with patch.object(gpu, "collect_gpu_metrics", fake_gpu_metrics):
        with patch.object(gpu, "get_all_gpu_count", return_value=(1, [0])):
            with patch("trackio.run.gpu_available", return_value=True):
                with patch("trackio.run.apple_gpu_available", return_value=False):
                    trackio.init(
                        project="test_gpu_project",
                        name="test_gpu_run",
                        auto_log_gpu=True,
                        gpu_log_interval=0.1,
                    )
                    trackio.log({"loss": 0.5})
                    time.sleep(0.3)
                    trackio.finish()

    system_logs = SQLiteStorage.get_system_logs(
        project="test_gpu_project", run="test_gpu_run"
    )
    assert len(system_logs) >= 1
    log = system_logs[0]
    assert log["gpu/0/utilization"] == 75
    assert log["gpu/0/allocated_memory"] == 4.5
    assert log["gpu/0/total_memory"] == 12.0
    assert log["gpu/0/temp"] == 65
    assert log["gpu/0/power"] == 150.0
    assert log["gpu/mean_utilization"] == 75
    assert "timestamp" in log


def test_auto_log_gpu_multi(temp_dir):
    def fake_gpu_metrics(device=None, all_gpus=False):
        metrics = {
            "gpu/0/utilization": 75,
            "gpu/0/allocated_memory": 4.5,
            "gpu/0/total_memory": 12.0,
            "gpu/0/temp": 65,
            "gpu/0/power": 150.0,
            "gpu/mean_utilization": 70,
        }
        if all_gpus:
            metrics.update(
                {
                    "gpu/1/utilization": 65,
                    "gpu/1/allocated_memory": 3.0,
                    "gpu/1/total_memory": 12.0,
                    "gpu/1/temp": 60,
                    "gpu/1/power": 120.0,
                }
            )
        return metrics

    with patch.object(gpu, "collect_gpu_metrics", fake_gpu_metrics):
        with patch.object(gpu, "get_all_gpu_count", return_value=(2, [0, 1])):
            with patch("trackio.run.gpu_available", return_value=True):
                with patch("trackio.run.apple_gpu_available", return_value=False):
                    trackio.init(
                        project="test_gpu_multi",
                        name="test_gpu_multi_run",
                        auto_log_gpu=True,
                        gpu_log_interval=0.1,
                    )
                    trackio.log({"loss": 0.5})
                    time.sleep(0.3)
                    trackio.finish()

    system_logs = SQLiteStorage.get_system_logs(
        project="test_gpu_multi", run="test_gpu_multi_run"
    )
    assert len(system_logs) >= 1
    log = system_logs[0]
    assert log["gpu/0/utilization"] == 75
    assert log["gpu/1/utilization"] == 65
    assert log["gpu/mean_utilization"] == 70
