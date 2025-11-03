"""End-to-end test for Table with TrackioImage functionality."""

import pandas as pd

import trackio
from trackio.media import TrackioImage
from trackio.sqlite_storage import SQLiteStorage
from trackio.table import Table

PROJECT_NAME = "test_table_images"


def test_table_mixed_images_and_regular_data(image_ndarray, temp_dir):
    """Test table with some rows having images and others not."""
    trackio.init(project=PROJECT_NAME, name="mixed_test")

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
