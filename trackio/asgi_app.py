from __future__ import annotations

import inspect
import json
import math
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.routing import Route

from trackio.exceptions import TrackioAPIError
from trackio.remote_client import HTTP_API_VERSION


def _normalize_allowed_file_roots(
    allowed_file_roots: list[str | Path] | None,
) -> tuple[Path, ...]:
    roots = []
    for root in allowed_file_roots or []:
        roots.append(Path(root).resolve())
    return tuple(roots)


def _is_allowed_file_path(path: Path, allowed_roots: tuple[Path, ...]) -> bool:
    resolved_path = path.resolve(strict=False)
    for root in allowed_roots:
        try:
            resolved_path.relative_to(root)
            return True
        except ValueError:
            continue
    return False


def _json_safe(data: Any) -> Any:
    if data is None or isinstance(data, (str, bool, int)):
        return data
    if isinstance(data, float):
        return data if math.isfinite(data) else None
    if isinstance(data, dict):
        return {k: _json_safe(v) for k, v in data.items()}
    if isinstance(data, (list, tuple)):
        return [_json_safe(v) for v in data]
    if hasattr(data, "item"):
        try:
            return _json_safe(data.item())
        except Exception:
            pass
    return str(data)


def _invoke_handler(
    fn: Any,
    request: Request,
    args: list[Any] | None = None,
    kwargs: dict[str, Any] | None = None,
) -> Any:
    sig = inspect.signature(fn)
    params = list(sig.parameters.values())
    positional_args: list[Any] = []
    keyword_args: dict[str, Any] = {}
    args = list(args or [])
    kwargs = dict(kwargs or {})
    data_index = 0

    for param in params:
        if param.name == "request":
            keyword_args["request"] = request
        elif param.kind == inspect.Parameter.VAR_POSITIONAL:
            positional_args.extend(args[data_index:])
            data_index = len(args)
        elif param.kind == inspect.Parameter.VAR_KEYWORD:
            keyword_args.update(kwargs)
            kwargs.clear()
        elif param.name in kwargs:
            keyword_args[param.name] = kwargs.pop(param.name)
        elif param.kind in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        ) and data_index < len(args):
            positional_args.append(args[data_index])
            data_index += 1
        elif param.default is inspect.Signature.empty and param.kind not in (
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        ):
            raise TrackioAPIError(f"Missing required parameter: {param.name}")

    return fn(*positional_args, **keyword_args)


async def version_handler(request: Request) -> Response:
    package_json = Path(__file__).parent / "package.json"
    version = json.loads(package_json.read_text())["version"]
    mcp_enabled = bool(getattr(request.app.state, "mcp_enabled", False))
    return JSONResponse(
        {
            "version": version,
            "api_version": HTTP_API_VERSION,
            "api_transport": "http",
            "mcp_enabled": mcp_enabled,
            "mcp_path": "/mcp" if mcp_enabled else None,
        }
    )


async def api_handler(request: Request) -> Response:
    api_registry = request.app.state.api_registry
    api_name = request.path_params["api_name"]
    fn = api_registry.get(api_name)
    if fn is None:
        return JSONResponse({"error": f"Unknown API: {api_name}"}, status_code=404)

    try:
        body = await request.json()
    except Exception:
        body = {}

    args: list[Any] = []
    kwargs: dict[str, Any] = {}
    if isinstance(body, dict):
        if "args" in body or "kwargs" in body:
            args = body.get("args") or []
            kwargs = body.get("kwargs") or {}
        elif "data" in body and isinstance(body["data"], list):
            args = body["data"]
        else:
            kwargs = body
    elif isinstance(body, list):
        args = body
    elif body is not None:
        args = [body]

    if not isinstance(args, list):
        args = [args]
    if not isinstance(kwargs, dict):
        kwargs = {}

    try:
        result = _invoke_handler(fn, request, args=args, kwargs=kwargs)
        return JSONResponse({"data": _json_safe(result)})
    except TrackioAPIError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def upload_handler(request: Request) -> Response:
    form = await request.form()
    uploads = form.getlist("files")
    saved_paths = []
    for upload in uploads:
        suffix = Path(getattr(upload, "filename", "") or "").suffix
        with tempfile.NamedTemporaryFile(
            delete=False,
            prefix="trackio-upload-",
            suffix=suffix,
        ) as tmp:
            tmp.write(await upload.read())
            saved_paths.append(tmp.name)
    return JSONResponse({"paths": saved_paths})


async def file_handler(request: Request) -> Response:
    fs_path = request.query_params.get("path")
    if fs_path is None:
        return Response("Missing path", status_code=400)
    fp = Path(unquote(fs_path))
    allowed_roots = getattr(request.app.state, "allowed_file_roots", ())
    if fp.is_file() and _is_allowed_file_path(fp, allowed_roots):
        return FileResponse(str(fp))
    return Response("Not found", status_code=404)


def create_trackio_starlette_app(
    oauth_routes: list[Route],
    api_registry: dict[str, Any],
    extra_routes: list[Any] | None = None,
    mcp_lifespan: Any = None,
    mcp_enabled: bool = False,
    allowed_file_roots: list[str | Path] | None = None,
) -> Starlette:
    routes: list[Any] = list(oauth_routes)
    routes.extend(
        [
            Route("/version", endpoint=version_handler, methods=["GET"]),
            Route("/api/upload", endpoint=upload_handler, methods=["POST"]),
            Route("/api/{api_name:str}", endpoint=api_handler, methods=["POST"]),
            Route("/file", endpoint=file_handler, methods=["GET"]),
        ]
    )
    routes.extend(extra_routes or [])
    app = Starlette(routes=routes, lifespan=mcp_lifespan)
    app.state.api_registry = api_registry
    app.state.mcp_enabled = mcp_enabled
    app.state.allowed_file_roots = _normalize_allowed_file_roots(allowed_file_roots)
    return app
