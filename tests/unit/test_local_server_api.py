import asyncio
import tempfile
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

import trackio
import trackio.context_vars as context_vars
import trackio.utils as trackio_utils
from trackio import Api
from trackio.remote_client import RemoteClient as Client
from trackio.sqlite_storage import SQLiteStorage


def test_move_run_via_api_updates_media_paths(temp_dir, image_ndarray):
    source_project = "test_move_source"
    target_project = "test_move_target"
    run_name = "test_move_run"

    trackio.init(project=source_project, name=run_name)

    image1 = trackio.Image(image_ndarray, caption="test_image_1")
    image2 = trackio.Image(image_ndarray, caption="test_image_2")

    trackio.log(metrics={"loss": 0.1, "acc": 0.9, "img1": image1})
    trackio.log(metrics={"loss": 0.2, "acc": 0.95, "img2": image2})
    trackio.finish()

    source_logs = SQLiteStorage.get_logs(project=source_project, run=run_name)
    assert len(source_logs) == 2
    assert source_logs[0]["loss"] == 0.1
    assert source_logs[1]["loss"] == 0.2

    image1_path = source_logs[0]["img1"].get("file_path")
    assert image1_path is not None
    assert str(image1_path).replace("\\", "/").startswith(f"{source_project}/{run_name}/")

    api = Api()
    runs = api.runs(source_project)
    run = runs[0]
    assert run.name == run_name
    assert run.project == source_project

    success = run.move(target_project)
    assert success is True
    assert run.project == target_project

    target_logs = SQLiteStorage.get_logs(project=target_project, run=run_name)
    assert len(target_logs) == 2
    assert target_logs[0]["loss"] == 0.1
    assert target_logs[1]["loss"] == 0.2

    target_image1_path = target_logs[0]["img1"].get("file_path")
    assert target_image1_path is not None
    assert str(target_image1_path).replace("\\", "/").startswith(
        f"{target_project}/{run_name}/"
    )

    target_image2_path = target_logs[1]["img2"].get("file_path")
    assert target_image2_path is not None
    assert str(target_image2_path).replace("\\", "/").startswith(
        f"{target_project}/{run_name}/"
    )

    assert SQLiteStorage.get_logs(project=source_project, run=run_name) == []
    assert SQLiteStorage.get_run_config(project=source_project, run=run_name) is None
    assert run_name in SQLiteStorage.get_runs(project=target_project)


def test_local_dashboard_supports_remote_client(temp_dir):
    project = "test_local_client"
    run_name = "client-run"

    trackio.init(project=project, name=run_name)
    trackio.log(metrics={"loss": 0.1})
    trackio.finish()

    app, url, _, _ = trackio.show(block_thread=False, open_browser=False)

    try:
        client = Client(url, verbose=False)
        projects = client.predict(api_name="/get_all_projects")
        runs = client.predict(project, api_name="/get_runs_for_project")
        settings = client.predict(api_name="/get_settings")

        assert project in projects
        assert len(runs) == 1
        assert runs[0]["name"] == run_name
        assert "logo_urls" in settings
    finally:
        trackio.delete_project(project, force=True)
        app.close()


def test_server_url_logs_to_self_hosted_server(temp_dir):
    project = "test_self_hosted"
    run_name = "self-hosted-run"

    app, url, _, full_url = trackio.show(block_thread=False, open_browser=False)

    try:
        write_token = parse_qs(urlparse(full_url).query).get("write_token", [None])[0]
        assert write_token

        context_vars.current_server.set(None)
        context_vars.current_project.set(None)
        context_vars.current_run.set(None)

        trackio.init(project=project, name=run_name, server_url=full_url)
        trackio.log(metrics={"loss": 0.5})
        trackio.finish()

        client = Client(url, verbose=False)
        runs = client.predict(project, api_name="/get_runs_for_project")
        assert any(r.get("name") == run_name for r in runs)
    finally:
        app.close()


def test_local_dashboard_returns_400_for_missing_required_parameter(temp_dir):
    app, url, _, _ = trackio.show(block_thread=False, open_browser=False)

    try:
        response = httpx.post(
            f"{url.rstrip('/')}/api/get_runs_for_project",
            json={},
            timeout=5,
        )

        assert response.status_code == 400
        assert response.json() == {"error": "Missing required parameter: project"}
    finally:
        app.close()


def test_local_dashboard_file_endpoint_only_serves_trackio_paths(
    temp_dir, image_ndarray
):
    project = "test_local_file_endpoint"
    run_name = "file-run"

    trackio.init(project=project, name=run_name)
    trackio.log(metrics={"image": trackio.Image(image_ndarray, caption="allowed")})
    trackio.finish()

    logs = SQLiteStorage.get_logs(project=project, run=run_name)
    rel_path = logs[0]["image"]["file_path"]
    allowed_path = trackio_utils.MEDIA_DIR / rel_path

    app, url, _, _ = trackio.show(block_thread=False, open_browser=False)

    try:
        allowed_response = httpx.get(
            f"{url.rstrip('/')}/file",
            params={"path": str(allowed_path)},
            timeout=5,
        )
        blocked_response = httpx.get(
            f"{url.rstrip('/')}/file",
            params={"path": "/etc/hosts"},
            timeout=5,
        )

        assert allowed_response.status_code == 200
        assert blocked_response.status_code == 404
    finally:
        trackio.delete_project(project, force=True)
        app.close()


def test_local_dashboard_upload_api_accepts_only_server_uploaded_paths(temp_dir):
    project = "test_local_upload_guard"
    source_path = Path(tempfile.gettempdir()) / "trackio-upload-source.txt"
    source_text = "uploaded through server"
    source_path.write_text(source_text)
    blocked_target = trackio_utils.MEDIA_DIR / project / "files" / "blocked.txt"
    allowed_target = None

    app, url, _, full_url = trackio.show(block_thread=False, open_browser=False)
    write_token = parse_qs(urlparse(full_url).query).get("write_token", [None])[0]
    assert write_token
    write_headers = {"x-trackio-write-token": write_token}

    try:
        blocked_upload_response = httpx.post(
            f"{url.rstrip('/')}/api/upload",
            files={"files": (source_path.name, source_text.encode())},
            timeout=5,
        )
        assert blocked_upload_response.status_code == 400
        assert blocked_upload_response.json() == {
            "error": "A write_token is required to upload files to this server. Use the write-access URL from trackio.show(), set TRACKIO_WRITE_TOKEN, or send header X-Trackio-Write-Token."
        }

        with source_path.open("rb") as handle:
            upload_response = httpx.post(
                f"{url.rstrip('/')}/api/upload",
                headers=write_headers,
                files={"files": (source_path.name, handle)},
                timeout=5,
            )
        upload_response.raise_for_status()
        uploaded_path = upload_response.json()["paths"][0]
        allowed_target = (
            trackio_utils.MEDIA_DIR
            / project
            / "files"
            / "allowed.txt"
            / Path(uploaded_path).name
        )

        allowed_response = httpx.post(
            f"{url.rstrip('/')}/api/bulk_upload_media",
            headers=write_headers,
            json={
                "uploads": [
                    {
                        "project": project,
                        "run": None,
                        "step": None,
                        "relative_path": "allowed.txt",
                        "uploaded_file": {"path": uploaded_path},
                    }
                ],
                "hf_token": None,
            },
            timeout=5,
        )
        blocked_response = httpx.post(
            f"{url.rstrip('/')}/api/bulk_upload_media",
            headers=write_headers,
            json={
                "uploads": [
                    {
                        "project": project,
                        "run": None,
                        "step": None,
                        "relative_path": "blocked.txt",
                        "uploaded_file": {"path": "/etc/hosts"},
                    }
                ],
                "hf_token": None,
            },
            timeout=5,
        )

        assert allowed_response.status_code == 200
        assert allowed_target is not None
        assert allowed_target.read_text() == source_text
        assert not Path(uploaded_path).exists()
        assert blocked_response.status_code == 400
        assert blocked_response.json() == {
            "error": "Uploaded file was not created by this Trackio server."
        }
        assert not blocked_target.exists()
    finally:
        source_path.unlink(missing_ok=True)
        trackio.delete_project(project, force=True)
        app.close()


def test_local_dashboard_supports_mcp(temp_dir):
    pytest.importorskip("mcp")
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    project = "test_local_mcp"
    run_name = "mcp-run"

    trackio.init(project=project, name=run_name)
    trackio.log(metrics={"loss": 0.1})
    trackio.finish()

    app, url, _, _ = trackio.show(
        block_thread=False,
        open_browser=False,
        mcp_server=True,
    )

    async def check_mcp() -> None:
        async with streamable_http_client(f"{url.rstrip('/')}/mcp") as (
            read_stream,
            write_stream,
            _,
        ):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                tools = await session.list_tools()
                tool_names = {tool.name for tool in tools.tools}
                assert "get_all_projects" in tool_names
                assert "get_run_summary" in tool_names

                projects = await session.call_tool("get_all_projects")
                assert project in projects.structuredContent["result"]

                runs = await session.call_tool(
                    "get_runs_for_project",
                    {"project": project},
                )
                result = runs.structuredContent["result"]
                assert len(result) == 1
                assert result[0]["name"] == run_name

                run_summary = await session.call_tool(
                    "get_run_summary",
                    {"project": project, "run": run_name},
                )
                assert run_summary.structuredContent["run"] == run_name
                assert run_summary.structuredContent["num_logs"] == 1

    try:
        asyncio.run(check_mcp())
    finally:
        trackio.delete_project(project, force=True)
        app.close()
