import pandas as pd

from trackio.media import TrackioImage
from trackio.table import Table

PROJECT_NAME = "test_project"
RUN_NAME = "test_run"


def test_table_to_dict_with_images(image_ndarray, temp_dir):
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

    row1 = result["_value"][0]
    assert row1["step"] == 1
    assert row1["text"] == "hello"
    assert row1["number"] == 1.5
    assert isinstance(row1["image"], dict)
    assert row1["image"]["_type"] == TrackioImage.TYPE

    row2 = result["_value"][1]
    assert row2["step"] == 2
    assert row2["text"] == "world"
    assert row2["number"] == 2.5
    assert row2["image"] is None

    row3 = result["_value"][2]
    assert row3["step"] == 3
    assert row3["text"] == "test"
    assert row3["number"] == 3.5
    assert isinstance(row3["image"], dict)
    assert row3["image"]["_type"] == TrackioImage.TYPE


def test_table_to_display_format_with_images():
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
            "image": None,
            "value": 84,
            "text": "more text",
        },
    ]

    processed_data = Table.to_display_format(table_data)

    assert len(processed_data) == 2

    row1 = processed_data[0]
    assert row1["step"] == 1
    assert row1["value"] == 42
    assert row1["text"] == "regular text"
    assert '<img src="/gradio_api/file=' in row1["image"]
    assert 'image.png"' in row1["image"]
    assert 'alt="Test Caption"' in row1["image"]

    row2 = processed_data[1]
    assert row2["step"] == 2
    assert row2["value"] == 84
    assert row2["text"] == "more text"
    assert row2["image"] is None


def test_table_to_display_format_with_multiple_images():
    table_data = [
        {
            "step": 1,
            "images": [
                {
                    "_type": "trackio.image",
                    "file_path": "test/path/image1.png",
                    "caption": "First Image",
                },
                {
                    "_type": "trackio.image",
                    "file_path": "test/path/image2.png",
                    "caption": "Second Image",
                },
                {
                    "_type": "trackio.image",
                    "file_path": "test/path/image3.png",
                    "caption": "Third Image",
                },
            ],
            "value": 42,
        },
        {
            "step": 2,
            "images": [],
            "value": 84,
        },
    ]

    processed_data = Table.to_display_format(table_data)

    assert len(processed_data) == 2

    row1 = processed_data[0]
    assert row1["step"] == 1
    assert row1["value"] == 42
    assert '<img src="/gradio_api/file=' in row1["images"]
    assert 'alt="First Image"' in row1["images"]
    assert 'image1.png"' in row1["images"]
    assert 'alt="Second Image"' in row1["images"]
    assert 'image2.png"' in row1["images"]
    assert 'alt="Third Image"' in row1["images"]
    assert 'image3.png"' in row1["images"]

    row2 = processed_data[1]
    assert row2["step"] == 2
    assert row2["value"] == 84
    assert row2["images"] == []
