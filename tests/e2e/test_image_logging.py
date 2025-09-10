import trackio
from trackio.media import TrackioImage
from trackio.sqlite_storage import SQLiteStorage

PROJECT_NAME = "test_project"


def test_image_logging(temp_dir, image_ndarray):
    trackio.init(project=PROJECT_NAME, name="test_run")

    image1 = trackio.Image(
        image_ndarray,
        caption="test_caption1",
    )
    image2 = trackio.Image(
        image_ndarray,
        caption="test_caption2",
    )
    trackio.log(metrics={"loss": 0.1, "img1": image1})
    trackio.log(metrics={"loss": 0.2, "img1": image1, "img2": image2})
    trackio.finish()

    metrics = SQLiteStorage.get_logs(project=PROJECT_NAME, run="test_run")

    assert len(metrics) == 2

    assert metrics[0]["loss"] == 0.1
    assert metrics[0]["step"] == 0
    assert metrics[0]["img1"].get("_type") == TrackioImage.TYPE
    assert metrics[0]["img1"].get("file_path") == str(image1._get_relative_file_path())
    assert metrics[0]["img1"].get("caption") == "test_caption1"

    assert metrics[1]["loss"] == 0.2
    assert metrics[1]["step"] == 1

    assert metrics[1]["img1"].get("_type") == TrackioImage.TYPE
    assert metrics[1]["img1"].get("file_path") == str(image1._get_relative_file_path())
    assert metrics[1]["img1"].get("caption") == "test_caption1"

    assert metrics[1]["img2"].get("_type") == TrackioImage.TYPE
    assert metrics[1]["img2"].get("file_path") == str(image2._get_relative_file_path())
    assert metrics[1]["img2"].get("caption") == "test_caption2"
