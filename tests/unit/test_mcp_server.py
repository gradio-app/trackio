"""Tests to ensure MCP server endpoints are properly registered."""

from trackio.server import make_trackio_server

EXPECTED_MCP_TOOLS = [
    "get_all_projects",
    "get_project_summary",
    "get_run_summary",
    "get_runs_for_project",
    "get_metrics_for_run",
    "get_metric_values",
    "get_logs",
    "get_snapshot",
    "get_alerts",
    "get_system_metrics_for_run",
    "get_system_logs",
]


def test_mcp_tools_available_after_launch():
    server = make_trackio_server()
    server.launch(
        prevent_thread_lock=True,
        quiet=True,
        mcp_server=True,
    )
    try:
        blocks = server.blocks
        assert blocks is not None
        assert blocks.mcp_server is True
        assert blocks.mcp_server_obj is not None
        registered_tools = set(blocks.mcp_server_obj.tool_to_endpoint.keys())
        for tool in EXPECTED_MCP_TOOLS:
            assert any(tool in t for t in registered_tools), (
                f"MCP tool '{tool}' not found in registered tools: {registered_tools}"
            )
    finally:
        server.close()
