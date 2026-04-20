from starlette.testclient import TestClient

from trackio.asgi_app import create_trackio_starlette_app


def _echo(msg: str = "") -> str:
    return msg


def _hf_echo(hf_token: str | None = None) -> str | None:
    return hf_token


def test_gradio_api_info_call_poll_and_headers(monkeypatch, temp_dir):
    monkeypatch.setenv("SYSTEM", "spaces")
    app = create_trackio_starlette_app([], {"echo": _echo})
    client = TestClient(app)

    info = client.get("/gradio_api/info")
    assert info.status_code == 200
    body = info.json()
    assert "/echo" in body["named_endpoints"]
    assert body["unnamed_endpoints"] == {}

    post = client.post("/gradio_api/call/echo", json={"data": ["hi"]})
    assert post.status_code == 200
    event_id = post.json()["event_id"]

    poll = client.get(f"/gradio_api/call/echo/{event_id}")
    assert poll.status_code == 200
    assert poll.headers.get("cache-control") == "no-store"
    assert poll.headers.get("x-accel-buffering") == "no"
    assert "event: complete" in poll.text
    assert '"hi"' in poll.text


def test_gradio_poll_wrong_api_name_not_consumed(monkeypatch, temp_dir):
    monkeypatch.setenv("SYSTEM", "spaces")
    app = create_trackio_starlette_app([], {"echo": _echo})
    client = TestClient(app)

    post = client.post("/gradio_api/call/echo", json={"data": ["x"]})
    event_id = post.json()["event_id"]

    bad = client.get(f"/gradio_api/call/other/{event_id}")
    assert bad.status_code == 404

    ok = client.get(f"/gradio_api/call/echo/{event_id}")
    assert ok.status_code == 200


def test_hf_token_from_authorization_on_spaces(monkeypatch, temp_dir):
    monkeypatch.setenv("SYSTEM", "spaces")
    app = create_trackio_starlette_app([], {"hf_echo": _hf_echo})
    client = TestClient(app)

    r = client.post(
        "/api/hf_echo",
        json={},
        headers={"Authorization": "Bearer space-token"},
    )
    assert r.status_code == 200
    assert r.json()["data"] == "space-token"


def test_hf_token_empty_or_whitespace_body_uses_bearer(monkeypatch, temp_dir):
    monkeypatch.setenv("SYSTEM", "spaces")
    app = create_trackio_starlette_app([], {"hf_echo": _hf_echo})
    client = TestClient(app)

    r = client.post(
        "/api/hf_echo",
        json={"hf_token": ""},
        headers={"Authorization": "Bearer from-header"},
    )
    assert r.status_code == 200
    assert r.json()["data"] == "from-header"

    r2 = client.post(
        "/api/hf_echo",
        json={"hf_token": "  "},
        headers={"Authorization": "Bearer from-header"},
    )
    assert r2.status_code == 200
    assert r2.json()["data"] == "from-header"


def test_gradio_upload_aliases_api_upload(monkeypatch, temp_dir):
    monkeypatch.setenv("SYSTEM", "spaces")
    app = create_trackio_starlette_app([], {"echo": _echo})
    client = TestClient(app)

    g = client.post("/gradio_api/upload", files={"files": ("a.txt", b"x")})
    assert g.status_code == 200
    assert "paths" in g.json()
