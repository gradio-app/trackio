import math
import time
import warnings
from unittest.mock import patch

import trackio
from trackio import gpu
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


def test_class_config_storage_in_database(temp_dir):
    class LoraConfig:
        def __init__(self):
            self.r = 8
            self.lora_alpha = 16
            self.target_modules = ["q_proj", "v_proj"]
            self.lora_dropout = 0.1
            self._private_config = "hidden"

    lora_config = LoraConfig()

    trackio.init(project="test_project", name="test_run", config=lora_config)
    trackio.log(metrics={"loss": 0.5})
    trackio.finish()

    stored_config = SQLiteStorage.get_run_config("test_project", "test_run")
    assert stored_config["r"] == 8
    assert stored_config["lora_alpha"] == 16
    assert stored_config["target_modules"] == ["q_proj", "v_proj"]
    assert stored_config["lora_dropout"] == 0.1
    assert "_private_config" not in stored_config


def test_reserved_keys_are_renamed(temp_dir):
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        run = trackio.init(project="test_reserved", name="test_run")

        run.log({"step": 100, "time": 200, "project": "test", "normal_key": 42})

        reserved_warnings = [
            warning for warning in w if "Reserved keys renamed" in str(warning.message)
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
    def fake_gpu_metrics(device=None):
        return {
            "gpu/0/utilization": 75,
            "gpu/0/allocated_memory": 4.5,
            "gpu/0/total_memory": 12.0,
            "gpu/0/temp": 65,
            "gpu/0/power": 150.0,
            "gpu/mean_utilization": 75,
        }

    with patch.object(gpu, "collect_gpu_metrics", fake_gpu_metrics):
        with patch.object(gpu, "get_gpu_count", return_value=(1, [0])):
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
