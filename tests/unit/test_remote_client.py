import types

import httpx2
import pytest

from trackio import remote_client
from trackio.remote_client import gradio_client_httpx, is_transient_remote_error

HTTP_MODULES = [httpx2]
if hasattr(gradio_client_httpx, "HTTPStatusError"):
    HTTP_MODULES.append(gradio_client_httpx)


@pytest.mark.parametrize("http", HTTP_MODULES)
def test_transient_remote_errors_from_trackio_and_gradio_client(http):
    request = http.Request("POST", "https://example.hf.space/api/bulk_log")

    assert is_transient_remote_error(http.ConnectError("offline", request=request))
    assert is_transient_remote_error(
        http.HTTPStatusError(
            "server error",
            request=request,
            response=http.Response(503, request=request),
        )
    )
    assert not is_transient_remote_error(
        http.HTTPStatusError(
            "bad request",
            request=request,
            response=http.Response(400, request=request),
        )
    )


def test_http_error_types_skip_clients_without_them(monkeypatch):
    monkeypatch.setattr(remote_client, "gradio_client_httpx", types.ModuleType("httpx"))
    assert remote_client._http_error_types("HTTPStatusError") == (
        httpx2.HTTPStatusError,
    )
