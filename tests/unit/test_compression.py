from starlette.applications import Starlette
from starlette.responses import JSONResponse, Response
from starlette.routing import Route
from starlette.testclient import TestClient

from trackio.compression import CompressionMiddleware


def _build_app():
    big_payload = [{"i": i, "loss": i * 0.001, "name": "metric"} for i in range(2000)]

    async def data(_request):
        return JSONResponse(big_payload)

    async def tiny(_request):
        return JSONResponse({"ok": True})

    async def image(_request):
        return Response(b"\x00" * 5000, media_type="image/png")

    app = Starlette(
        routes=[
            Route("/data", data),
            Route("/tiny", tiny),
            Route("/image", image),
        ]
    )
    app.add_middleware(CompressionMiddleware)
    return app


def test_brotli_is_negotiated_and_roundtrips():
    client = TestClient(_build_app())
    r = client.get("/data", headers={"Accept-Encoding": "br"})
    assert r.headers["content-encoding"] == "br"
    assert "accept-encoding" in r.headers.get("vary", "").lower()
    assert len(r.json()) == 2000


def test_gzip_fallback_when_brotli_not_accepted():
    client = TestClient(_build_app())
    r = client.get("/data", headers={"Accept-Encoding": "gzip"})
    assert r.headers["content-encoding"] == "gzip"
    assert len(r.json()) == 2000


def test_identity_when_no_encoding_accepted():
    client = TestClient(_build_app())
    r = client.get("/data", headers={"Accept-Encoding": "identity"})
    assert "content-encoding" not in r.headers
    assert len(r.json()) == 2000


def test_small_response_is_not_compressed():
    client = TestClient(_build_app())
    r = client.get("/tiny", headers={"Accept-Encoding": "br"})
    assert "content-encoding" not in r.headers
    assert r.json() == {"ok": True}


def test_non_text_content_passes_through_uncompressed():
    client = TestClient(_build_app())
    r = client.get("/image", headers={"Accept-Encoding": "br"})
    assert "content-encoding" not in r.headers
    assert len(r.content) == 5000
