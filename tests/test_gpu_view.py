"""
Tests for GPU database viewing functionality in TrackIO View.
"""

import pytest
from unittest.mock import patch, MagicMock
from io import StringIO
import sys

import trackio
from trackio.view import TrackIOViewer
from trackio.sqlite_storage import SQLiteStorage


def create_test_gpu_data(temp_dir):
    """Create test data with GPU metrics for testing."""
    from pathlib import Path

    # Create a project with GPU logging
    run = trackio.init(project="gpu-test", name="gpu-run", log_gpu=True)

    # Mock GPU metrics data
    gpu_metrics = {
        "gpu/utilization": 95.0,
        "gpu/memory_used_gb": 15.2,
        "gpu/memory_percent": 63.3,
        "gpu/temperature_c": 78,
        "gpu/power_w": 285,
        "gpu/power_limit_w": 350,
        "gpu/fan_speed": 70,
        "gpu/fan_rpm": 2200,
        "gpu/clock_graphics_mhz": 1900,
        "gpu/clock_memory_mhz": 1100,
        "gpu/clock_fclk_mhz": 1650,
        "gpu/clock_socclk_mhz": 1250,
        "gpu/perf_state": "P0",
    }

    # Log several entries with varying metrics
    for i in range(5):
        base_metrics = {
            "loss": 5.0 - i * 0.8,
            "learning_rate": 1e-4,
            "iteration": i * 100,
        }

        # Vary GPU metrics slightly
        current_gpu_metrics = gpu_metrics.copy()
        current_gpu_metrics["gpu/utilization"] = 95.0 + i  # 95, 96, 97, 98, 99
        current_gpu_metrics["gpu/temperature_c"] = 78 + i  # 78, 79, 80, 81, 82

        # Combine training and GPU metrics
        all_metrics = {**base_metrics, **current_gpu_metrics}

        # Mock the GPU monitor to return our test data
        with patch("trackio._get_gpu_metrics", return_value=current_gpu_metrics):
            trackio.log(all_metrics, step=i)

    trackio.finish()

    # Return both project name and the temp_dir path for the database
    return "gpu-test", Path(temp_dir)


def create_test_viewer(project_name, temp_path):
    """Create a TrackIOViewer configured for test temp directory."""
    viewer = TrackIOViewer(project_name)
    # Override the trackio_dirs to point to our temp directory
    viewer.trackio_dirs = [temp_path / f"{project_name}.db"]
    viewer.data_dir = None
    viewer.db_path = temp_path / f"{project_name}.db"
    return viewer


def test_gpu_db_viewer_initialization(temp_dir):
    """Test that TrackIOViewer can be initialized for GPU database viewing."""
    project_name, temp_path = create_test_gpu_data(temp_dir)

    viewer = create_test_viewer(project_name, temp_path)
    assert viewer.project == project_name


def test_gpu_db_viewer_finds_metrics(temp_dir):
    """Test that the viewer can find GPU metrics in the database."""
    project_name, temp_path = create_test_gpu_data(temp_dir)

    viewer = create_test_viewer(project_name, temp_path)
    metrics = viewer.find_latest_metrics()

    assert metrics is not None
    assert "data" in metrics
    assert len(metrics["data"]) == 5  # 5 log entries

    # Check that GPU metrics are present in at least one entry
    gpu_found = False
    for entry in metrics["data"]:
        gpu_keys = [k for k in entry.keys() if k.startswith("gpu/")]
        if gpu_keys:
            gpu_found = True
            break

    assert gpu_found, "No GPU metrics found in database"


def test_gpu_db_display_output(temp_dir):
    """Test that GPU database display produces expected output."""
    project_name = create_test_gpu_data(temp_dir)

    viewer = TrackIOViewer(project_name)
    metrics = viewer.find_latest_metrics()

    # Capture stdout
    captured_output = StringIO()
    sys.stdout = captured_output

    try:
        viewer.display_gpu_metrics_from_db(metrics)
        output = captured_output.getvalue()

        # Check for expected content in output
        assert "GPU Metrics from Database" in output
        assert project_name in output
        assert "GPU Utilization:" in output
        assert "Memory Usage:" in output
        assert "Temperature:" in output
        assert "Power:" in output
        assert "Clock Frequencies:" in output
        assert "Graphics:" in output
        assert "Memory:" in output
        assert "Historical Data" in output
        assert "Available GPU Metrics:" in output

    finally:
        sys.stdout = sys.__stdout__


def test_gpu_db_display_no_data(temp_dir):
    """Test GPU database display when no data is available."""
    viewer = TrackIOViewer("nonexistent-project")

    # Capture stdout
    captured_output = StringIO()
    sys.stdout = captured_output

    try:
        viewer.display_gpu_metrics_from_db({})
        output = captured_output.getvalue()

        assert "No GPU metrics found" in output

    finally:
        sys.stdout = sys.__stdout__


def test_gpu_db_display_no_gpu_metrics(temp_dir):
    """Test GPU database display when no GPU metrics in data."""
    # Create project without GPU metrics
    run = trackio.init(project="no-gpu-test", name="no-gpu-run")
    trackio.log({"loss": 0.5})
    trackio.finish()

    viewer = TrackIOViewer("no-gpu-test")
    metrics = viewer.find_latest_metrics()

    # Capture stdout
    captured_output = StringIO()
    sys.stdout = captured_output

    try:
        viewer.display_gpu_metrics_from_db(metrics)
        output = captured_output.getvalue()

        assert "No GPU metrics found in database" in output

    finally:
        sys.stdout = sys.__stdout__


def test_gpu_db_historical_analysis(temp_dir):
    """Test that historical GPU analysis works correctly."""
    project_name = create_test_gpu_data(temp_dir)

    viewer = TrackIOViewer(project_name)
    metrics = viewer.find_latest_metrics()

    # Extract GPU data like the display function does
    data = metrics["data"]
    gpu_data = {}

    for entry in data:
        for key, value in entry.items():
            if key.startswith("gpu/"):
                if key not in gpu_data:
                    gpu_data[key] = []
                gpu_data[key].append(
                    {
                        "step": entry.get("step", 0),
                        "timestamp": entry.get("timestamp", ""),
                        "value": value,
                    }
                )

    # Check that we have the expected metrics
    assert "gpu/utilization" in gpu_data
    assert "gpu/temperature_c" in gpu_data
    assert len(gpu_data["gpu/utilization"]) == 5

    # Check that values are in expected ranges (from our test data)
    utils = [d["value"] for d in gpu_data["gpu/utilization"]]
    assert min(utils) >= 95.0
    assert max(utils) <= 99.0

    temps = [d["value"] for d in gpu_data["gpu/temperature_c"]]
    assert min(temps) >= 78
    assert max(temps) <= 82


def test_gpu_db_clock_frequency_parsing(temp_dir):
    """Test that clock frequency metrics are properly parsed."""
    project_name = create_test_gpu_data(temp_dir)

    viewer = TrackIOViewer(project_name)
    metrics = viewer.find_latest_metrics()

    data = metrics["data"]
    gpu_data = {}

    for entry in data:
        for key, value in entry.items():
            if key.startswith("gpu/") and "clock_" in key:
                if key not in gpu_data:
                    gpu_data[key] = []
                gpu_data[key].append(value)

    # Check that all expected clock frequencies are present
    expected_clocks = [
        "gpu/clock_graphics_mhz",
        "gpu/clock_memory_mhz",
        "gpu/clock_fclk_mhz",
        "gpu/clock_socclk_mhz",
    ]

    for clock in expected_clocks:
        assert clock in gpu_data, f"Clock frequency {clock} not found"
        assert len(gpu_data[clock]) == 5  # 5 entries


def test_gpu_db_multi_gpu_handling(temp_dir):
    """Test GPU database handling with multiple GPUs."""
    # Create a project with multi-GPU metrics
    run = trackio.init(project="multi-gpu-test", name="multi-gpu-run", log_gpu=True)

    # Mock multi-GPU metrics
    multi_gpu_metrics = {
        "gpu_0/utilization": 95.0,
        "gpu_0/temperature_c": 75,
        "gpu_1/utilization": 88.0,
        "gpu_1/temperature_c": 72,
    }

    with patch("trackio._get_gpu_metrics", return_value=multi_gpu_metrics):
        trackio.log({"loss": 0.5, **multi_gpu_metrics})

    trackio.finish()

    viewer = TrackIOViewer("multi-gpu-test")
    metrics = viewer.find_latest_metrics()

    # Capture stdout
    captured_output = StringIO()
    sys.stdout = captured_output

    try:
        viewer.display_gpu_metrics_from_db(metrics)
        output = captured_output.getvalue()

        # Should handle multi-GPU metrics gracefully
        # The display function should show available metrics
        assert "Available GPU Metrics:" in output

    finally:
        sys.stdout = sys.__stdout__


def test_gpu_db_viewer_with_zoom(temp_dir):
    """Test that zoom levels work with GPU database viewer."""
    project_name = create_test_gpu_data(temp_dir)

    viewer = TrackIOViewer(project_name)

    # Test different zoom levels
    for zoom_level in [0, 1, 2, 3, 4]:
        viewer.zoom_level = zoom_level
        metrics = viewer.find_latest_metrics()

        # Should not crash with any zoom level
        assert metrics is not None


@patch("select.select")
@patch("trackio.view.termios")
@patch("trackio.view.tty")
def test_gpu_db_live_monitoring_setup(mock_tty, mock_termios, mock_select, temp_dir):
    """Test that GPU database live monitoring can be set up."""
    project_name = create_test_gpu_data(temp_dir)

    viewer = TrackIOViewer(project_name)

    # Mock terminal setup
    mock_termios.tcgetattr.return_value = "mock_settings"
    mock_select.return_value = ([], [], [])  # No input available

    # Test that monitor setup doesn't crash
    # We can't easily test the full loop without complex mocking
    assert hasattr(viewer, "monitor_gpu_db_live")


def test_gpu_db_edge_cases(temp_dir):
    """Test edge cases in GPU database viewing."""
    # Test with empty project
    viewer = TrackIOViewer("empty-project")
    metrics = viewer.find_latest_metrics()

    captured_output = StringIO()
    sys.stdout = captured_output

    try:
        viewer.display_gpu_metrics_from_db(metrics)
        output = captured_output.getvalue()
        assert "No GPU metrics found" in output
    finally:
        sys.stdout = sys.__stdout__

    # Test with malformed data
    malformed_metrics = {"data": [{"invalid": "data"}]}

    captured_output = StringIO()
    sys.stdout = captured_output

    try:
        viewer.display_gpu_metrics_from_db(malformed_metrics)
        output = captured_output.getvalue()
        assert "No GPU metrics found in database" in output
    finally:
        sys.stdout = sys.__stdout__
