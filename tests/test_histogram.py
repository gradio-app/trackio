import json

import numpy as np
import pytest

import trackio
from trackio.histogram import Histogram


def test_histogram_from_sequence():
    """Test creating histogram from a sequence of values."""
    data = [1, 2, 3, 4, 5, 5, 5, 6, 7, 8, 8, 9]
    hist = Histogram(data)

    assert hist.bins is not None
    assert hist.histogram is not None
    assert len(hist.bins) == 65  # 64 bins + 1 for edge
    assert len(hist.histogram) == 64
    assert sum(hist.histogram) == len(data)


def test_histogram_from_numpy_array():
    """Test creating histogram from numpy array."""
    data = np.random.randn(1000)
    hist = Histogram(data)

    assert hist.bins is not None
    assert hist.histogram is not None
    assert len(hist.bins) == 65
    assert len(hist.histogram) == 64
    assert sum(hist.histogram) == 1000


def test_histogram_from_np_histogram():
    """Test creating histogram from pre-computed numpy histogram."""
    data = np.random.randn(500)
    np_hist, np_bins = np.histogram(data, bins=30)

    hist = Histogram(np_histogram=(np_hist, np_bins))

    assert np.array_equal(hist.bins, np_bins)
    assert np.array_equal(hist.histogram, np_hist)
    assert len(hist.bins) == 31
    assert len(hist.histogram) == 30


def test_histogram_custom_bins():
    """Test creating histogram with custom number of bins."""
    data = np.random.randn(200)
    hist = Histogram(data, num_bins=20)

    assert len(hist.bins) == 21
    assert len(hist.histogram) == 20
    assert sum(hist.histogram) == 200


def test_histogram_max_bins():
    """Test that histogram respects maximum bin limit."""
    data = np.random.randn(100)
    hist = Histogram(data, num_bins=1000)  # Request more than max

    assert len(hist.bins) == 513  # Capped at 512 bins
    assert len(hist.histogram) == 512


def test_histogram_handles_nan_inf():
    """Test that histogram handles NaN and inf values correctly."""
    data = [1, 2, float("nan"), 3, float("inf"), 4, float("-inf"), 5]
    hist = Histogram(data)

    # Only finite values should be included
    assert sum(hist.histogram) == 5  # Only 1, 2, 3, 4, 5


def test_histogram_empty_after_filtering():
    """Test histogram with only NaN/inf values."""
    data = [float("nan"), float("inf"), float("-inf")]
    hist = Histogram(data)

    assert len(hist.histogram) == 0
    assert len(hist.bins) == 0


def test_histogram_to_dict():
    """Test histogram serialization to dictionary."""
    data = np.random.randn(100)
    hist = Histogram(data, num_bins=10)

    hist_dict = hist._to_dict()

    assert hist_dict["_type"] == "trackio.histogram"
    assert "bins" in hist_dict
    assert "values" in hist_dict
    assert isinstance(hist_dict["bins"], list)
    assert isinstance(hist_dict["values"], list)
    assert len(hist_dict["bins"]) == 11
    assert len(hist_dict["values"]) == 10


def test_histogram_invalid_inputs():
    """Test histogram with invalid inputs."""
    # No input provided
    with pytest.raises(
        ValueError, match="Must provide either sequence or np_histogram"
    ):
        Histogram()

    # Both inputs provided
    with pytest.raises(
        ValueError, match="Cannot provide both sequence and np_histogram"
    ):
        Histogram([1, 2, 3], np_histogram=([1, 2], [0, 1, 2]))


def test_histogram_with_trackio_log(temp_dir):
    """Test logging histograms with trackio."""
    run = trackio.init(project="test_histogram")

    # Create histogram from different sources
    data1 = np.random.randn(1000)
    data2 = np.random.exponential(2, 500)

    trackio.log(
        {
            "normal_dist": trackio.Histogram(data1),
            "exp_dist": trackio.Histogram(data2, num_bins=30),
        }
    )

    # Log pre-computed histogram
    hist, bins = np.histogram(data1, bins=25)
    trackio.log({"precomputed": trackio.Histogram(np_histogram=(hist, bins))})

    trackio.finish()

    # Verify the data was logged correctly
    from trackio.sqlite_storage import SQLiteStorage

    logs = SQLiteStorage.get_logs("test_histogram", run.name)

    assert len(logs) == 2

    # Check first log
    assert "normal_dist" in logs[0]
    assert logs[0]["normal_dist"]["_type"] == "trackio.histogram"
    assert len(logs[0]["normal_dist"]["bins"]) == 65
    assert len(logs[0]["normal_dist"]["values"]) == 64

    assert "exp_dist" in logs[0]
    assert logs[0]["exp_dist"]["_type"] == "trackio.histogram"
    assert len(logs[0]["exp_dist"]["bins"]) == 31
    assert len(logs[0]["exp_dist"]["values"]) == 30

    # Check second log
    assert "precomputed" in logs[1]
    assert logs[1]["precomputed"]["_type"] == "trackio.histogram"
    assert len(logs[1]["precomputed"]["bins"]) == 26
    assert len(logs[1]["precomputed"]["values"]) == 25
