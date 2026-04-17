from __future__ import annotations

import os
import secrets
from contextlib import asynccontextmanager
from typing import Any

from starlette.routing import Mount

from trackio.sqlite_storage import SQLiteStorage


def _assert_mcp_mutation_access(
    *,
    hf_token: str | None = None,
    write_token: str | None = None,
) -> None:
    import trackio.server as trackio_server  # noqa: PLC0415

    if os.getenv("SYSTEM") == "spaces":
        try:
            trackio_server.check_hf_token_has_write_access(hf_token)
        except PermissionError as e:
            raise ValueError(str(e)) from e
        return

    if not secrets.compare_digest(write_token or "", trackio_server.write_token or ""):
        raise ValueError(
            "A write_token is required for Trackio MCP mutations. "
            "Use the write token from the dashboard URL."
        )


def create_mcp_integration() -> tuple[list[Any], Any]:
    from mcp.server.fastmcp import FastMCP  # noqa: PLC0415

    import trackio.server as trackio_server  # noqa: PLC0415

    mcp = FastMCP(
        "Trackio",
        instructions="Inspect and manage Trackio experiment data.",
        streamable_http_path="/",
        log_level="WARNING",
    )

    mcp.add_tool(
        trackio_server.get_all_projects,
        description="List all Trackio projects available on this server.",
        structured_output=True,
    )
    mcp.add_tool(
        trackio_server.get_runs_for_project,
        description="List runs for a given Trackio project.",
        structured_output=True,
    )
    mcp.add_tool(
        trackio_server.get_metrics_for_run,
        description="List metric names recorded for a given Trackio run.",
        structured_output=True,
    )
    mcp.add_tool(
        trackio_server.get_project_summary,
        description="Return summary metadata for a Trackio project.",
        structured_output=True,
    )
    mcp.add_tool(
        trackio_server.get_run_summary,
        description="Return summary metadata for a Trackio run.",
        structured_output=True,
    )
    mcp.add_tool(
        trackio_server.get_metric_values,
        description="Fetch metric values for a run, optionally around a step or time.",
        structured_output=True,
    )
    mcp.add_tool(
        trackio_server.get_system_metrics_for_run,
        description="List system metric names recorded for a run.",
        structured_output=True,
    )
    mcp.add_tool(
        trackio_server.get_system_logs,
        description="Fetch system metric logs for a run.",
        structured_output=True,
    )
    mcp.add_tool(
        trackio_server.get_snapshot,
        description="Fetch a single Trackio snapshot around a step or timestamp.",
        structured_output=True,
    )
    mcp.add_tool(
        trackio_server.get_logs,
        description="Fetch Trackio metric logs for a run.",
        structured_output=True,
    )
    mcp.add_tool(
        trackio_server.get_alerts,
        description="Fetch alerts for a project, optionally filtered by run or level.",
        structured_output=True,
    )
    mcp.add_tool(
        trackio_server.get_settings,
        description="Return Trackio dashboard settings and asset configuration.",
        structured_output=True,
    )

    @mcp.tool(
        description="Delete a run. On Spaces, pass an hf_token with write access.",
        structured_output=True,
    )
    def delete_run(
        project: str,
        run: str,
        hf_token: str | None = None,
        write_token: str | None = None,
    ) -> bool:
        _assert_mcp_mutation_access(hf_token=hf_token, write_token=write_token)
        return SQLiteStorage.delete_run(project, run)

    @mcp.tool(
        description="Rename a run. On Spaces, pass an hf_token with write access.",
        structured_output=True,
    )
    def rename_run(
        project: str,
        old_name: str,
        new_name: str,
        hf_token: str | None = None,
        write_token: str | None = None,
    ) -> bool:
        _assert_mcp_mutation_access(hf_token=hf_token, write_token=write_token)
        SQLiteStorage.rename_run(project, old_name, new_name)
        return True

    @mcp.tool(
        description=(
            "Trigger a Trackio export/sync pass. On Spaces, pass an hf_token with "
            "write access."
        ),
        structured_output=True,
    )
    def trigger_sync(
        hf_token: str | None = None,
        write_token: str | None = None,
    ) -> bool:
        _assert_mcp_mutation_access(hf_token=hf_token, write_token=write_token)
        return trackio_server.force_sync()

    mcp_app = mcp.streamable_http_app()

    @asynccontextmanager
    async def mcp_lifespan_context(app):
        async with mcp.session_manager.run():
            yield

    return [Mount("/mcp", app=mcp_app)], mcp_lifespan_context
