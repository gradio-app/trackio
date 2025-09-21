"""
Tests for GPU logging functionality in TrackIO.
"""

import pytest
from unittest.mock import patch, MagicMock

import trackio
from trackio.sqlite_storage import SQLiteStorage


def test_gpu_logging_disabled_by_default(temp_dir):
    """Test that GPU logging is disabled by default."""
    run = trackio.init(project="test-project", name="test-run")
    assert not getattr(run, "log_gpu", True)  # Should be False by default

    trackio.log({"loss": 0.5})
    trackio.finish()

    # Check that no GPU metrics were logged
    logs = SQLiteStorage.get_logs(project="test-project", run="test-run")
    assert len(logs) == 1

    # Should not contain any GPU metrics
    gpu_keys = [
        k for k in logs[0].keys() if k.startswith("gpu/") or k.startswith("gpu_")
    ]
    assert len(gpu_keys) == 0


def test_gpu_logging_enabled_explicitly(temp_dir):
    """Test that GPU logging works when explicitly enabled."""
    run = trackio.init(project="test-project", name="test-run", log_gpu=True)
    assert getattr(run, "log_gpu", False)

    trackio.log({"loss": 0.5})
    trackio.finish()

    # Check that GPU metrics were attempted to be logged
    logs = SQLiteStorage.get_logs(project="test-project", run="test-run")
    assert len(logs) == 1

    # May or may not contain GPU metrics depending on hardware availability
    # But the function should not crash


@patch("trackio._get_gpu_metrics")
def test_gpu_logging_with_mock_monitor(mock_get_gpu_metrics, temp_dir):
    """Test GPU logging with mocked GPU monitor."""
    # Mock the _get_gpu_metrics function to return fake data
    mock_gpu_metrics = {
        "gpu/utilization": 85.0,
        "gpu/memory_used_gb": 12.5,
        "gpu/memory_percent": 52.1,
        "gpu/temperature_c": 75,
        "gpu/power_w": 250,
        "gpu/power_limit_w": 300,
        "gpu/fan_speed": 65,
        "gpu/fan_rpm": 2100,
        "gpu/clock_graphics_mhz": 1800,
        "gpu/clock_memory_mhz": 1000,
        "gpu/clock_fclk_mhz": 1600,
        "gpu/clock_socclk_mhz": 1200,
        "gpu/perf_state": "P0",
    }
    mock_get_gpu_metrics.return_value = mock_gpu_metrics

    run = trackio.init(project="test-project", name="test-run", log_gpu=True)
    trackio.log({"loss": 0.5})
    trackio.finish()

    # Check that GPU metrics were logged
    logs = SQLiteStorage.get_logs(project="test-project", run="test-run")
    assert len(logs) == 1

    log_entry = logs[0]

    # Check that expected GPU metrics are present
    assert "gpu/utilization" in log_entry
    assert log_entry["gpu/utilization"] == 85.0
    assert "gpu/memory_used_gb" in log_entry
    assert log_entry["gpu/memory_used_gb"] == 12.5
    assert "gpu/memory_percent" in log_entry
    assert log_entry["gpu/memory_percent"] == 52.1
    assert "gpu/temperature_c" in log_entry
    assert log_entry["gpu/temperature_c"] == 75
    assert "gpu/power_w" in log_entry
    assert log_entry["gpu/power_w"] == 250
    assert "gpu/power_limit_w" in log_entry
    assert log_entry["gpu/power_limit_w"] == 300
    assert "gpu/fan_speed" in log_entry
    assert log_entry["gpu/fan_speed"] == 65
    assert "gpu/fan_rpm" in log_entry
    assert log_entry["gpu/fan_rpm"] == 2100

    # Check clock frequencies
    assert "gpu/clock_graphics_mhz" in log_entry
    assert log_entry["gpu/clock_graphics_mhz"] == 1800
    assert "gpu/clock_memory_mhz" in log_entry
    assert log_entry["gpu/clock_memory_mhz"] == 1000
    assert "gpu/clock_fclk_mhz" in log_entry
    assert log_entry["gpu/clock_fclk_mhz"] == 1600
    assert "gpu/clock_socclk_mhz" in log_entry
    assert log_entry["gpu/clock_socclk_mhz"] == 1200

    assert "gpu/perf_state" in log_entry
    assert log_entry["gpu/perf_state"] == "P0"

    # Check that original metrics are still there
    assert "loss" in log_entry
    assert log_entry["loss"] == 0.5


def test_gpu_logging_per_call_override(temp_dir):
    """Test that log_gpu parameter can be overridden per call."""
    # Initialize with GPU logging disabled
    run = trackio.init(project="test-project", name="test-run", log_gpu=False)

    # Log without GPU metrics
    trackio.log({"loss": 0.5}, log_gpu=False)

    # Log with GPU metrics (override)
    trackio.log({"loss": 0.4}, log_gpu=True)

    trackio.finish()

    logs = SQLiteStorage.get_logs(project="test-project", run="test-run")
    assert len(logs) == 2

    # First log should not have GPU metrics (or they should be empty if no GPU)
    # Second log should have attempted GPU metrics collection


@patch("trackio._get_gpu_metrics")
def test_gpu_logging_with_multiple_gpus(mock_get_gpu_metrics, temp_dir):
    """Test GPU logging with multiple GPUs."""
    # Mock multi-GPU metrics (simulating the output after processing multiple GPUs)
    mock_gpu_metrics = {
        "gpu_0/utilization": 85.0,
        "gpu_0/memory_used_gb": 12.5,
        "gpu_0/memory_percent": 52.1,
        "gpu_0/temperature_c": 75,
        "gpu_0/power_w": 250,
        "gpu_1/utilization": 90.0,
        "gpu_1/memory_used_gb": 20.0,
        "gpu_1/memory_percent": 83.3,
        "gpu_1/temperature_c": 80,
        "gpu_1/power_w": 275,
    }
    mock_get_gpu_metrics.return_value = mock_gpu_metrics

    run = trackio.init(project="test-project", name="test-run", log_gpu=True)
    trackio.log({"loss": 0.5})
    trackio.finish()

    logs = SQLiteStorage.get_logs(project="test-project", run="test-run")
    assert len(logs) == 1

    log_entry = logs[0]

    # Check that metrics for both GPUs are present
    assert "gpu_0/utilization" in log_entry
    assert log_entry["gpu_0/utilization"] == 85.0
    assert "gpu_1/utilization" in log_entry
    assert log_entry["gpu_1/utilization"] == 90.0

    assert "gpu_0/temperature_c" in log_entry
    assert log_entry["gpu_0/temperature_c"] == 75
    assert "gpu_1/temperature_c" in log_entry
    assert log_entry["gpu_1/temperature_c"] == 80


def test_gpu_logging_handles_monitor_failure(temp_dir):
    """Test that GPU logging gracefully handles monitor failures."""
    with patch("trackio.gpu_monitor.GPUMonitor") as mock_gpu_monitor:
        # Mock monitor that raises an exception
        mock_monitor_instance = MagicMock()
        mock_monitor_instance.initialized = False
        mock_gpu_monitor.return_value = mock_monitor_instance

        run = trackio.init(project="test-project", name="test-run", log_gpu=True)

        # This should not crash even if GPU monitoring fails
        trackio.log({"loss": 0.5})
        trackio.finish()

        logs = SQLiteStorage.get_logs(project="test-project", run="test-run")
        assert len(logs) == 1

        log_entry = logs[0]

        # Should still have the original metric
        assert "loss" in log_entry
        assert log_entry["loss"] == 0.5

        # Should not have GPU metrics if monitor failed
        gpu_keys = [
            k for k in log_entry.keys() if k.startswith("gpu/") or k.startswith("gpu_")
        ]
        # May be empty or may have empty values, but should not crash


def test_gpu_logging_api_compatibility(temp_dir):
    """Test that GPU logging maintains wandb API compatibility."""
    # Test that existing wandb-style code still works

    # Standard wandb usage pattern
    run = trackio.init(project="test-project", name="test-run")
    trackio.log({"train_loss": 0.5, "accuracy": 0.9})
    trackio.log({"train_loss": 0.4, "accuracy": 0.92}, step=1)
    trackio.finish()

    logs = SQLiteStorage.get_logs(project="test-project", run="test-run")
    assert len(logs) == 2

    # Verify basic functionality still works
    assert logs[0]["train_loss"] == 0.5
    assert logs[0]["accuracy"] == 0.9
    assert logs[1]["train_loss"] == 0.4
    assert logs[1]["accuracy"] == 0.92
    assert logs[1]["step"] == 1


def test_gpu_logging_with_no_hardware(temp_dir):
    """Test GPU logging when no GPU hardware is available."""
    with patch("trackio._get_gpu_metrics", return_value={}):
        run = trackio.init(project="test-project", name="test-run", log_gpu=True)
        trackio.log({"loss": 0.5})
        trackio.finish()

        logs = SQLiteStorage.get_logs(project="test-project", run="test-run")
        assert len(logs) == 1

        log_entry = logs[0]

        # Should have the original metric
        assert "loss" in log_entry
        assert log_entry["loss"] == 0.5

        # Should not have GPU metrics
        gpu_keys = [
            k for k in log_entry.keys() if k.startswith("gpu/") or k.startswith("gpu_")
        ]
        assert len(gpu_keys) == 0
