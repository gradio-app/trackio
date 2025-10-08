from pathlib import Path

import pytest

from trackio.media import TrackioImage, TrackioVideo, TrackioAudio

PROJECT_NAME = "test_project"


@pytest.mark.parametrize("image", ["image_ndarray", "image_pil", "image_path"])
def test_image_save(image, temp_dir, request):
    image_value = request.getfixturevalue(image)
    image = TrackioImage(image_value)
    image._save(PROJECT_NAME, "test_run", 0)

    expected_rel_dir = Path(PROJECT_NAME) / "test_run" / "0"
    assert str(image._get_relative_file_path()).startswith(str(expected_rel_dir))
    assert str(image._get_absolute_file_path()).endswith(".png")
    assert image._get_absolute_file_path().is_file()


def test_image_serialization(image_ndarray, temp_dir):
    image = TrackioImage(
        image_ndarray,
        caption="test_caption",
    )
    image._save(PROJECT_NAME, "test_run", 0)
    value = image._to_dict()

    assert value is not None
    assert value.get("_type") == TrackioImage.TYPE
    assert value.get("file_path") == str(image._get_relative_file_path())
    assert value.get("caption") == "test_caption"


@pytest.mark.parametrize(
    "video", ["video_ndarray", "video_path", "video_ndarray_batch"]
)
def test_video_save(video, temp_dir, request):
    video_value = request.getfixturevalue(video)
    video = TrackioVideo(video_value, format="mp4")
    video._save(PROJECT_NAME, "test_run", 0)

    expected_rel_dir = Path(PROJECT_NAME) / "test_run" / "0"
    assert str(video._get_relative_file_path()).startswith(str(expected_rel_dir))
    assert str(video._get_absolute_file_path()).endswith(".mp4")
    assert video._get_absolute_file_path().is_file()


def test_video_serialization(video_ndarray_batch, temp_dir):
    video = TrackioVideo(video_ndarray_batch, format="mp4", caption="test_caption")
    video._save(PROJECT_NAME, "test_run", 0)
    value = video._to_dict()

    assert value is not None
    assert value.get("_type") == TrackioVideo.TYPE
    assert value.get("file_path") == str(video._get_relative_file_path())
    assert value.get("caption") == "test_caption"

@pytest.mark.parametrize("audio", ["audio_ndarray", "audio_path"])
def test_audio_save(audio, temp_dir, request):
    audio_value = request.getfixturevalue(audio)
    audio = TrackioAudio(audio_value, format="wav", sample_rate=16000)
    audio._save(PROJECT_NAME, "test_run", 0)

    expected_rel_dir = Path(PROJECT_NAME) / "test_run" / "0"
    assert str(audio._get_relative_file_path()).startswith(str(expected_rel_dir))
    assert str(audio._get_absolute_file_path()).endswith(".wav")
    assert audio._get_absolute_file_path().is_file()

def test_audio_serialization(audio_ndarray, temp_dir):
    audio = TrackioAudio(audio_ndarray, format="wav", sample_rate=16000, caption="test_caption")
    audio._save(PROJECT_NAME, "test_run", 0)
    value = audio._to_dict()

    assert value is not None
    assert value.get("_type") == TrackioAudio.TYPE
    assert value.get("file_path") == str(audio._get_relative_file_path())
    assert value.get("caption") == "test_caption"