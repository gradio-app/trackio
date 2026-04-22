"""Serves a static frontend alongside the Trackio HTTP API."""

import logging
from pathlib import Path

from starlette.responses import FileResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

ASSETS_DIR = Path(__file__).parent / "assets"

_logger = logging.getLogger(__name__)


def mount_frontend(app, frontend_dir: str | Path):
    frontend_root = Path(frontend_dir).resolve()
    if not frontend_root.exists():
        _logger.warning(
            "Trackio dashboard UI was not mounted: %s is missing. "
            "Build the frontend or provide a custom frontend directory.",
            frontend_root,
        )
        return

    index_html_path = frontend_root / "index.html"
    if not index_html_path.exists():
        _logger.warning(
            "Trackio dashboard UI was not mounted: %s is missing.",
            index_html_path,
        )
        return

    async def serve_frontend(request):
        relative_path = request.path_params.get("path", "").lstrip("/")
        requested_path = (frontend_root / relative_path).resolve()
        if (
            relative_path
            and requested_path.is_file()
            and requested_path.is_relative_to(frontend_root)
        ):
            return FileResponse(requested_path)
        return FileResponse(index_html_path)

    static_assets = StaticFiles(directory=str(ASSETS_DIR))

    app.routes.append(Mount("/static/trackio", app=static_assets))
    app.routes.append(Route("/", serve_frontend, methods=["GET"]))
    app.routes.append(Route("/{path:path}", serve_frontend, methods=["GET"]))
