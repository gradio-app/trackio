"""End-to-end test for Table with TrackioImage functionality."""

import pandas as pd
import pytest

import trackio
from trackio.media import TrackioImage
from trackio.sqlite_storage import SQLiteStorage
from trackio.table import Table

PROJECT_NAME = "test_table_images"


def test_table_with_images_e2e(image_ndarray, temp_dir):
    """Test complete workflow of logging a table with images."""
    # Initialize trackio
    run = trackio.init(project=PROJECT_NAME, name="test_run")

    # Create a table with images
    img1 = TrackioImage(image_ndarray, caption="Sample Image 1")
    img2 = TrackioImage(image_ndarray, caption="Sample Image 2")

    df = pd.DataFrame(
        {
            "step": [1, 2],
            "image": [img1, img2],
            "accuracy": [0.85, 0.92],
            "description": ["first test", "second test"],
        }
    )

    table = Table(dataframe=df)

    # Log the table
    trackio.log({"experiment_results": table})

    # Finish the run
    trackio.finish()

    # Verify the data was stored correctly
    stored_data = SQLiteStorage.get_all_metrics(PROJECT_NAME, "test_run")

    assert "experiment_results" in stored_data

    # Get the stored table data
    table_entry = None
    for entry in stored_data["experiment_results"]:
        if (
            isinstance(entry["value"], dict)
            and entry["value"].get("_type") == Table.TYPE
        ):
            table_entry = entry
            break

    assert table_entry is not None, "Table entry not found in stored data"

    stored_table = table_entry["value"]
    assert stored_table["_type"] == Table.TYPE
    assert len(stored_table["_value"]) == 2

    # Verify the table data structure
    for i, row in enumerate(stored_table["_value"]):
        assert row["step"] == i + 1
        assert row["accuracy"] == [0.85, 0.92][i]
        assert row["description"] == ["first test", "second test"][i]

        # Verify image was serialized correctly
        assert isinstance(row["image"], dict)
        assert row["image"]["_type"] == TrackioImage.TYPE
        assert "file_path" in row["image"]
        assert row["image"]["caption"] == f"Sample Image {i + 1}"


def test_table_mixed_media_and_regular_data(image_ndarray, temp_dir):
    """Test table with some rows having images and others not."""
    run = trackio.init(project=PROJECT_NAME, name="mixed_test")

    img = TrackioImage(image_ndarray, caption="Only Image")

    df = pd.DataFrame(
        {
            "experiment": ["exp1", "exp2", "exp3"],
            "result_image": [img, None, img],  # Some rows have images, some don't
            "score": [0.75, 0.80, 0.85],
        }
    )

    table = Table(dataframe=df)
    trackio.log({"mixed_results": table})
    trackio.finish()

    # Verify storage
    stored_data = SQLiteStorage.get_all_metrics(PROJECT_NAME, "mixed_test")
    table_data = None

    for entry in stored_data["mixed_results"]:
        if (
            isinstance(entry["value"], dict)
            and entry["value"].get("_type") == Table.TYPE
        ):
            table_data = entry["value"]["_value"]
            break

    assert table_data is not None
    assert len(table_data) == 3

    # Check rows with and without images
    assert isinstance(table_data[0]["result_image"], dict)  # Has image
    assert table_data[1]["result_image"] is None  # No image
    assert isinstance(table_data[2]["result_image"], dict)  # Has image


def test_original_issue_reproduction(image_ndarray, temp_dir):
    """Test the exact scenario from the GitHub issue."""
    import pandas as pd

    trackio.init(project="test_project")

    # Recreate the exact scenario from the issue
    df = pd.DataFrame({"step": [1], "image": [TrackioImage(image_ndarray)]})

    # This should not raise a "TypeError: Object of type TrackioImage is not JSON serializable"
    try:
        trackio.log({"table": Table(dataframe=df)})
        # If we get here, the fix worked
        success = True
    except TypeError as e:
        if "TrackioImage is not JSON serializable" in str(e):
            success = False
        else:
            # Re-raise if it's a different error
            raise

    trackio.finish()

    assert success, "The original issue still exists - TrackioImage not serializable"
