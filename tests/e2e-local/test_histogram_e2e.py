import numpy as np

import trackio
from trackio.sqlite_storage import SQLiteStorage


def test_histogram_with_trackio_log(temp_dir):
    """Test logging histograms with trackio."""
    run = trackio.init(project="test_histogram")

    data1 = np.random.randn(1000)
    data2 = np.random.exponential(2, 500)

    trackio.log(
        {
            "normal_dist": trackio.Histogram(data1),
            "exp_dist": trackio.Histogram(data2, num_bins=30),
        }
    )

    hist, bins = np.histogram(data1, bins=25)
    trackio.log({"precomputed": trackio.Histogram(np_histogram=(hist, bins))})

    trackio.finish()

    logs = SQLiteStorage.get_logs("test_histogram", run.name)

    assert len(logs) == 2

    assert "normal_dist" in logs[0]
    assert logs[0]["normal_dist"]["_type"] == "trackio.histogram"
    assert len(logs[0]["normal_dist"]["bins"]) == 65
    assert len(logs[0]["normal_dist"]["values"]) == 64

    assert "exp_dist" in logs[0]
    assert logs[0]["exp_dist"]["_type"] == "trackio.histogram"
    assert len(logs[0]["exp_dist"]["bins"]) == 31
    assert len(logs[0]["exp_dist"]["values"]) == 30

    assert "precomputed" in logs[1]
    assert logs[1]["precomputed"]["_type"] == "trackio.histogram"
    assert len(logs[1]["precomputed"]["bins"]) == 26
    assert len(logs[1]["precomputed"]["values"]) == 25
