from trackio import remote_client
from trackio.remote_client import _TrackioGradioCompatClient


def test_compat_client_maps_hf_token_to_token_kwarg(monkeypatch):
    captured = {}

    class FakeNewGradioClient:
        def __init__(self, src, token=None, verbose=True, httpx_kwargs=None):
            captured.update(src=src, token=token, httpx_kwargs=httpx_kwargs)

    monkeypatch.setattr(remote_client, "GradioClient", FakeNewGradioClient)
    _TrackioGradioCompatClient("user/space", hf_token="hf_secret")
    assert captured["src"] == "user/space"
    assert captured["token"] == "hf_secret"
    assert captured["httpx_kwargs"]["headers"]["authorization"] == "Bearer hf_secret"


def test_compat_client_keeps_hf_token_kwarg_on_old_versions(monkeypatch):
    captured = {}

    class FakeOldGradioClient:
        def __init__(self, src, hf_token=None, verbose=True, httpx_kwargs=None):
            captured.update(src=src, hf_token=hf_token, httpx_kwargs=httpx_kwargs)

    monkeypatch.setattr(remote_client, "GradioClient", FakeOldGradioClient)
    _TrackioGradioCompatClient("user/space", hf_token="hf_secret")
    assert captured["hf_token"] == "hf_secret"


def test_compat_client_drops_unsupported_kwargs(monkeypatch):
    captured = {}

    class FakeMinimalGradioClient:
        def __init__(self, src, token=None, verbose=True):
            captured.update(src=src, token=token)

    monkeypatch.setattr(remote_client, "GradioClient", FakeMinimalGradioClient)
    _TrackioGradioCompatClient(
        "user/space", hf_token="hf_secret", write_token="wt", verbose=False
    )
    assert captured["src"] == "user/space"
    assert captured["token"] == "hf_secret"
