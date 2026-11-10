"""Tests for token authentication functionality."""

from unittest.mock import Mock

import pytest

import trackio.server as trackio_server
from trackio.server import check_write_access as check_write_access_runs


def test_check_write_access_header():
    mock_request = Mock()
    mock_request.query_params = {}
    for token, allowed in [
        ("secret", True),
        ("wrong!", False),
        ("secret-but-longer", False),
        ("", False),
    ]:
        mock_request.headers = {"x-trackio-write-token": token}
        assert check_write_access_runs(mock_request, "secret") is allowed


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


@pytest.mark.parametrize(
    "who, allowed",
    [
        ({"name": "acme", "orgs": []}, True),
        ({"name": "alice", "orgs": [{"name": "acme", "roleInOrg": "admin"}]}, True),
        ({"name": "bob", "orgs": [{"name": "acme", "roleInOrg": "write"}]}, True),
        (
            {"name": "carol", "orgs": [{"name": "acme", "roleInOrg": "contributor"}]},
            False,
        ),
        ({"name": "dave", "orgs": [{"name": "acme", "roleInOrg": "read"}]}, False),
        ({"name": "erin", "orgs": [{"name": "other", "roleInOrg": "admin"}]}, False),
    ],
)
def test_run_mutation_status_for_space_owner_org_roles(monkeypatch, who, allowed):
    monkeypatch.setenv("SYSTEM", "spaces")
    monkeypatch.setenv("SPACE_AUTHOR_NAME", "acme")
    monkeypatch.setattr(trackio_server, "_oauth_write_cache", {})
    monkeypatch.setattr(trackio_server.HfApi, "whoami", lambda token, cache=False: who)

    mock_request = Mock()
    mock_request.headers = {"cookie": "trackio_hf_access_token=hf_oauth"}
    mock_request.query_params = {}
    status = trackio_server.get_run_mutation_status(mock_request)

    assert status["allowed"] is allowed
    assert status["auth"] == ("oauth" if allowed else "oauth_insufficient")
