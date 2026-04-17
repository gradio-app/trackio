"""Serves the built Svelte frontend alongside the Trackio HTTP API."""

import logging
import re
from pathlib import Path

from starlette.responses import HTMLResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

FRONTEND_DIR = Path(__file__).parent / "frontend" / "dist"
ASSETS_DIR = Path(__file__).parent / "assets"

_logger = logging.getLogger(__name__)

_SPA_SEGMENTS = (
    "metrics",
    "system",
    "media",
    "reports",
    "runs",
    "run",
    "files",
    "settings",
)


def mount_frontend(app):
    if not FRONTEND_DIR.exists():
        _logger.warning(
            "Trackio dashboard UI was not mounted: %s is missing. "
            "Build the frontend with `npm ci && npm run build` in trackio/frontend.",
            FRONTEND_DIR,
        )
        return

    index_html_path = FRONTEND_DIR / "index.html"
    if not index_html_path.exists():
        _logger.warning(
            "Trackio dashboard UI was not mounted: %s is missing.",
            index_html_path,
        )
        return

    index_html_content = index_html_path.read_text()
    patched_html = re.sub(
        r'/assets/(index-[^"]+)',
        r"/assets/app/\1",
        index_html_content,
    )

    async def serve_frontend(request):
        return HTMLResponse(patched_html)

    vite_assets = StaticFiles(directory=str(FRONTEND_DIR / "assets"))
    static_assets = StaticFiles(directory=str(ASSETS_DIR))

    app.routes.insert(0, Mount("/static/trackio", app=static_assets))
    app.routes.insert(0, Mount("/assets/app", app=vite_assets))

    for seg in reversed(_SPA_SEGMENTS):
        app.routes.insert(0, Route(f"/{seg}/", serve_frontend, methods=["GET"]))
        app.routes.insert(0, Route(f"/{seg}", serve_frontend, methods=["GET"]))
    app.routes.insert(0, Route("/", serve_frontend, methods=["GET"]))
