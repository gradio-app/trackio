"""Tests for token authentication functionality."""

from unittest.mock import Mock

import pytest

import trackio.server as server
from trackio.server import check_write_access as check_write_access_runs


@pytest.fixture(autouse=True)
def clear_write_token_failures():
    server._write_token_failures.clear()
    yield
    server._write_token_failures.clear()


def _header_request(token, host="203.0.113.7"):
    request = Mock()
    request.headers = {"x-trackio-write-token": token}
    request.query_params = {}
    request.client.host = host
    return request


def test_repeated_wrong_tokens_lock_out_the_client(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(server.time, "monotonic", lambda: now[0])

    for _ in range(server._WRITE_TOKEN_MAX_FAILURES):
        assert not check_write_access_runs(_header_request("guess"), "secret")
    assert not check_write_access_runs(_header_request("secret"), "secret")
    assert check_write_access_runs(
        _header_request("secret", host="198.51.100.2"), "secret"
    )

    now[0] += server._WRITE_TOKEN_FAILURE_WINDOW + 1
    assert check_write_access_runs(_header_request("secret"), "secret")


def test_missing_token_is_not_counted_as_a_failure():
    for _ in range(server._WRITE_TOKEN_MAX_FAILURES + 1):
        assert not check_write_access_runs(_header_request(""), "secret")
    assert check_write_access_runs(_header_request("secret"), "secret")


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
