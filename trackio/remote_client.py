from __future__ import annotations

import hashlib
import inspect
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
import huggingface_hub
from gradio_client import Client as GradioClient
from huggingface_hub.utils import build_hf_headers

from trackio.resumable_uploads import COMPATIBILITY_MAX_BYTES
from trackio.utils import parse_trackio_server_url

HTTP_API_VERSION = 1
FORCE_SYNC_TIMEOUT = 180.0

WRITE_TOKEN_HEADER = "x-trackio-write-token"


def _normalize_src(src: str) -> str:
    return src if src.endswith("/") else src + "/"


def _space_id_to_url(space_id: str) -> str:
    namespace, name = space_id.split("/", 1)
    subdomain = f"{namespace}-{name}".lower().replace("_", "-").replace(".", "-")
    return f"https://{subdomain}.hf.space/"


def _host_is_hf_space(url: str) -> bool:
    p = urlparse(url)
    h = (p.hostname or "").lower()
    return h.endswith(".hf.space")


def _resolve_src_url(src: str) -> str:
    if src.startswith(("http://", "https://")):
        base, _ = parse_trackio_server_url(src)
        return _normalize_src(base)
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


def _merge_client_headers(
    hf_token: str | None, write_token: str | None
) -> dict[str, str]:
    headers: dict[str, str] = {}
    if hf_token:
        headers.update(build_hf_headers(token=hf_token))
    if write_token:
        headers[WRITE_TOKEN_HEADER] = write_token
    return headers


def _request_timeout_for_api(
    timeout: httpx.Timeout | float | int | None, api_name: str
) -> httpx.Timeout | float | int | None:
    if api_name != "force_sync":
        return timeout

    normalized = httpx.Timeout(timeout)
    read_timeout = normalized.read if normalized.read is not None else 0.0
    if read_timeout >= FORCE_SYNC_TIMEOUT:
        return timeout

    return httpx.Timeout(
        connect=normalized.connect,
        read=FORCE_SYNC_TIMEOUT,
        write=normalized.write,
        pool=normalized.pool,
    )


def is_transient_remote_error(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code >= 500
    return isinstance(exc, (httpx.RequestError, ConnectionError))


class _TrackioHTTPClient:
    def __init__(
        self,
        src: str,
        hf_token: str | None = None,
        write_token: str | None = None,
        httpx_kwargs: dict[str, Any] | None = None,
    ) -> None:
        self.src = _resolve_src_url(src)
        self.httpx_kwargs = dict(httpx_kwargs or {})
        self.httpx_kwargs.setdefault("timeout", 60)
        extra = self.httpx_kwargs.pop("headers", None)
        h = _merge_client_headers(hf_token, write_token)
        if isinstance(extra, dict):
            h.update({str(k): str(v) for k, v in extra.items()})
        self.headers = h
        self._artifact_upload_capabilities: dict[str, Any] | None = None

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
        request_kwargs = dict(self.httpx_kwargs)
        request_kwargs["timeout"] = _request_timeout_for_api(
            request_kwargs.get("timeout"), api_name
        )
        resp = httpx.post(
            urljoin(self.src, f"api/{api_name}"),
            headers=self.headers,
            json=payload,
            **request_kwargs,
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

    def _resumable_capabilities(self) -> dict[str, Any] | None:
        if self._artifact_upload_capabilities is not None:
            return self._artifact_upload_capabilities
        response = httpx.get(
            urljoin(self.src, "api/artifact-upload/capabilities"),
            headers=self.headers,
            **self.httpx_kwargs,
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        capabilities = response.json()
        if capabilities.get("resumable") is not True:
            return None
        self._artifact_upload_capabilities = capabilities
        return capabilities

    def upload_artifact_blob(self, project: str, digest: str, path: Path) -> bool:
        """Upload one blob through the resumable API.

        Returns ``False`` only when a legacy server can safely handle the small
        file through the compatibility path.
        """

        size_bytes = path.stat().st_size
        capabilities = self._resumable_capabilities()
        if capabilities is None:
            if size_bytes > COMPATIBILITY_MAX_BYTES:
                raise RuntimeError(
                    "The Trackio server does not support resumable artifact uploads; "
                    f"refusing to send {size_bytes} bytes through the legacy whole-file endpoint."
                )
            return False

        idempotency_key = hashlib.sha256(
            f"{project}\0{digest}".encode("utf-8")
        ).hexdigest()
        init_response = httpx.post(
            urljoin(self.src, f"api/artifact-upload/{project}"),
            headers=self.headers,
            json={
                "digest": digest,
                "size_bytes": size_bytes,
                "idempotency_key": idempotency_key,
            },
            **self.httpx_kwargs,
        )
        init_response.raise_for_status()
        session = init_response.json()
        upload_id = session["upload_id"]
        chunk_size = int(session["chunk_size_bytes"])
        acknowledged = {int(index) for index in session["acknowledged_chunks"]}
        with path.open("rb") as handle:
            for index in range(int(session["chunk_count"])):
                chunk = handle.read(chunk_size)
                if index in acknowledged:
                    continue
                chunk_digest = hashlib.sha256(chunk).hexdigest()
                response = httpx.put(
                    urljoin(
                        self.src,
                        f"api/artifact-upload/{project}/{upload_id}/chunks/{index}",
                    ),
                    headers={
                        **self.headers,
                        "x-trackio-chunk-sha256": chunk_digest,
                    },
                    content=chunk,
                    **self.httpx_kwargs,
                )
                response.raise_for_status()
        complete_response = httpx.post(
            urljoin(self.src, f"api/artifact-upload/{project}/{upload_id}"),
            headers=self.headers,
            **self.httpx_kwargs,
        )
        complete_response.raise_for_status()
        completed = complete_response.json()
        if completed.get("digest") != digest or completed.get("size_bytes") != size_bytes:
            raise RuntimeError("Trackio completed an artifact upload with the wrong identity.")
        return True


class _TrackioGradioCompatClient:
    def __init__(
        self,
        src: str,
        hf_token: str | None = None,
        write_token: str | None = None,
        httpx_kwargs: dict[str, Any] | None = None,
        verbose: bool = False,
    ) -> None:
        supported_params = inspect.signature(GradioClient.__init__).parameters
        kwargs: dict[str, Any] = {"verbose": verbose}
        if hf_token:
            if "hf_token" in supported_params:
                kwargs["hf_token"] = hf_token
            elif "token" in supported_params:
                kwargs["token"] = hf_token
        merged = dict(httpx_kwargs or {})
        h = _merge_client_headers(
            hf_token if hf_token else None,
            write_token,
        )
        extra = merged.pop("headers", None)
        if isinstance(extra, dict):
            h.update({str(k): str(v) for k, v in extra.items()})
        if h:
            if "headers" in supported_params:
                kwargs["headers"] = h
            elif "httpx_kwargs" in supported_params:
                merged["headers"] = h
        if merged and "httpx_kwargs" in supported_params:
            kwargs["httpx_kwargs"] = merged
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

    def upload_artifact_blob(self, project: str, digest: str, path: Path) -> bool:
        if path.stat().st_size > COMPATIBILITY_MAX_BYTES:
            raise RuntimeError(
                "The Trackio server does not support resumable artifact uploads; "
                f"refusing to send {path.stat().st_size} bytes through the legacy whole-file endpoint."
            )
        return False


def _raise_if_space_is_building(space_id: str) -> None:
    """
    GradioClient.__init__ blocks in an unbounded loop while a Space is in the
    BUILDING stage, which would make the caller unresponsive to trackio's stop
    flag. Fail fast instead so callers can retry on their own schedule.
    """
    try:
        info = huggingface_hub.HfApi().space_info(space_id, timeout=30)
        stage = str(info.runtime.stage) if info.runtime else None
    except Exception:
        return
    if stage == "BUILDING":
        raise ConnectionError(f"Space '{space_id}' is still building.")


def _supports_http_api(
    src: str,
    hf_token: str | None = None,
    write_token: str | None = None,
    httpx_kwargs: dict[str, Any] | None = None,
) -> bool:
    url = _resolve_src_url(src)
    headers = _merge_client_headers(hf_token, write_token)
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
        write_token: str | None = None,
        httpx_kwargs: dict[str, Any] | None = None,
        verbose: bool = False,
    ) -> None:
        self._space = space
        src_for_resolve = space
        hf_effective = hf_token
        wt_effective = write_token
        if space.startswith(("http://", "https://")):
            base, url_tok = parse_trackio_server_url(space)
            src_for_resolve = base
            if wt_effective is None:
                wt_effective = url_tok
            if not _host_is_hf_space(_normalize_src(base)):
                hf_effective = None
        try:
            if _supports_http_api(
                src_for_resolve,
                hf_token=hf_effective,
                write_token=wt_effective,
                httpx_kwargs=httpx_kwargs,
            ):
                self._client = _TrackioHTTPClient(
                    src_for_resolve,
                    hf_token=hf_effective,
                    write_token=wt_effective,
                    httpx_kwargs=httpx_kwargs,
                )
            else:
                if not src_for_resolve.startswith(("http://", "https://")):
                    _raise_if_space_is_building(src_for_resolve)
                self._client = _TrackioGradioCompatClient(
                    src_for_resolve,
                    hf_token=hf_effective,
                    write_token=wt_effective,
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

    def upload_artifact_blob(self, project: str, digest: str, path: Path) -> bool:
        return self._client.upload_artifact_blob(project, digest, path)
