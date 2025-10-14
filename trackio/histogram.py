from typing import Any

import numpy as np


class Histogram:
    """
    Histogram data type for Trackio, compatible with wandb.Histogram.

    Example:
        ```python
        import trackio
        import numpy as np

        # Create histogram from sequence
        data = np.random.randn(1000)
        trackio.log({"distribution": trackio.Histogram(data)})

        # Create histogram from numpy histogram
        hist, bins = np.histogram(data, bins=30)
        trackio.log({"distribution": trackio.Histogram(np_histogram=(hist, bins))})

        # Specify custom number of bins
        trackio.log({"distribution": trackio.Histogram(data, num_bins=50)})
        ```

    Args:
        sequence: Optional sequence of values to create histogram from
        np_histogram: Optional pre-computed numpy histogram (hist, bins) tuple
        num_bins: Number of bins for the histogram (default 64, max 512)
    """

    TYPE = "trackio.histogram"

    def __init__(
        self,
        sequence: Any = None,
        np_histogram: tuple | None = None,
        num_bins: int = 64,
    ):
        if sequence is None and np_histogram is None:
            raise ValueError("Must provide either sequence or np_histogram")

        if sequence is not None and np_histogram is not None:
            raise ValueError("Cannot provide both sequence and np_histogram")

        num_bins = min(num_bins, 512)

        if np_histogram is not None:
            self.histogram, self.bins = np_histogram
            self.histogram = np.asarray(self.histogram)
            self.bins = np.asarray(self.bins)
        else:
            data = np.asarray(sequence).flatten()
            data = data[np.isfinite(data)]
            if len(data) == 0:
                self.histogram = np.array([])
                self.bins = np.array([])
            else:
                self.histogram, self.bins = np.histogram(data, bins=num_bins)

    def _to_dict(self) -> dict:
        """Convert histogram to dictionary for storage."""
        return {
            "_type": self.TYPE,
            "bins": self.bins.tolist(),
            "values": self.histogram.tolist(),
        }
