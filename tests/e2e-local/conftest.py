import tempfile
from pathlib import Path

import pytest
from _pytest.monkeypatch import MonkeyPatch

from trackio import context_vars


@pytest.fixture(scope="module")
def module_temp_dir():
    """Module-scoped TRACKIO_DIR. The default `temp_dir` is function-scoped;
    use this when an entire test module shares an expensive setup (e.g. _seed)."""
    mp = MonkeyPatch()
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        for name in ["trackio.sqlite_storage"]:
            mp.setattr(f"{name}.TRACKIO_DIR", Path(tmpdir))
        for name in [
            "trackio.media.media",
            "trackio.media.utils",
            "trackio.utils",
            "trackio.sqlite_storage",
        ]:
            mp.setattr(f"{name}.MEDIA_DIR", Path(tmpdir) / "media")
        for cv in (
            context_vars.current_run,
            context_vars.current_project,
            context_vars.current_server,
            context_vars.current_space_id,
        ):
            cv.set(None)
        yield tmpdir
        for cv in (
            context_vars.current_run,
            context_vars.current_project,
            context_vars.current_server,
            context_vars.current_space_id,
        ):
            cv.set(None)
        mp.undo()
