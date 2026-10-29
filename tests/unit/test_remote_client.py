import httpx2
import pytest

from trackio.remote_client import gradio_client_httpx, is_transient_remote_error


@pytest.mark.parametrize("http", [httpx2, gradio_client_httpx])
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
