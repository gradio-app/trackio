"""Tests for token authentication functionality."""

from unittest.mock import Mock

from trackio.ui.runs import check_write_access_runs


def test_check_write_access():
    test_token = "test_token_123"

    mock_request = Mock()
    mock_request.headers = {"cookie": "trackio_write_token=test_token_123; other=value"}
    mock_request.query_params = {}
    assert check_write_access_runs(mock_request, test_token)

    mock_request.headers = {"cookie": "trackio_write_token=wrong_token; other=value"}
    assert not check_write_access_runs(mock_request, test_token)

    mock_request.headers = {"cookie": ""}
    mock_request.query_params = {"write_token": "test_token_123"}
    assert check_write_access_runs(mock_request, test_token)

    mock_request.headers = {"cookie": ""}
    mock_request.query_params = {}
    assert not check_write_access_runs(mock_request, test_token)
