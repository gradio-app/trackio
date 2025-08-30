import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def temp_dir(monkeypatch):
    """Fixture that creates a temporary TRACKIO_DIR."""
    with tempfile.TemporaryDirectory() as tmpdir:
        for name in ("trackio.sqlite_storage", "trackio.media", "trackio.file_storage"):
            monkeypatch.setattr(f"{name}.TRACKIO_DIR", Path(tmpdir))
        yield tmpdir
