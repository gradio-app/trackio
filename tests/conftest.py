import tempfile
from pathlib import Path

import numpy as np
import pytest
from PIL import Image as PILImage

from trackio.video_writer import write_video


@pytest.fixture
def temp_dir(monkeypatch):
    """Fixture that creates a temporary TRACKIO_DIR."""
    with tempfile.TemporaryDirectory() as tmpdir:
        for name in ["trackio.sqlite_storage"]:
            monkeypatch.setattr(f"{name}.TRACKIO_DIR", Path(tmpdir))
        for name in ["trackio.media", "trackio.file_storage"]:
            monkeypatch.setattr(f"{name}.MEDIA_DIR", Path(tmpdir) / "media")
        yield tmpdir


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
