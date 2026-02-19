import os
import tempfile
from pathlib import Path

import numpy as np
import pytest
from PIL import Image as PILImage

from trackio import context_vars
from trackio.media import write_audio, write_video


@pytest.fixture
def test_space_id():
    space_id = os.environ.get("TEST_SPACE_ID")
    if not space_id:
        pytest.skip("TEST_SPACE_ID environment variable not set")
    return space_id


@pytest.fixture
def temp_dir(monkeypatch):
    """Fixture that creates a temporary TRACKIO_DIR."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        for name in ["trackio.sqlite_storage"]:
            monkeypatch.setattr(f"{name}.TRACKIO_DIR", Path(tmpdir))
        for name in ["trackio.media.media", "trackio.media.utils", "trackio.utils"]:
            monkeypatch.setattr(f"{name}.MEDIA_DIR", Path(tmpdir) / "media")
        context_vars.current_run.set(None)
        context_vars.current_project.set(None)
        context_vars.current_server.set(None)
        context_vars.current_space_id.set(None)
        context_vars.current_share_server.set(None)
        yield tmpdir
        context_vars.current_run.set(None)
        context_vars.current_project.set(None)
        context_vars.current_server.set(None)
        context_vars.current_space_id.set(None)
        context_vars.current_share_server.set(None)


@pytest.fixture(autouse=True)
def set_numpy_seed():
    np.random.seed(0)


@pytest.fixture
def image_ndarray():
    return np.random.randint(255, size=(100, 100, 3), dtype=np.uint8)


@pytest.fixture
def image_pil():
    return PILImage.fromarray(
        np.random.randint(255, size=(100, 100, 3), dtype=np.uint8)
    )


@pytest.fixture
def image_path(image_ndarray, tmp_path):
    file_path = Path(tmp_path, "foo.png")
    PILImage.fromarray(image_ndarray).save(file_path)
    return file_path


@pytest.fixture
def video_ndarray():
    return np.random.randint(255, size=(60, 3, 128, 96), dtype=np.uint8)


@pytest.fixture
def video_ndarray_batch():
    return np.random.randint(255, size=(5, 60, 3, 128, 96), dtype=np.uint8)


@pytest.fixture
def video_path(video_ndarray, tmp_path):
    file_path = Path(tmp_path, "foo.mp4")
    video_ndarray = video_ndarray.transpose(0, 2, 3, 1)
    write_video(file_path, video_ndarray, codec="h264", fps=30)
    return file_path


@pytest.fixture
def audio_ndarray():
    sr = 16000
    t = np.linspace(0.0, 1.0, sr, endpoint=False)
    wave = 0.12 * np.sin(2 * np.pi * 440.0 * t)
    wave = np.clip(wave, -0.9999, 0.9999)
    pcm_i16 = (wave * 32767.0).astype(np.int16)
    return pcm_i16


@pytest.fixture
def audio_path(audio_ndarray, tmp_path):
    file_path = Path(tmp_path, "tone.wav")
    write_audio(data=audio_ndarray, sample_rate=16000, filename=file_path, format="wav")
    return file_path
