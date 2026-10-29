import httpx2
import pytest

from trackio import remote_client
from trackio.exceptions import IncompatibleServerError


@pytest.mark.parametrize(
    "running, error", [(True, IncompatibleServerError), (False, ConnectionError)]
)
def test_space_older_than_http_api(monkeypatch, running, error):
    monkeypatch.setattr(
        remote_client.httpx2,
        "get",
        lambda url, **kwargs: httpx2.Response(404, request=httpx2.Request("GET", url)),
    )
    monkeypatch.setattr(remote_client, "_space_is_running", lambda space_id: running)

    with pytest.raises(error):
        remote_client.RemoteClient("user/space")
