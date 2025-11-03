import pandas as pd
import pytest

from trackio.media import TrackioImage
from trackio.table import Table

PROJECT_NAME = "test_project"
RUN_NAME = "test_run"


def test_table_without_images():
    """Test table creation and serialization without images."""
    df = pd.DataFrame({"step": [1, 2, 3], "value": [10, 20, 30]})
    table = Table(dataframe=df)

    result = table._to_dict()
    expected_data = [
        {"step": 1, "value": 10},
        {"step": 2, "value": 20},
        {"step": 3, "value": 30},
    ]

    assert result["_type"] == Table.TYPE
    assert result["_value"] == expected_data


def test_table_with_images(image_ndarray, temp_dir):
    """Test table creation and serialization with TrackioImage objects."""
    img1 = TrackioImage(image_ndarray, caption="Test Image 1")
    img2 = TrackioImage(image_ndarray, caption="Test Image 2")

    df = pd.DataFrame({"step": [1, 2], "image": [img1, img2], "value": [10, 20]})

    table = Table(dataframe=df)

    # Verify that the table has stored the original dataframe
    assert table._original_dataframe is not None
    assert table.data is None  # Should be None until _to_dict is called

    # Test serialization
    result = table._to_dict(project=PROJECT_NAME, run=RUN_NAME, step=0)

    assert result["_type"] == Table.TYPE
    assert "_value" in result
    assert len(result["_value"]) == 2

    # Check that images were serialized correctly
    for i, row in enumerate(result["_value"]):
        assert row["step"] == i + 1
        assert row["value"] == (i + 1) * 10

        # Check that image was serialized
        assert isinstance(row["image"], dict)
        assert row["image"]["_type"] == TrackioImage.TYPE
        assert "file_path" in row["image"]
        assert row["image"]["caption"] == f"Test Image {i + 1}"


def test_table_mixed_content(image_ndarray, temp_dir):
    """Test table with mix of images and regular data."""
    img = TrackioImage(image_ndarray, caption="Mixed Test")

    df = pd.DataFrame(
        {
            "step": [1, 2, 3],
            "image": [img, None, img],
            "text": ["hello", "world", "test"],
            "number": [1.5, 2.5, 3.5],
        }
    )

    table = Table(dataframe=df)
    result = table._to_dict(project=PROJECT_NAME, run=RUN_NAME, step=5)

    assert result["_type"] == Table.TYPE
    assert len(result["_value"]) == 3

    # Check first row (with image)
    row1 = result["_value"][0]
    assert row1["step"] == 1
    assert row1["text"] == "hello"
    assert row1["number"] == 1.5
    assert isinstance(row1["image"], dict)
    assert row1["image"]["_type"] == TrackioImage.TYPE

    # Check second row (without image)
    row2 = result["_value"][1]
    assert row2["step"] == 2
    assert row2["text"] == "world"
    assert row2["number"] == 2.5
    assert row2["image"] is None

    # Check third row (with image)
    row3 = result["_value"][2]
    assert row3["step"] == 3
    assert row3["text"] == "test"
    assert row3["number"] == 3.5
    assert isinstance(row3["image"], dict)
    assert row3["image"]["_type"] == TrackioImage.TYPE


def test_table_backwards_compatibility():
    """Test that table works with data parameter (no dataframe)."""
    data = [{"step": 1, "value": 10}, {"step": 2, "value": 20}]

    table = Table(data=data)
    result = table._to_dict()

    assert result["_type"] == Table.TYPE
    assert result["_value"] == data
    assert (
        not hasattr(table, "_original_dataframe") or table._original_dataframe is None
    )


def test_table_to_dict_without_project_info(image_ndarray, temp_dir):
    """Test that _to_dict works without project info when no images present."""
    df = pd.DataFrame({"step": [1, 2], "value": [10, 20]})
    table = Table(dataframe=df)

    # Should work fine without project/run/step
    result = table._to_dict()
    assert result["_type"] == Table.TYPE
    assert len(result["_value"]) == 2


def test_table_to_dict_with_images_no_project_info(image_ndarray, temp_dir):
    """Test that _to_dict falls back gracefully when images present but no project info."""
    img = TrackioImage(image_ndarray, caption="Test")
    df = pd.DataFrame({"step": [1], "image": [img]})
    table = Table(dataframe=df)

    # Should fall back to original behavior
    result = table._to_dict()
    assert result["_type"] == Table.TYPE
    # Should use the original stored data (None in this case since it has media)
    assert result["_value"] is None


def test_table_to_display_format():
    """Test the new to_display_format static method."""
    # Test data as it would be stored (serialized format)
    table_data = [
        {
            "step": 1,
            "image": {
                "_type": "trackio.image",
                "file_path": "test/path/image.png",
                "caption": "Test Caption",
            },
            "value": 42,
            "text": "regular text",
        },
        {
            "step": 2,
            "image": None,  # No image in this row
            "value": 84,
            "text": "more text",
        },
    ]

    processed_data = Table.to_display_format(table_data)

    assert len(processed_data) == 2

    # Check first row (with image)
    row1 = processed_data[0]
    assert row1["step"] == 1
    assert row1["value"] == 42
    assert row1["text"] == "regular text"
    assert "![Test Caption](/gradio_api/file=" in row1["image"]
    assert "test/path/image.png)" in row1["image"]

    # Check second row (without image)
    row2 = processed_data[1]
    assert row2["step"] == 2
    assert row2["value"] == 84
    assert row2["text"] == "more text"
    assert row2["image"] is None


def test_table_to_display_format_no_images():
    """Test to_display_format with table containing no images."""
    table_data = [
        {"step": 1, "value": 10, "text": "hello"},
        {"step": 2, "value": 20, "text": "world"},
    ]

    processed_data = Table.to_display_format(table_data)

    assert len(processed_data) == 2
    assert processed_data == table_data  # Should be unchanged
