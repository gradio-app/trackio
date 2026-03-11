"""Serves the built Svelte frontend alongside the Gradio API."""

from pathlib import Path

from starlette.responses import FileResponse, HTMLResponse
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
    patched_html = index_html_content.replace(
        "/trackio/assets/", "/trackio/assets/app/"
    )

    async def serve_frontend(request):
        path = request.path_params.get("path", "")
        if path and not path.startswith("assets"):
            file_path = FRONTEND_DIR / path
            if file_path.exists() and file_path.is_file():
                return FileResponse(str(file_path))
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

    app.routes.insert(0, frontend_app)
