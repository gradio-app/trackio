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
    run = trackio.init(project=PROJECT_NAME, name="test_run")

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

    trackio.log({"experiment_results": table})

    trackio.finish()

    stored_data = SQLiteStorage.get_all_metrics(PROJECT_NAME, "test_run")

    assert "experiment_results" in stored_data

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

    for i, row in enumerate(stored_table["_value"]):
        assert row["step"] == i + 1
        assert row["accuracy"] == [0.85, 0.92][i]
        assert row["description"] == ["first test", "second test"][i]

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
            "result_image": [img, None, img],
            "score": [0.75, 0.80, 0.85],
        }
    )

    table = Table(dataframe=df)
    trackio.log({"mixed_results": table})
    trackio.finish()

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

    assert isinstance(table_data[0]["result_image"], dict)
    assert table_data[1]["result_image"] is None
    assert isinstance(table_data[2]["result_image"], dict)


def test_original_issue_reproduction(image_ndarray, temp_dir):
    """Test the exact scenario from the GitHub issue."""
    import pandas as pd

    trackio.init(project="test_project")

    df = pd.DataFrame({"step": [1], "image": [TrackioImage(image_ndarray)]})

    try:
        trackio.log({"table": Table(dataframe=df)})
        success = True
    except TypeError as e:
        if "TrackioImage is not JSON serializable" in str(e):
            success = False
        else:
            raise

    trackio.finish()

    assert success, "The original issue still exists - TrackioImage not serializable"
