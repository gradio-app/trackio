import asyncio
import tempfile
from pathlib import Path

import httpx
import pytest

import trackio
import trackio.utils as trackio_utils
from trackio import Api
from trackio.remote_client import RemoteClient as Client
from trackio.sqlite_storage import SQLiteStorage


def test_delete_run(temp_dir):
    project = "test_delete_project"
    run_name = "test_delete_run"

    trackio.init(project=project, name=run_name)
    trackio.log(metrics={"loss": 0.1, "accuracy": 0.9})
    trackio.log(metrics={"loss": 0.2, "accuracy": 0.95})
    trackio.finish()

    logs = SQLiteStorage.get_logs(project=project, run=run_name)
    assert len(logs) == 2
    assert logs[0]["loss"] == 0.1
    assert logs[1]["loss"] == 0.2

    api = Api()
    runs = api.runs(project)
    run = runs[0]
    assert run.name == run_name

    success = run.delete()
    assert success is True

    logs_after = SQLiteStorage.get_logs(project=project, run=run_name)
    assert len(logs_after) == 0

    config_after = SQLiteStorage.get_run_config(project=project, run=run_name)
    assert config_after is None

    runs_after = SQLiteStorage.get_runs(project=project)
    assert run_name not in runs_after


def test_move_run(temp_dir, image_ndarray):
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
    normalized_path = str(image1_path).replace("\\", "/")
    assert normalized_path.startswith(f"{source_project}/{run_name}/")

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
    normalized_path1 = str(target_image1_path).replace("\\", "/")
    assert normalized_path1.startswith(f"{target_project}/{run_name}/")

    target_image2_path = target_logs[1]["img2"].get("file_path")
    assert target_image2_path is not None
    normalized_path2 = str(target_image2_path).replace("\\", "/")
    assert normalized_path2.startswith(f"{target_project}/{run_name}/")

    source_logs_after = SQLiteStorage.get_logs(project=source_project, run=run_name)
    assert len(source_logs_after) == 0

    source_runs_after = SQLiteStorage.get_runs(project=source_project)
    assert run_name not in source_runs_after
    assert len(source_runs_after) == 0

    target_runs = SQLiteStorage.get_runs(project=target_project)
    assert run_name in target_runs

    source_config_after = SQLiteStorage.get_run_config(
        project=source_project, run=run_name
    )
    assert source_config_after is None

    target_config = SQLiteStorage.get_run_config(project=target_project, run=run_name)
    assert target_config is not None


def test_rename_run(temp_dir, image_ndarray):
    project = "test_rename_project"
    old_name = "old_run_name"
    new_name = "new_run_name"

    trackio.init(project=project, name=old_name)

    image1 = trackio.Image(image_ndarray, caption="test_image_1")
    image2 = trackio.Image(image_ndarray, caption="test_image_2")

    trackio.log(metrics={"loss": 0.1, "acc": 0.9, "img1": image1})
    trackio.log(metrics={"loss": 0.2, "acc": 0.95, "img2": image2})
    trackio.finish()

    old_logs = SQLiteStorage.get_logs(project=project, run=old_name)
    assert len(old_logs) == 2
    assert old_logs[0]["loss"] == 0.1
    assert old_logs[1]["loss"] == 0.2

    image1_path = old_logs[0]["img1"].get("file_path")
    assert image1_path is not None
    normalized_path = str(image1_path).replace("\\", "/")
    assert normalized_path.startswith(f"{project}/{old_name}/")

    api = Api()
    runs = api.runs(project)
    run = runs[0]
    assert run.name == old_name

    result = run.rename(new_name)
    assert result is run
    assert run.name == new_name

    new_logs = SQLiteStorage.get_logs(project=project, run=new_name)
    assert len(new_logs) == 2
    assert new_logs[0]["loss"] == 0.1
    assert new_logs[1]["loss"] == 0.2

    new_image1_path = new_logs[0]["img1"].get("file_path")
    assert new_image1_path is not None
    normalized_new_path1 = str(new_image1_path).replace("\\", "/")
    assert normalized_new_path1.startswith(f"{project}/{new_name}/")

    new_image2_path = new_logs[1]["img2"].get("file_path")
    assert new_image2_path is not None
    normalized_new_path2 = str(new_image2_path).replace("\\", "/")
    assert normalized_new_path2.startswith(f"{project}/{new_name}/")

    old_logs_after = SQLiteStorage.get_logs(project=project, run=old_name)
    assert len(old_logs_after) == 0

    runs_after = SQLiteStorage.get_runs(project=project)
    assert old_name not in runs_after
    assert new_name in runs_after

    old_config_after = SQLiteStorage.get_run_config(project=project, run=old_name)
    assert old_config_after is None

    new_config = SQLiteStorage.get_run_config(project=project, run=new_name)
    assert new_config is not None


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


def test_trackio_url_logs_to_self_hosted_server(temp_dir):
    from urllib.parse import parse_qs, urlparse

    import trackio.context_vars as context_vars

    project = "test_self_hosted"
    run_name = "self-hosted-run"

    app, url, _, full_url = trackio.show(block_thread=False, open_browser=False)

    try:
        write_token = parse_qs(urlparse(full_url).query).get("write_token", [None])[0]
        assert write_token

        context_vars.current_server.set(None)
        context_vars.current_project.set(None)
        context_vars.current_run.set(None)

        trackio.init(project=project, name=run_name, trackio_url=full_url)
        trackio.log(metrics={"loss": 0.5})
        trackio.finish()

        client = Client(url, verbose=False)
        runs = client.predict(project, api_name="/get_runs_for_project")
        assert any(r.get("name") == run_name for r in runs)
    finally:
        app.close()


def test_trackio_url_rejects_non_url_value(temp_dir):
    with pytest.raises(ValueError, match="full URL"):
        trackio.init(project="x", trackio_url="not-a-url")


def test_trackio_url_mutually_exclusive_with_space_id(temp_dir):
    with pytest.raises(ValueError, match="Cannot provide both"):
        trackio.init(project="x", space_id="u/s", trackio_url="http://localhost:1")


def test_local_dashboard_returns_400_for_missing_required_parameter(temp_dir):
    app, url, _, _ = trackio.show(block_thread=False, open_browser=False)

    try:
        resp = httpx.post(
            f"{url.rstrip('/')}/api/get_runs_for_project",
            json={},
            timeout=5,
        )

        assert resp.status_code == 400
        assert resp.json() == {"error": "Missing required parameter: project"}
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
        allowed_resp = httpx.get(
            f"{url.rstrip('/')}/file",
            params={"path": str(allowed_path)},
            timeout=5,
        )
        blocked_resp = httpx.get(
            f"{url.rstrip('/')}/file",
            params={"path": "/etc/hosts"},
            timeout=5,
        )

        assert allowed_resp.status_code == 200
        assert blocked_resp.status_code == 404
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

    app, url, _, _ = trackio.show(block_thread=False, open_browser=False)

    try:
        with source_path.open("rb") as handle:
            upload_resp = httpx.post(
                f"{url.rstrip('/')}/api/upload",
                files={"files": (source_path.name, handle)},
                timeout=5,
            )
        upload_resp.raise_for_status()
        uploaded_path = upload_resp.json()["paths"][0]
        allowed_target = (
            trackio_utils.MEDIA_DIR
            / project
            / "files"
            / "allowed.txt"
            / Path(uploaded_path).name
        )

        allowed_resp = httpx.post(
            f"{url.rstrip('/')}/api/bulk_upload_media",
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
        blocked_resp = httpx.post(
            f"{url.rstrip('/')}/api/bulk_upload_media",
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

        assert allowed_resp.status_code == 200
        assert allowed_target is not None
        assert allowed_target.read_text() == source_text
        assert blocked_resp.status_code == 400
        assert blocked_resp.json() == {
            "error": "Uploaded file was not created by this Trackio server."
        }
        assert not blocked_target.exists()
    finally:
        source_path.unlink(missing_ok=True)
        trackio.delete_project(project, force=True)
        app.close()


def test_local_dashboard_supports_mcp(temp_dir):
    pytest.importorskip("mcp")

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
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client

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
