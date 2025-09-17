"""Tests for token authentication functionality."""

import secrets
from unittest.mock import Mock, patch

import pytest


def test_token_generation():
    """Test that tokens are generated with proper length and randomness."""
    token1 = secrets.token_urlsafe(32)
    token2 = secrets.token_urlsafe(32)

    # Tokens should be different
    assert token1 != token2

    # Tokens should be reasonable length
    assert len(token1) > 20
    assert len(token2) > 20


def test_check_write_access():
    """Test the write access validation logic."""
    from trackio.ui.main import check_write_access, demo

    # Mock a demo with a token
    demo.write_token = "test_token_123"

    # Test with valid cookie
    mock_request = Mock()
    mock_request.headers = {"cookie": "trackio_write_token=test_token_123; other=value"}
    mock_request.query_params = {}

    assert check_write_access(mock_request) is True

    # Test with invalid cookie
    mock_request.headers = {"cookie": "trackio_write_token=wrong_token; other=value"}
    assert check_write_access(mock_request) is False

    # Test with valid query param
    mock_request.headers = {"cookie": ""}
    mock_request.query_params = {"write_token": "test_token_123"}
    assert check_write_access(mock_request) is True

    # Test with no token
    mock_request.headers = {"cookie": ""}
    mock_request.query_params = {}
    assert check_write_access(mock_request) is False


def test_show_function_generates_token():
    """Test that the show function generates and uses a token."""
    from trackio.ui.main import demo

    with (
        patch("trackio.ui.main.demo.launch") as mock_launch,
        patch("webbrowser.open") as mock_browser,
        patch("trackio.utils.is_in_notebook", return_value=False),
    ):
        mock_launch.return_value = (None, "http://localhost:7860", None)

        # Import and call show
        from trackio import show

        show(project="test")

        # Check that token was set on demo
        assert hasattr(demo, "write_token")
        assert len(demo.write_token) > 20

        # Check that browser was opened with token in URL
        mock_browser.assert_called_once()
        called_url = mock_browser.call_args[0][0]
        assert "write_token=" in called_url
        assert demo.write_token in called_url
        assert "project=test" in called_url


def test_delete_button_access():
    """Test the delete button access function."""
    from trackio.ui.main import demo
    from trackio.ui.runs import update_delete_button_access

    demo.write_token = "test_delete_token"

    # Test with valid access
    mock_request = Mock()
    mock_request.headers = {"cookie": "trackio_write_token=test_delete_token"}
    mock_request.query_params = {}

    result = update_delete_button_access(mock_request)
    assert "Select and delete run(s)" in result.value
    assert result.variant == "stop"

    # Test without access
    mock_request.headers = {"cookie": ""}
    mock_request.query_params = {}

    result = update_delete_button_access(mock_request)
    assert "Need write access to delete runs" in result.value
    assert result.variant == "secondary"
