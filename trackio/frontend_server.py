"""Serves a static frontend alongside the Trackio HTTP API."""

import hashlib
import logging
from pathlib import Path

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import FileResponse, HTMLResponse, JSONResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

ASSETS_DIR = Path(__file__).parent / "assets"

_logger = logging.getLogger(__name__)

_LIVE_RELOAD_SCRIPT = """
<script>
(() => {
  const endpoint = "/__trackio/frontend_version";
  let currentVersion = null;

  async function poll() {
    try {
      const response = await fetch(endpoint, { cache: "no-store" });
      const payload = await response.json();
      if (currentVersion === null) {
        currentVersion = payload.version;
        return;
      }
      if (payload.version !== currentVersion) {
        window.location.reload();
      }
    } catch (error) {
      console.warn("Trackio live reload poll failed", error);
    }
  }

  poll();
  setInterval(poll, 1000);
})();
</script>
""".strip()


def _frontend_version(frontend_root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(frontend_root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(frontend_root)
        digest.update(str(relative).encode("utf-8"))
        stat = path.stat()
        digest.update(str(stat.st_mtime_ns).encode("utf-8"))
        digest.update(str(stat.st_size).encode("utf-8"))
    return digest.hexdigest()


def _inject_live_reload(html: str) -> str:
    if "/__trackio/frontend_version" in html:
        return html
    if "</body>" in html:
        return html.replace("</body>", f"{_LIVE_RELOAD_SCRIPT}\n  </body>")
    return html + _LIVE_RELOAD_SCRIPT


def _html_response(path: Path) -> HTMLResponse:
    html = path.read_text(encoding="utf-8")
    return HTMLResponse(_inject_live_reload(html))


class FrontendMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, frontend_root: Path, index_html_path: Path):
        super().__init__(app)
        self.frontend_root = frontend_root
        self.index_html_path = index_html_path
        self.reserved_prefixes = (
            "/api/",
            "/file",
            "/version",
            "/static/trackio",
            "/__trackio/frontend_version",
            "/oauth/",
            "/login/",
            "/mcp",
        )
        self.reserved_exact = {
            "/api",
            "/oauth",
            "/login",
        }

    async def dispatch(self, request, call_next):
        if request.method not in {"GET", "HEAD"}:
            return await call_next(request)

        path = request.url.path
        if path in self.reserved_exact or path.startswith(self.reserved_prefixes):
            return await call_next(request)

        relative_path = path.lstrip("/")
        requested_path = (self.frontend_root / relative_path).resolve()
        if (
            relative_path
            and requested_path.is_file()
            and requested_path.is_relative_to(self.frontend_root)
        ):
            if requested_path.suffix.lower() == ".html":
                return _html_response(requested_path)
            return FileResponse(requested_path)

        return _html_response(self.index_html_path)


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

    async def frontend_version(_request):
        return JSONResponse({"version": _frontend_version(frontend_root)})

    static_assets = StaticFiles(directory=str(ASSETS_DIR))

    app.add_middleware(
        FrontendMiddleware,
        frontend_root=frontend_root,
        index_html_path=index_html_path,
    )
    app.routes.append(Mount("/static/trackio", app=static_assets))
    app.routes.append(
        Route("/__trackio/frontend_version", frontend_version, methods=["GET"])
    )
