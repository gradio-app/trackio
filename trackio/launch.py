from __future__ import annotations

import os
import secrets
import socket
import threading
import time
import warnings
from typing import Any

import httpx
import uvicorn
from uvicorn.config import Config

from trackio.launch_utils import colab_check, is_hosted_notebook

INITIAL_PORT_VALUE = int(os.getenv("GRADIO_SERVER_PORT", "7860"))
TRY_NUM_PORTS = int(os.getenv("GRADIO_NUM_PORTS", "100"))
LOCALHOST_NAME = os.getenv("GRADIO_SERVER_NAME", "127.0.0.1")


class _UvicornServer(uvicorn.Server):
    def install_signal_handlers(self) -> None:
        pass

    def run_in_thread(self) -> None:
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()
        start = time.time()
        while not self.started:
            time.sleep(1e-3)
            if time.time() - start > 60:
                raise RuntimeError(
                    "Server failed to start. Please check that the port is available."
                )


def _bind_host(server_name: str) -> str:
    if server_name.startswith("[") and server_name.endswith("]"):
        return server_name[1:-1]
    return server_name


def start_server(
    app: Any,
    server_name: str | None = None,
    server_port: int | None = None,
    ssl_keyfile: str | None = None,
    ssl_certfile: str | None = None,
    ssl_keyfile_password: str | None = None,
) -> tuple[str, int, str, _UvicornServer]:
    server_name = server_name or LOCALHOST_NAME
    url_host_name = "localhost" if server_name == "0.0.0.0" else server_name

    host = _bind_host(server_name)

    server_ports = (
        [server_port]
        if server_port is not None
        else range(INITIAL_PORT_VALUE, INITIAL_PORT_VALUE + TRY_NUM_PORTS)
    )

    port_used = None
    server = None
    for port in server_ports:
        try:
            s = socket.socket()
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((LOCALHOST_NAME, port))
            s.close()
            config = Config(
                app=app,
                port=port,
                host=host,
                log_level="warning",
                ssl_keyfile=ssl_keyfile,
                ssl_certfile=ssl_certfile,
                ssl_keyfile_password=ssl_keyfile_password,
            )
            server = _UvicornServer(config=config)
            server.run_in_thread()
            port_used = port
            break
        except (OSError, RuntimeError):
            continue
    else:
        raise OSError(
            f"Cannot find empty port in range: {min(server_ports)}-{max(server_ports)}. "
            "Set GRADIO_SERVER_PORT or pass server_port to trackio.show()."
        )

    assert port_used is not None and server is not None

    if ssl_keyfile is not None:
        path_to_local_server = f"https://{url_host_name}:{port_used}/"
    else:
        path_to_local_server = f"http://{url_host_name}:{port_used}/"

    return server_name, port_used, path_to_local_server, server


def launch_trackio_dashboard(
    starlette_app: Any,
    *,
    server_name: str | None = None,
    server_port: int | None = None,
    share: bool | None = None,
    share_server_address: str | None = None,
    share_server_protocol: str | None = None,
    share_server_tls_certificate: str | None = None,
    mcp_server: bool = False,
    ssl_verify: bool = True,
    quiet: bool = False,
) -> tuple[str | None, str | None, str | None, Any]:
    from pathlib import Path

    from trackio._vendor.networking import normalize_share_url, setup_tunnel
    from trackio._vendor.tunneling import BINARY_PATH

    is_colab = colab_check()
    is_hosted_nb = is_hosted_notebook()
    space_id = os.getenv("SPACE_ID")

    if share is None:
        if is_colab or is_hosted_nb:
            if not quiet:
                print(
                    "It looks like you are running Trackio on a hosted Jupyter notebook, which requires "
                    "`share=True`. Automatically setting `share=True` "
                    "(set `share=False` in `show()` to disable).\n"
                )
            share = True
        else:
            share = os.getenv("GRADIO_SHARE", "").lower() == "true"

    sn = server_name
    if sn is None and os.getenv("SYSTEM") == "spaces":
        sn = "0.0.0.0"
    elif sn is None:
        sn = LOCALHOST_NAME

    server_name_r, server_port_r, local_url, uv_server = start_server(
        starlette_app,
        server_name=sn,
        server_port=server_port,
    )

    local_api_url = f"{local_url.rstrip('/')}/api/"
    try:
        httpx.get(f"{local_url.rstrip('/')}/version", verify=ssl_verify, timeout=10)
    except Exception as e:
        raise RuntimeError(
            f"Could not reach Trackio server at {local_url.rstrip('/')}/version: {e}"
        ) from e

    if share and space_id:
        warnings.warn("Setting share=True is not supported on Hugging Face Spaces")
        share = False

    share_url: str | None = None
    if share:
        try:
            share_tok = secrets.token_urlsafe(32)
            proto = share_server_protocol or (
                "http" if share_server_address is not None else "https"
            )
            raw = setup_tunnel(
                local_host=server_name_r,
                local_port=server_port_r,
                share_token=share_tok,
                share_server_address=share_server_address,
                share_server_tls_certificate=share_server_tls_certificate,
            )
            share_url = normalize_share_url(raw, proto)
            if not quiet:
                print(f"* Running on public URL: {share_url}")
                print(
                    "\nThis share link expires in 1 week. For permanent hosting, deploy to Hugging Face Spaces."
                )
        except Exception as e:
            share_url = None
            if not quiet:
                from trackio._vendor.gradio_exceptions import ChecksumMismatchError

                if isinstance(e, ChecksumMismatchError):
                    print(
                        "\nCould not create share link. Checksum mismatch for frpc binary."
                    )
                elif Path(BINARY_PATH).exists():
                    print(
                        "\nCould not create share link. Check your internet connection or https://status.gradio.app."
                    )
                else:
                    print(
                        f"\nCould not create share link. Missing frpc at {BINARY_PATH}. {e}"
                    )

    if not share_url and not quiet:
        print("* To create a public link, set `share=True` in `trackio.show()`.")

    return local_url, share_url, local_api_url, uv_server


def url_ok_local(local_url: str) -> bool:
    from trackio._vendor.networking import url_ok

    return url_ok(local_url)
