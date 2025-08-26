from pathlib import Path

import numpy as np

from trackio.media import TrackioImage

PROJECT_NAME = "test_project"


def test_image_save(temp_dir):
    image = TrackioImage(np.random.randint(255, size=(100, 100, 3), dtype=np.uint8))
    image._save(PROJECT_NAME, "test_run", 0, "PNG")

    assert image._file_format == "PNG"

    expected_rel_dir = Path("media") / PROJECT_NAME / "test_run" / "0"
    assert str(image._get_relative_file_path()).startswith(str(expected_rel_dir))
    assert str(image._get_absolute_file_path()).endswith(".png")
    assert image._get_absolute_file_path().is_file()


def test_image_serialization(temp_dir):
    image = TrackioImage(
        np.random.randint(255, size=(100, 100, 3), dtype=np.uint8),
        caption="test_caption",
    )
    image._save(PROJECT_NAME, "test_run", 0, "PNG")
    value = image._to_dict()

    assert value is not None
    assert value.get("_type") == TrackioImage.TYPE
    assert value.get("file_path") == str(image._get_relative_file_path())
    assert value.get("file_format") == "PNG"
    assert value.get("caption") == "test_caption"


def test_image_deserialization(temp_dir):
    image = TrackioImage(
        np.random.randint(255, size=(100, 100, 3), dtype=np.uint8),
        caption="test_caption",
    )
    image._save(PROJECT_NAME, "test_run", 0, "PNG")
    value = image._to_dict()

    image2 = TrackioImage._from_dict(value)
    assert image2._get_relative_file_path() == image._get_relative_file_path()
    assert image2._get_absolute_file_path() == image._get_absolute_file_path()
    assert image2._get_absolute_file_path().is_file()
    assert image2._file_format == "PNG"
    assert image2.caption == "test_caption"
