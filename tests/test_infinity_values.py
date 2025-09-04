import math
import sqlite3
import tempfile
from pathlib import Path

import pytest

from trackio.sqlite_storage import SQLiteStorage
from trackio.utils import deserialize_infinity_values, sanitize_infinity_values


class TestInfinityValues:
    """Test suite for infinity and NaN value handling in trackio."""

    def test_sanitize_infinity_values(self):
        """Test that infinity values are properly sanitized for JSON serialization."""
        test_data = {
            "positive_inf": float("inf"),
            "negative_inf": float("-inf"),
            "nan_value": float("nan"),
            "normal_value": 42.0,
            "nested": {
                "inf_in_nested": float("inf"),
                "list_with_inf": [1.0, float("inf"), float("-inf"), float("nan")],
            },
        }

        sanitized = sanitize_infinity_values(test_data)

        assert sanitized["positive_inf"] == "Infinity"
        assert sanitized["negative_inf"] == "-Infinity"
        assert sanitized["nan_value"] == "NaN"
        assert sanitized["normal_value"] == 42.0
        assert sanitized["nested"]["inf_in_nested"] == "Infinity"
        assert sanitized["nested"]["list_with_inf"] == [
            1.0,
            "Infinity",
            "-Infinity",
            "NaN",
        ]

    def test_deserialize_infinity_values(self):
        """Test that sanitized infinity values are properly deserialized back to numeric forms."""
        test_data = {
            "positive_inf": "Infinity",
            "negative_inf": "-Infinity",
            "nan_value": "NaN",
            "normal_value": 42.0,
            "nested": {
                "inf_in_nested": "Infinity",
                "list_with_inf": [1.0, "Infinity", "-Infinity", "NaN"],
            },
        }

        deserialized = deserialize_infinity_values(test_data)

        assert (
            math.isinf(deserialized["positive_inf"])
            and deserialized["positive_inf"] > 0
        )
        assert (
            math.isinf(deserialized["negative_inf"])
            and deserialized["negative_inf"] < 0
        )
        assert math.isnan(deserialized["nan_value"])
        assert deserialized["normal_value"] == 42.0
        assert math.isinf(deserialized["nested"]["inf_in_nested"])
        assert math.isinf(deserialized["nested"]["list_with_inf"][1])
        assert math.isinf(deserialized["nested"]["list_with_inf"][2])
        assert math.isnan(deserialized["nested"]["list_with_inf"][3])

    def test_roundtrip_serialization(self):
        """Test that values can be sanitized and then deserialized correctly."""
        original_data = {
            "inf": float("inf"),
            "neg_inf": float("-inf"),
            "nan": float("nan"),
            "normal": 123.45,
        }

        sanitized = sanitize_infinity_values(original_data)
        deserialized = deserialize_infinity_values(sanitized)

        assert math.isinf(deserialized["inf"]) and deserialized["inf"] > 0
        assert math.isinf(deserialized["neg_inf"]) and deserialized["neg_inf"] < 0
        assert math.isnan(deserialized["nan"])
        assert deserialized["normal"] == 123.45

    def test_sqlite_storage_with_infinity_values(self):
        """Test that SQLite storage properly handles infinity values."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Override the TRACKIO_DIR for this test
            original_trackio_dir = SQLiteStorage.get_project_db_path("test_project")
            test_db_path = Path(temp_dir) / "test_project.db"

            # Mock the get_project_db_path method
            original_method = SQLiteStorage.get_project_db_path
            SQLiteStorage.get_project_db_path = lambda project: test_db_path

            try:
                # Initialize database
                SQLiteStorage.init_db("test_project")

                # Log data with infinity values
                test_metrics = {
                    "loss": float("inf"),
                    "accuracy": float("-inf"),
                    "f1_score": float("nan"),
                    "normal_metric": 0.95,
                }

                SQLiteStorage.log("test_project", "test_run", test_metrics, step=0)

                # Retrieve the logged data
                logs = SQLiteStorage.get_logs("test_project", "test_run")

                assert len(logs) == 1
                log = logs[0]

                # Check that infinity values were properly deserialized
                assert math.isinf(log["loss"]) and log["loss"] > 0
                assert math.isinf(log["accuracy"]) and log["accuracy"] < 0
                assert math.isnan(log["f1_score"])
                assert log["normal_metric"] == 0.95

                # Verify that the data in the database is stored as sanitized strings
                with sqlite3.connect(test_db_path) as conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        "SELECT metrics FROM metrics WHERE run_name = ?", ("test_run",)
                    )
                    raw_metrics = cursor.fetchone()[0]

                    # The raw JSON should contain sanitized string representations
                    assert '"Infinity"' in raw_metrics
                    assert '"-Infinity"' in raw_metrics
                    assert '"NaN"' in raw_metrics

            finally:
                # Restore original method
                SQLiteStorage.get_project_db_path = original_method

    def test_numpy_float_infinity_values(self):
        """Test that numpy float infinity values are properly handled."""
        import numpy as np

        test_data = {
            "np_inf": np.float64("inf"),
            "np_neg_inf": np.float64("-inf"),
            "np_nan": np.float64("nan"),
        }

        sanitized = sanitize_infinity_values(test_data)

        assert sanitized["np_inf"] == "Infinity"
        assert sanitized["np_neg_inf"] == "-Infinity"
        assert sanitized["np_nan"] == "NaN"
