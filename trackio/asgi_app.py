from __future__ import annotations

import asyncio
import inspect
import json
import secrets
import traceback
from collections.abc import Callable
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response, StreamingResponse
from starlette.routing import Route

from trackio.exceptions import TrackioAPIError

API_PREFIX = "/gradio_api"


def _serialize_result(data: Any) -> str:
    def default(o: Any):
        if isinstance(o, (dict, list, str, int, float, bool)) or o is None:
            return o
        if hasattr(o, "item"):
            try:
                return o.item()
            except Exception:
                pass
        return str(o)

    return json.dumps(data, default=default)


def _invoke_handler(
    fn: Callable,
    request: Request,
    data: list[Any],
) -> Any:
    sig = inspect.signature(fn)
    params = list(sig.parameters.values())
    pos_args: list[Any] = []
    di = 0
    for p in params:
        if p.name == "request":
            pos_args.append(request)
        else:
            if di < len(data):
                pos_args.append(data[di])
            else:
                pos_args.append(None)
            di += 1
    return fn(*pos_args)


class _EventStore:
    def __init__(self) -> None:
        self._results: dict[str, tuple[Any, bool, str | None]] = {}

    def store_result(
        self, event_id: str, result: Any, is_error: bool, err_msg: str | None
    ) -> None:
        self._results[event_id] = (result, is_error, err_msg)

    def pop(self, event_id: str) -> tuple[Any, bool, str | None] | None:
        return self._results.pop(event_id, None)


_event_store = _EventStore()


def build_gradio_compat_handlers(
    api_registry: dict[str, Callable[..., Any]],
) -> tuple[Callable, Callable]:
    async def call_post(request: Request) -> Response:
        api_name = request.path_params["api_name"].lstrip("/")
        fn = api_registry.get(api_name)
        if fn is None:
            return JSONResponse({"detail": f"Unknown API: {api_name}"}, status_code=404)
        try:
            body = await request.json()
        except Exception:
            body = {}
        data = body.get("data") or []
        if not isinstance(data, list):
            data = [data]
        event_id = secrets.token_urlsafe(16)
        try:
            out = await asyncio.to_thread(_invoke_handler, fn, request, data)
            _event_store.store_result(event_id, out, False, None)
        except TrackioAPIError as e:
            _event_store.store_result(event_id, None, True, str(e))
        except Exception:
            tb = traceback.format_exc()
            print(tb)
            _event_store.store_result(event_id, None, True, tb)
        return JSONResponse({"event_id": event_id})

    async def call_get(request: Request) -> Response:
        event_id = request.path_params["event_id"]

        async def sse_gen():
            for _ in range(500):
                await asyncio.sleep(0.005)
                got = _event_store.pop(event_id)
                if got is not None:
                    result, is_err, err_msg = got
                    if is_err:
                        payload = json.dumps(err_msg)
                        yield f"event: error\ndata: {payload}\n\n"
                    else:
                        wrapped = [result] if not isinstance(result, list) else result
                        payload = _serialize_result(wrapped)
                        yield f"event: complete\ndata: {payload}\n\n"
                    return
            err = json.dumps("timeout waiting for result")
            yield f"event: error\ndata: {err}\n\n"

        return StreamingResponse(sse_gen(), media_type="text/event-stream")

    return call_post, call_get


async def gradio_file_handler(request: Request) -> Response:
    from pathlib import Path
    from urllib.parse import unquote

    rest = request.path_params.get("rest", "")
    if not rest.startswith("file="):
        return Response("Not found", status_code=404)
    fs_path = unquote(rest[5:])
    fp = Path(fs_path)
    if fp.is_file():
        return FileResponse(str(fp))
    return Response("Not found", status_code=404)


async def startup_events_handler(request: Request) -> Response:
    return JSONResponse({"status": "ok"})


def create_trackio_starlette_app(
    oauth_routes: list[Route],
    api_registry: dict[str, Callable[..., Any]],
    mcp_lifespan: Any = None,
) -> Starlette:
    call_post, call_get = build_gradio_compat_handlers(api_registry)
    routes: list[Any] = list(oauth_routes)
    routes.append(
        Route(
            API_PREFIX + "/call/{api_name:path}",
            endpoint=call_post,
            methods=["POST"],
        )
    )
    routes.append(
        Route(
            API_PREFIX + "/call/{api_name:path}/{event_id}",
            endpoint=call_get,
            methods=["GET"],
        )
    )
    routes.append(
        Route(
            API_PREFIX + "/startup-events",
            endpoint=startup_events_handler,
            methods=["GET"],
        )
    )
    routes.append(
        Route(
            API_PREFIX + "/{rest:path}", endpoint=gradio_file_handler, methods=["GET"]
        )
    )
    return Starlette(routes=routes, lifespan=mcp_lifespan)
