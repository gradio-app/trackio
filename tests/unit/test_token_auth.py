"""Tests for token authentication functionality."""

from unittest.mock import Mock

import huggingface_hub as hf
import pytest

from trackio.server import check_hf_token_has_write_access, check_write_access


@pytest.fixture(autouse=True)
def clear_token_access_cache():
    check_hf_token_has_write_access.cache_clear()
    yield
    check_hf_token_has_write_access.cache_clear()


def test_check_write_access():
    test_token = "test_token_123"

    mock_request = Mock()
    mock_request.headers = {"cookie": "trackio_write_token=test_token_123; other=value"}
    mock_request.query_params = {}
    assert check_write_access(mock_request, test_token)

    mock_request.headers = {"cookie": "trackio_write_token=wrong_token; other=value"}
    assert not check_write_access(mock_request, test_token)

    mock_request.headers = {"cookie": ""}
    mock_request.query_params = {"write_token": "test_token_123"}
    assert check_write_access(mock_request, test_token)

    mock_request.headers = {"cookie": ""}
    mock_request.query_params = {}
    assert not check_write_access(mock_request, test_token)


def test_space_secret_token_skips_hub_permission_check(monkeypatch):
    monkeypatch.setenv("SYSTEM", "spaces")
    monkeypatch.setenv("HF_TOKEN", "space-token")
    auth_check = Mock()
    monkeypatch.setattr("trackio.server.HfApi.auth_check", auth_check)

    check_hf_token_has_write_access("space-token")

    auth_check.assert_not_called()


def test_refreshed_oauth_token_uses_repository_write_check(monkeypatch):
    monkeypatch.setenv("SYSTEM", "spaces")
    monkeypatch.setenv("HF_TOKEN", "stale-space-token")
    monkeypatch.setenv("SPACE_AUTHOR_NAME", "user")
    monkeypatch.setenv("SPACE_REPO_NAME", "trackio")
    auth_check = Mock()
    monkeypatch.setattr("trackio.server.HfApi.auth_check", auth_check)

    check_hf_token_has_write_access("refreshed-oauth-token")

    auth_check.assert_called_once_with(
        "user/trackio",
        repo_type="space",
        token="refreshed-oauth-token",
        write=True,
    )


def test_token_without_repository_write_access_is_rejected(monkeypatch):
    monkeypatch.setenv("SYSTEM", "spaces")
    monkeypatch.setenv("HF_TOKEN", "space-token")
    monkeypatch.setenv("SPACE_AUTHOR_NAME", "user")
    monkeypatch.setenv("SPACE_REPO_NAME", "trackio")
    auth_check = Mock(
        side_effect=hf.errors.HfHubHTTPError("denied", response=Mock(status_code=403))
    )
    monkeypatch.setattr("trackio.server.HfApi.auth_check", auth_check)

    with pytest.raises(PermissionError, match="provide write access"):
        check_hf_token_has_write_access("read-only-token")


def test_hub_permission_check_outage_is_not_reported_as_denied(monkeypatch):
    monkeypatch.setenv("SYSTEM", "spaces")
    monkeypatch.setenv("HF_TOKEN", "space-token")
    monkeypatch.setenv("SPACE_AUTHOR_NAME", "user")
    monkeypatch.setenv("SPACE_REPO_NAME", "trackio")
    error = hf.errors.HfHubHTTPError("unavailable", response=Mock(status_code=503))
    monkeypatch.setattr("trackio.server.HfApi.auth_check", Mock(side_effect=error))

    with pytest.raises(hf.errors.HfHubHTTPError) as exc_info:
        check_hf_token_has_write_access("oauth-token")

    assert exc_info.value is error
