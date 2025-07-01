import tempfile

import pytest


@pytest.fixture
def temp_db(monkeypatch):
    """Fixture that creates a temporary directory for database storage and patches the TRACKIO_DIR."""
    with tempfile.TemporaryDirectory() as tmpdir:
        monkeypatch.setattr("trackio.sqlite_storage.TRACKIO_DIR", tmpdir)
        yield tmpdir
