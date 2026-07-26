"""Real-process producer test for resumable self-hosted artifact transport."""

from __future__ import annotations

import hashlib
import json
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import httpx
import pytest

import trackio
import trackio.remote_client as remote_client_module
from trackio.remote_client import RemoteClient


def _free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _wait_ready(url: str, process: subprocess.Popen[str]) -> None:
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if process.poll() is not None:
            stdout, stderr = process.communicate()
            raise RuntimeError(
                f"Trackio server exited early: stdout={stdout[-1000:]} stderr={stderr[-1000:]}"
            )
        try:
            response = httpx.get(f"{url}/version", timeout=1)
            if response.status_code == 200:
                return
        except httpx.RequestError:
            pass
        time.sleep(0.05)
    raise TimeoutError("Trackio server did not become ready")


def _start_server(
    *,
    server_dir: Path,
    port: int,
    token: str,
) -> subprocess.Popen[str]:
    environment = {
        **os.environ,
        "TRACKIO_DIR": str(server_dir),
        "TRACKIO_WRITE_TOKEN": token,
    }
    return subprocess.Popen(
        [
            sys.executable,
            "-c",
            (
                "import trackio; "
                f"trackio.show(open_browser=False, block_thread=True, host='127.0.0.1', server_port={port})"
            ),
        ],
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def _stop_server(server: subprocess.Popen[str]) -> None:
    server.terminate()
    try:
        server.wait(timeout=10)
    except subprocess.TimeoutExpired:
        server.kill()
        server.wait(timeout=5)


def _rss_bytes(pid: int) -> int:
    status = Path(f"/proc/{pid}/status").read_text()
    for line in status.splitlines():
        if line.startswith("VmRSS:"):
            return int(line.split()[1]) * 1024
    raise RuntimeError(f"VmRSS is unavailable for pid {pid}")


def _write_deterministic(path: Path, size_bytes: int) -> str:
    chunk = (b"trackio-resumable-e2e-" * 65536)[: 1024 * 1024]
    sha = hashlib.sha256()
    remaining = size_bytes
    with path.open("wb") as handle:
        while remaining:
            payload = chunk[: min(remaining, len(chunk))]
            handle.write(payload)
            sha.update(payload)
            remaining -= len(payload)
    return sha.hexdigest()


def _run_process_round_trip(
    *,
    temp_dir: str,
    tmp_path: Path,
    monkeypatch,
    size_bytes: int,
    project: str,
) -> dict[str, int]:
    server_dir = tmp_path / "server"
    server_dir.mkdir()
    port = _free_port()
    url = f"http://127.0.0.1:{port}"
    token = "qualification-only-token"
    server = _start_server(server_dir=server_dir, port=port, token=token)
    source = tmp_path / "weights.bin"
    digest = _write_deterministic(source, size_bytes)
    stop_monitor = threading.Event()
    baseline_rss = 0
    peak_rss = 0

    def monitor_server() -> None:
        nonlocal peak_rss
        while not stop_monitor.wait(0.005):
            peak_rss = max(peak_rss, _rss_bytes(server.pid))

    try:
        _wait_ready(url, server)
        baseline_rss = _rss_bytes(server.pid)
        peak_rss = baseline_rss
        monitor = threading.Thread(target=monitor_server, daemon=True)
        monitor.start()
        monkeypatch.setenv("TRACKIO_WRITE_TOKEN", token)
        run = trackio.init(
            project=project,
            name="producer",
            server_url=url,
            auto_log_cpu=False,
            auto_log_gpu=False,
            embed=False,
        )
        artifact = trackio.log_artifact(source, name="model", type="model")
        trackio.finish()

        assert artifact.version == "v0"
        assert run.id
        readback_sha = hashlib.sha256()
        readback_size = 0
        with httpx.stream(
            "GET",
            f"{url}/artifact_blob/{project}/{digest}",
            timeout=300,
        ) as response:
            response.raise_for_status()
            for chunk in response.iter_bytes():
                readback_sha.update(chunk)
                readback_size += len(chunk)
        assert readback_sha.hexdigest() == digest
        assert readback_size == size_bytes
        assert not (
            Path(temp_dir)
            / "artifacts"
            / project
            / "blobs"
            / "sha256"
            / digest[:2]
            / digest
        ).samefile(server_dir / "artifacts" / project / "blobs" / "sha256" / digest[:2] / digest)
        stop_monitor.set()
        monitor.join(timeout=2)
        return {
            "server_baseline_rss_bytes": baseline_rss,
            "server_peak_rss_bytes": peak_rss,
            "server_peak_delta_bytes": peak_rss - baseline_rss,
        }
    finally:
        stop_monitor.set()
        _stop_server(server)


def test_remote_log_artifact_uses_distinct_server_storage(
    temp_dir,
    tmp_path,
    monkeypatch,
):
    _run_process_round_trip(
        temp_dir=temp_dir,
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        size_bytes=16 * 1024 * 1024 + 17,
        project="process-resumable",
    )


@pytest.mark.skipif(
    os.environ.get("TRACKIO_LARGE_ARTIFACT_TEST") != "1",
    reason="set TRACKIO_LARGE_ARTIFACT_TEST=1 for the 512 MiB transport gate",
)
def test_remote_log_artifact_round_trips_512_mib(
    temp_dir,
    tmp_path,
    monkeypatch,
):
    evidence = _run_process_round_trip(
        temp_dir=temp_dir,
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        size_bytes=512 * 1024 * 1024,
        project="process-resumable-large",
    )
    print(json.dumps(evidence, sort_keys=True))
    assert evidence["server_peak_delta_bytes"] < 128 * 1024 * 1024


def test_client_resumes_after_server_process_restart(tmp_path, monkeypatch):
    server_dir = tmp_path / "server"
    server_dir.mkdir()
    port = _free_port()
    url = f"http://127.0.0.1:{port}"
    token = "qualification-only-token"
    project = "process-restart-resume"
    source = tmp_path / "weights.bin"
    digest = _write_deterministic(source, 16 * 1024 * 1024 + 17)
    server = _start_server(server_dir=server_dir, port=port, token=token)
    _wait_ready(url, server)
    client = RemoteClient(url, write_token=token, verbose=False)
    real_put = remote_client_module.httpx.put
    puts = 0

    def disconnect_second_chunk(*args, **kwargs):
        nonlocal puts
        puts += 1
        if puts == 2:
            request = httpx.Request("PUT", str(args[0]))
            raise httpx.ConnectError("synthetic disconnect", request=request)
        return real_put(*args, **kwargs)

    try:
        monkeypatch.setattr(
            remote_client_module.httpx,
            "put",
            disconnect_second_chunk,
        )
        with pytest.raises(httpx.ConnectError, match="synthetic disconnect"):
            client.upload_artifact_blob(project, digest, source)
        _stop_server(server)

        monkeypatch.setattr(remote_client_module.httpx, "put", real_put)
        server = _start_server(server_dir=server_dir, port=port, token=token)
        _wait_ready(url, server)
        resumed = RemoteClient(url, write_token=token, verbose=False)

        assert resumed.upload_artifact_blob(project, digest, source) is True
        readback_sha = hashlib.sha256()
        with httpx.stream(
            "GET",
            f"{url}/artifact_blob/{project}/{digest}",
            timeout=30,
        ) as response:
            response.raise_for_status()
            for chunk in response.iter_bytes():
                readback_sha.update(chunk)
        assert readback_sha.hexdigest() == digest
    finally:
        if server.poll() is None:
            _stop_server(server)
