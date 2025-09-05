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
        """Test that top-level infinity values are properly sanitized for JSON serialization."""
        test_data = {
            "positive_inf": float("inf"),
            "negative_inf": float("-inf"),
            "nan_value": float("nan"),
            "normal_value": 42.0,
            "string_value": "test",
            "none_value": None,
            "dict_value": {"nested": "data"},  # Should be left unchanged
        }

        sanitized = sanitize_infinity_values(test_data)

        assert sanitized["positive_inf"] == "Infinity"
        assert sanitized["negative_inf"] == "-Infinity"
        assert sanitized["nan_value"] == "NaN"
        assert sanitized["normal_value"] == 42.0
        assert sanitized["string_value"] == "test"
        assert sanitized["none_value"] is None
        assert sanitized["dict_value"] == {"nested": "data"}  # Unchanged

    def test_deserialize_infinity_values(self):
        """Test that sanitized infinity values are properly deserialized back to numeric forms."""
        test_data = {
            "positive_inf": "Infinity",
            "negative_inf": "-Infinity",
            "nan_value": "NaN",
            "normal_value": 42.0,
            "string_value": "test",
            "none_value": None,
            "dict_value": {"nested": "data"},  # Should be left unchanged
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
        assert deserialized["string_value"] == "test"
        assert deserialized["none_value"] is None
        assert deserialized["dict_value"] == {"nested": "data"}  # Unchanged

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
                    # Note: json.dumps() produces unquoted Infinity/-Infinity/NaN for backward compatibility
                    # but our sanitization converts them to quoted strings
                    assert "Infinity" in raw_metrics
                    assert "-Infinity" in raw_metrics
                    assert "NaN" in raw_metrics

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
            "np_normal": np.float64(3.14),
        }

        sanitized = sanitize_infinity_values(test_data)

        assert sanitized["np_inf"] == "Infinity"
        assert sanitized["np_neg_inf"] == "-Infinity"
        assert sanitized["np_nan"] == "NaN"
        assert isinstance(sanitized["np_normal"], (int, float))
        assert abs(sanitized["np_normal"] - 3.14) < 1e-10
