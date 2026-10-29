import httpx2
import pytest

from trackio import remote_client
from trackio.exceptions import IncompatibleServerError
from trackio.remote_client import (
    RemoteClient,
    handle_file,
    is_transient_remote_error,
)


def test_transient_remote_errors():
    request = httpx2.Request("POST", "https://example.hf.space/api/bulk_log")

    assert is_transient_remote_error(httpx2.ConnectError("offline", request=request))
    assert is_transient_remote_error(
        httpx2.HTTPStatusError(
            "server error",
            request=request,
            response=httpx2.Response(503, request=request),
        )
    )
    assert not is_transient_remote_error(
        httpx2.HTTPStatusError(
            "bad request",
            request=request,
            response=httpx2.Response(400, request=request),
        )
    )


def test_handle_file(tmp_path):
    path = tmp_path / "metrics.db"
    path.write_bytes(b"data")

    assert handle_file(path) == {
        "path": str(path),
        "meta": {"_type": "gradio.FileData"},
        "orig_name": "metrics.db",
    }
    with pytest.raises(ValueError):
        handle_file(tmp_path / "missing.db")


def _serve_version(monkeypatch, status_code, body=None):
    def get(url, **kwargs):
        request = httpx2.Request("GET", url)
        if body is None:
            return httpx2.Response(status_code, text="Not Found", request=request)
        return httpx2.Response(status_code, json=body, request=request)

    monkeypatch.setattr(remote_client.httpx2, "get", get)


def test_remote_client_uses_http_api(monkeypatch):
    _serve_version(monkeypatch, 200, {"api_version": remote_client.HTTP_API_VERSION})

    client = RemoteClient("user/space")

    assert isinstance(client._client, remote_client._TrackioHTTPClient)


def test_remote_client_rejects_running_space_older_than_http_api(monkeypatch):
    _serve_version(monkeypatch, 404)
    monkeypatch.setattr(remote_client, "_space_is_running", lambda space_id: True)

    with pytest.raises(IncompatibleServerError, match="trackio bump user/space"):
        RemoteClient("user/space")


def test_remote_client_rejects_server_older_than_http_api(monkeypatch):
    _serve_version(monkeypatch, 404)

    with pytest.raises(IncompatibleServerError, match="Upgrade Trackio"):
        RemoteClient("http://127.0.0.1:7860/")


@pytest.mark.parametrize("status_code", [404, 503])
def test_remote_client_waits_for_space_that_is_not_running(monkeypatch, status_code):
    _serve_version(monkeypatch, status_code)
    monkeypatch.setattr(remote_client, "_space_is_running", lambda space_id: False)

    with pytest.raises(ConnectionError):
        RemoteClient("user/space")
