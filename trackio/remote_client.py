from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import httpx
from gradio_client import Client as GradioClient
from huggingface_hub.utils import build_hf_headers

HTTP_API_VERSION = 1


def _normalize_src(src: str) -> str:
    return src if src.endswith("/") else src + "/"


def _space_id_to_url(space_id: str) -> str:
    namespace, name = space_id.split("/", 1)
    return f"https://{namespace}-{name}.hf.space/"


def _resolve_src_url(src: str) -> str:
    if src.startswith(("http://", "https://")):
        return _normalize_src(src)
    if "/" in src:
        return _space_id_to_url(src)
    raise ValueError(
        f"Could not resolve Trackio remote source '{src}'. "
        "Pass a full Space id like 'user/space' or a URL."
    )


def _is_local_file_data(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and "path" in value
        and isinstance(value["path"], str)
        and value.get("meta", {}).get("_type") == "gradio.FileData"
        and Path(value["path"]).exists()
    )


class _TrackioHTTPClient:
    def __init__(
        self,
        src: str,
        hf_token: str | None = None,
        httpx_kwargs: dict[str, Any] | None = None,
    ) -> None:
        self.src = _resolve_src_url(src)
        self.httpx_kwargs = dict(httpx_kwargs or {})
        self.headers = build_hf_headers(token=hf_token)

    def _upload_file(self, file_data: dict[str, Any]) -> dict[str, Any]:
        path = Path(file_data["path"])
        with path.open("rb") as f:
            resp = httpx.post(
                urljoin(self.src, "api/upload"),
                headers=self.headers,
                files={"files": (path.name, f)},
                **self.httpx_kwargs,
            )
        resp.raise_for_status()
        uploaded_path = resp.json()["paths"][0]
        return {
            **file_data,
            "path": uploaded_path,
            "orig_name": file_data.get("orig_name", path.name),
        }

    def _prepare_value(self, value: Any) -> Any:
        if _is_local_file_data(value):
            return self._upload_file(value)
        if isinstance(value, list):
            return [self._prepare_value(item) for item in value]
        if isinstance(value, tuple):
            return [self._prepare_value(item) for item in value]
        if isinstance(value, dict):
            return {k: self._prepare_value(v) for k, v in value.items()}
        return value

    def predict(self, *args, api_name: str, **kwargs) -> Any:
        api_name = api_name.lstrip("/")
        payload = {
            "args": self._prepare_value(list(args)),
            "kwargs": self._prepare_value(kwargs),
        }
        resp = httpx.post(
            urljoin(self.src, f"api/{api_name}"),
            headers=self.headers,
            json=payload,
            **self.httpx_kwargs,
        )
        if resp.status_code == 404:
            raise RuntimeError(
                f"Space '{self.src}' does not support '/{api_name}'. Redeploy with `trackio sync`."
            )
        resp.raise_for_status()
        body = resp.json()
        if body.get("error") is not None:
            raise RuntimeError(body["error"])
        return body.get("data")


class _TrackioGradioCompatClient:
    def __init__(
        self,
        src: str,
        hf_token: str | None = None,
        httpx_kwargs: dict[str, Any] | None = None,
        verbose: bool = False,
    ) -> None:
        kwargs: dict[str, Any] = {"verbose": verbose}
        if hf_token:
            kwargs["hf_token"] = hf_token
        if httpx_kwargs:
            kwargs["httpx_kwargs"] = httpx_kwargs
        self._client = GradioClient(src, **kwargs)

    def predict(self, *args, api_name: str, **kwargs) -> Any:
        try:
            return self._client.predict(*args, api_name=api_name, **kwargs)
        except Exception as e:
            if "API Not Found" in str(e) or "api_name" in str(e):
                raise RuntimeError(
                    f"Space '{self._client.src}' does not support '{api_name}'. "
                    "Redeploy with `trackio sync`."
                ) from e
            raise


def _supports_http_api(
    src: str,
    hf_token: str | None = None,
    httpx_kwargs: dict[str, Any] | None = None,
) -> bool:
    url = _resolve_src_url(src)
    headers = build_hf_headers(token=hf_token)
    kwargs = dict(httpx_kwargs or {})
    kwargs.setdefault("timeout", 10)
    try:
        resp = httpx.get(urljoin(url, "version"), headers=headers, **kwargs)
        if not resp.is_success:
            return False
        data = resp.json()
        return data.get("api_version") == HTTP_API_VERSION
    except Exception:
        return False


class RemoteClient:
    def __init__(
        self,
        space: str,
        hf_token: str | None = None,
        httpx_kwargs: dict[str, Any] | None = None,
        verbose: bool = False,
    ) -> None:
        self._space = space
        try:
            if _supports_http_api(space, hf_token=hf_token, httpx_kwargs=httpx_kwargs):
                self._client = _TrackioHTTPClient(
                    space, hf_token=hf_token, httpx_kwargs=httpx_kwargs
                )
            else:
                self._client = _TrackioGradioCompatClient(
                    space,
                    hf_token=hf_token,
                    httpx_kwargs=httpx_kwargs,
                    verbose=verbose,
                )
        except ValueError:
            raise
        except Exception as e:
            raise ConnectionError(
                f"Could not connect to Space '{space}'. Is it running?\n{e}"
            ) from e

    def predict(self, *args, api_name: str, **kwargs) -> Any:
        return self._client.predict(*args, api_name=api_name, **kwargs)
