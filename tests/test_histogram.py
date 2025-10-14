import numpy as np
import pytest

from trackio.histogram import Histogram


def test_histogram_from_sequence():
    """Test creating histogram from a sequence of values."""
    data = [1, 2, 3, 4, 5, 5, 5, 6, 7, 8, 8, 9]
    hist = Histogram(data)

    assert hist.bins is not None
    assert hist.histogram is not None
    assert len(hist.bins) == 65
    assert len(hist.histogram) == 64
    assert sum(hist.histogram) == len(data)


def test_histogram_from_np_histogram():
    """Test creating histogram from pre-computed numpy histogram."""
    data = np.random.randn(500)
    np_hist, np_bins = np.histogram(data, bins=30)

    hist = Histogram(np_histogram=(np_hist, np_bins))

    assert np.array_equal(hist.bins, np_bins)
    assert np.array_equal(hist.histogram, np_hist)
    assert len(hist.bins) == 31
    assert len(hist.histogram) == 30


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
    with pytest.raises(
        ValueError, match="Must provide either sequence or np_histogram"
    ):
        Histogram()

    with pytest.raises(
        ValueError, match="Cannot provide both sequence and np_histogram"
    ):
        Histogram([1, 2, 3], np_histogram=([1, 2], [0, 1, 2]))
