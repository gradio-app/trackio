"""Serves the built Svelte frontend alongside the Gradio API."""

import re
from pathlib import Path

from starlette.responses import HTMLResponse, RedirectResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

FRONTEND_DIR = Path(__file__).parent / "frontend" / "dist"
ASSETS_DIR = Path(__file__).parent / "assets"


def mount_frontend(app):
    if not FRONTEND_DIR.exists():
        return

    index_html_path = FRONTEND_DIR / "index.html"
    if not index_html_path.exists():
        return

    index_html_content = index_html_path.read_text()
    patched_html = re.sub(
        r'/trackio/assets/(index-[^"]+)',
        r"/trackio/assets/app/\1",
        index_html_content,
    )

    async def serve_frontend(request):
        return HTMLResponse(patched_html)

    frontend_app = Mount(
        "/trackio",
        routes=[
            Mount(
                "/assets/app",
                app=StaticFiles(directory=str(FRONTEND_DIR / "assets")),
                name="trackio-frontend-assets",
            ),
            Mount(
                "/assets",
                app=StaticFiles(directory=str(ASSETS_DIR)),
                name="trackio-static-assets",
            ),
            Route("/", endpoint=serve_frontend),
            Route("/{path:path}", endpoint=serve_frontend),
        ],
    )

    async def redirect_root(request):
        query_string = request.url.query
        target = "/trackio/"
        if query_string:
            target += f"?{query_string}"
        return RedirectResponse(url=target)

    app.routes.insert(0, Route("/", endpoint=redirect_root))
    app.routes.insert(1, frontend_app)
