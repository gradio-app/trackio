"""Unit tests for functions defined as part of the Gradio UI"""

import pytest

from trackio import ui


def test_read_only_mode_blocks_api_access(temp_dir):
    ui.check_auth(None)
    ui.demo.read_only = True
    with pytest.raises(PermissionError, match="Dashboard is in read-only mode"):
        ui.check_auth(None)
