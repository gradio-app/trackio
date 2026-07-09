import hashlib
import tempfile
from pathlib import Path

import numpy as np
import pytest
from PIL import Image as PILImage

from trackio import context_vars
from trackio.media import write_audio, write_video


@pytest.fixture
def temp_dir(monkeypatch):
    """Fixture that creates a temporary TRACKIO_DIR."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        for name in ["trackio", "trackio.sqlite_storage", "trackio.utils"]:
            monkeypatch.setattr(f"{name}.TRACKIO_DIR", Path(tmpdir))
        for name in ["trackio.media.media", "trackio.utils"]:
            monkeypatch.setattr(f"{name}.MEDIA_DIR", Path(tmpdir) / "media")
        monkeypatch.setattr("trackio.utils.ARTIFACTS_DIR", Path(tmpdir) / "artifacts")
        monkeypatch.setattr("trackio.bucket_storage.TRACKIO_DIR", Path(tmpdir))
        context_vars.current_run.set(None)
        context_vars.current_project.set(None)
        context_vars.current_server.set(None)
        context_vars.current_space_id.set(None)
        yield tmpdir
        context_vars.current_run.set(None)
        context_vars.current_project.set(None)
        context_vars.current_server.set(None)
        context_vars.current_space_id.set(None)


@pytest.fixture
def stage_blob(temp_dir):
    """Factory that writes `payload` into the local content-addressed store
    for `project`, as Artifact._build_manifest would. Returns
    (digest, blob_path)."""

    def _stage(project, payload):
        from trackio.utils import canonical_project_name

        digest = hashlib.sha256(payload).hexdigest()
        blob = (
            Path(temp_dir)
            / "artifacts"
            / canonical_project_name(project)
            / "blobs"
            / "sha256"
            / digest[:2]
            / digest
        )
        blob.parent.mkdir(parents=True, exist_ok=True)
        blob.write_bytes(payload)
        return digest, blob

    return _stage


@pytest.fixture(autouse=True)
def set_numpy_seed():
    np.random.seed(0)


@pytest.fixture(autouse=True)
def disable_logbook_autonote(monkeypatch):
    monkeypatch.setenv("TRACKIO_LOGBOOK_AUTONOTE", "0")


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
