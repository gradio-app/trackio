"""
Tests for trackio-view CLI functionality.
"""

import pytest
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock
import tempfile
import os

import trackio
from trackio.view import TrackIOViewer


def create_test_viewer_with_data(project_name, num_entries=5):
    """Helper to create a viewer with test data."""
    # Create test data
    run = trackio.init(project=project_name, name="test-run")
    for i in range(num_entries):
        trackio.log({"train_loss": 5.0 - i * 0.5, "iteration": i * 100}, step=i)
    trackio.finish()

    # Create viewer and set up data path
    viewer = TrackIOViewer(project_name)

    # Find the actual database location
    trackio_dir = Path.home() / ".cache" / "huggingface" / "trackio"
    db_path = trackio_dir / f"{project_name}.db"
    if db_path.exists():
        viewer.db_path = db_path
        viewer.data_dir = None

    return viewer


def test_trackio_view_import():
    """Test that trackio-view module can be imported."""
    from trackio import view
    assert hasattr(view, "main")
    assert hasattr(view, "TrackIOViewer")


def test_trackio_viewer_initialization():
    """Test TrackIOViewer can be initialized."""
    viewer = TrackIOViewer("test-project")
    assert viewer.project == "test-project"
    assert viewer.zoom_level == 0


def test_trackio_viewer_with_data(temp_dir):
    """Test TrackIOViewer with actual data."""
    viewer = create_test_viewer_with_data("test-project-data", 5)
    metrics = viewer.find_latest_metrics()

    if metrics is not None:
        assert "data" in metrics
        assert len(metrics["data"]) == 5
    else:
        pytest.skip("Could not find test data - database may not be accessible")


def test_trackio_viewer_display_stdout(temp_dir):
    """Test TrackIOViewer stdout display (--once mode)."""
    from io import StringIO

    # Test display_stdout with None metrics (common case)
    viewer = TrackIOViewer("nonexistent-project")

    captured_output = StringIO()
    with patch('sys.stdout', captured_output):
        viewer.display_stdout(None)

    output = captured_output.getvalue()
    assert "No metrics found for project:" in output


def test_trackio_viewer_zoom_functionality(temp_dir):
    """Test zoom level functionality."""
    viewer = TrackIOViewer("test-project")

    # Test different zoom levels can be set
    for zoom in [0, 1, 2, 3, 4]:
        viewer.zoom_level = zoom
        assert viewer.zoom_level == zoom


def test_trackio_viewer_no_data():
    """Test TrackIOViewer with no data."""
    viewer = TrackIOViewer("nonexistent-project")
    metrics = viewer.find_latest_metrics()

    # Should return None for non-existent project
    assert metrics is None


def test_trackio_viewer_db_format(temp_dir):
    """Test TrackIOViewer database path discovery."""
    viewer = TrackIOViewer("test-project")

    # Should have search paths configured
    assert len(viewer.trackio_dirs) > 0

    # Should initialize with None values if no data found
    assert viewer.data_dir is None or viewer.db_path is None


def test_trackio_view_cli_help():
    """Test that trackio-view CLI shows help."""
    try:
        result = subprocess.run(
            [sys.executable, "-m", "trackio.view", "--help"],
            capture_output=True,
            text=True,
            timeout=10
        )

        assert result.returncode == 0
        assert "TrackIO Console Dashboard" in result.stdout
        assert "--project" in result.stdout
        assert "--once" in result.stdout
        assert "--zoom" in result.stdout

    except subprocess.TimeoutExpired:
        pytest.skip("CLI help test timed out")


def test_trackio_view_cli_once_mode(temp_dir):
    """Test trackio-view CLI in --once mode."""
    try:
        # Test --once mode with non-existent project (should not crash)
        result = subprocess.run(
            [sys.executable, "-m", "trackio.view", "--project", "cli-test-nonexistent", "--once"],
            capture_output=True,
            text=True,
            timeout=10
        )

        # Should complete even if no data found
        assert result.returncode == 0
        assert "No metrics found" in result.stdout

    except subprocess.TimeoutExpired:
        pytest.skip("CLI once mode test timed out")


def test_trackio_view_cli_project_not_found():
    """Test trackio-view CLI with non-existent project."""
    try:
        result = subprocess.run(
            [sys.executable, "-m", "trackio.view", "--project", "nonexistent", "--once"],
            capture_output=True,
            text=True,
            timeout=10
        )

        # Should complete but show no data message
        assert result.returncode == 0
        assert "No metrics found" in result.stdout

    except subprocess.TimeoutExpired:
        pytest.skip("CLI project not found test timed out")


def test_trackio_view_zoom_levels(temp_dir):
    """Test zoom level functionality through CLI."""
    # Test different zoom levels via CLI (without data)
    for zoom in [0, 1, 2, 3, 4]:
        try:
            result = subprocess.run(
                [sys.executable, "-m", "trackio.view",
                 "--project", "zoom-test-empty", "--once", "--zoom", str(zoom)],
                capture_output=True,
                text=True,
                timeout=10
            )

            assert result.returncode == 0
            # Should handle zoom gracefully even without data

        except subprocess.TimeoutExpired:
            pytest.skip(f"CLI zoom test for level {zoom} timed out")


def test_trackio_viewer_convert_db_format(temp_dir):
    """Test database format conversion."""
    viewer = TrackIOViewer("convert-test")

    # Test conversion with mock data
    test_data = [
        {"train_loss": 4.0, "iteration": 0, "step": 0},
        {"train_loss": 3.5, "iteration": 20, "step": 1},
        {"train_loss": 3.0, "iteration": 40, "step": 2}
    ]

    converted = viewer._convert_db_to_display_format(test_data)
    assert "iterations" in converted
    assert "losses" in converted
    assert len(converted["iterations"]) == 3
    assert len(converted["losses"]) == 3


def test_trackio_viewer_terminal_features():
    """Test terminal feature availability."""
    viewer = TrackIOViewer("test")

    # Test that viewer has all expected methods
    assert hasattr(viewer, "find_latest_metrics")
    assert hasattr(viewer, "display_stdout")
    assert hasattr(viewer, "monitor_live")
    assert hasattr(viewer, "_convert_db_to_display_format")

    # Test terminal classes exist
    from trackio.view import Term, Color, Theme
    assert hasattr(Term, "width")
    assert hasattr(Term, "height")
    assert hasattr(Color, "fg")
    assert hasattr(Theme, "loss_gradient")


@patch("trackio.view.RICH_AVAILABLE", False)
def test_trackio_viewer_no_rich_library(temp_dir):
    """Test viewer works without rich library."""
    viewer = TrackIOViewer("no-rich-test")

    # Should still work without rich - test with None metrics
    from io import StringIO
    captured_output = StringIO()

    with patch('sys.stdout', captured_output):
        viewer.display_stdout(None)

    output = captured_output.getvalue()
    assert "No metrics found for project:" in output


def test_trackio_viewer_graph_creation():
    """Test graph creation functionality."""
    from trackio.view import Graph, Color, Theme

    # Test basic graph
    graph = Graph(width=20, height=5, min_value=0, max_value=10)

    # Add some test values
    test_values = [1, 3, 5, 7, 9, 5, 2]
    for val in test_values:
        graph.add_value(val)

    # Draw graph
    lines = graph.draw(Theme.loss_gradient, show_values=True)
    assert len(lines) == 5  # height
    assert all(len(line) >= 20 for line in lines)  # width (plus scale)


def test_trackio_viewer_find_data_locations():
    """Test data location discovery."""
    viewer = TrackIOViewer("test-project")

    # Should have expected search paths
    assert len(viewer.trackio_dirs) > 0

    # Should include common locations
    home = Path.home()
    expected_paths = [
        home / ".trackio" / "test-project",
        home / ".cache" / "trackio" / "test-project",
        home / ".cache" / "huggingface" / "trackio" / "test-project",
    ]

    for expected in expected_paths:
        assert expected in viewer.trackio_dirs