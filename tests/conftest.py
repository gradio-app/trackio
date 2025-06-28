import os
import sys
import tempfile

import pytest

# Ensure local package is imported before site packages
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


@pytest.fixture
def temp_db(monkeypatch):
    """Fixture that creates a temporary directory for database storage and patches the TRACKIO_DIR."""
    with tempfile.TemporaryDirectory() as tmpdir:
        monkeypatch.setattr("trackio.sqlite_storage.TRACKIO_DIR", tmpdir)
        yield tmpdir
