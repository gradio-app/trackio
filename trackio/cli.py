import argparse
import os

import huggingface_hub

from trackio import freeze, show, sync
from trackio.cli_helpers import (
    error_exit,
    format_alerts,
    format_artifact,
    format_artifacts,
    format_json,
    format_list,
    format_metric_values,
    format_project_summary,
    format_query_result,
    format_run_summary,
    format_snapshot,
    format_spaces,
    format_system_metric_names,
    format_system_metrics,
)
from trackio.frontend_config import (
    TRACKIO_CONFIG_PATH,
    get_persisted_frontend_dir,
    set_persisted_frontend_dir,
    unset_persisted_frontend_dir,
)
from trackio.markdown import Markdown
from trackio.server import get_project_summary, get_run_summary
from trackio.sqlite_storage import SQLiteStorage


def _get_space(args):
    return getattr(args, "space", None)


def _get_remote(args):
    from trackio.remote_client import RemoteClient

    space = _get_space(args)
    if not space:
        return None
    hf_token = getattr(args, "hf_token", None)
    return RemoteClient(space, hf_token=hf_token)


def _handle_status():
    print("Reading local Trackio projects...\n")
    projects = SQLiteStorage.get_projects()
    if not projects:
        print("No Trackio projects found.")
        return

    local_projects = []
    synced_projects = []
    unsynced_projects = []

    for project in projects:
        space_id = SQLiteStorage.get_space_id(project)
        if space_id is None:
            local_projects.append(project)
        elif SQLiteStorage.has_pending_data(project):
            unsynced_projects.append(project)
        else:
            synced_projects.append(project)

    print("Finished reading Trackio projects")
    if local_projects:
        print(f"  * {len(local_projects)} local trackio project(s) [OK]")
    if synced_projects:
        print(f"  * {len(synced_projects)} trackio project(s) synced to Spaces [OK]")
    if unsynced_projects:
        print(
            f"  * {len(unsynced_projects)} trackio project(s) with unsynced changes [WARNING]:"
        )
        for p in unsynced_projects:
            print(f"    - {p}")

    if unsynced_projects:
        print(
            f"\nRun `trackio sync --project {unsynced_projects[0]}` to sync. "
            "Or run `trackio sync --all` to sync all unsynced changes."
        )


def _handle_sync(args):
    from trackio.deploy import sync_incremental

    if args.sync_all and args.project:
        error_exit("Cannot use --all and --project together.")
    if not args.sync_all and not args.project:
        error_exit("Must provide either --project or --all.")

    if args.sync_all:
        projects = SQLiteStorage.get_projects()
        synced_any = False
        for project in projects:
            space_id = SQLiteStorage.get_space_id(project)
            if space_id and SQLiteStorage.has_pending_data(project):
                sync_incremental(
                    project,
                    space_id,
                    private=args.private,
                    pending_only=True,
                    frontend_dir=args.frontend,
                )
                synced_any = True
        if not synced_any:
            print("No projects with unsynced data found.")
    else:
        space_id = args.space_id
        if space_id is None:
            space_id = SQLiteStorage.get_space_id(args.project)
        sync(
            project=args.project,
            space_id=space_id,
            private=args.private,
            force=args.force,
            sdk=args.sdk,
            frontend_dir=args.frontend,
        )


def _handle_config(args):
    if args.config_command == "get":
        frontend_dir = get_persisted_frontend_dir()
        if frontend_dir is None:
            print("No Trackio frontend config is set.")
            print(f"Config file: {TRACKIO_CONFIG_PATH}")
            return
        print(f"frontend: {frontend_dir}")
        print(f"config: {TRACKIO_CONFIG_PATH}")
        return

    if args.config_command == "set":
        try:
            frontend_dir = set_persisted_frontend_dir(args.frontend)
        except ValueError as e:
            error_exit(str(e))
        print(f"Saved Trackio default frontend: {frontend_dir}")
        print("Reset with `trackio config unset frontend`.")
        return

    if args.config_command == "unset":
        removed = unset_persisted_frontend_dir()
        if removed:
            print("Removed Trackio default frontend.")
        else:
            print("No Trackio default frontend was set.")
        return


def _extract_reports(
    run: str, logs: list[dict], report_name: str | None = None
) -> list[dict]:
    reports = []
    for log in logs:
        timestamp = log.get("timestamp")
        step = log.get("step")
        for key, value in log.items():
            if report_name is not None and key != report_name:
                continue
            if isinstance(value, dict) and value.get("_type") == Markdown.TYPE:
                content = value.get("_value")
                if isinstance(content, str):
                    reports.append(
                        {
                            "run": run,
                            "report": key,
                            "step": step,
                            "timestamp": timestamp,
                            "content": content,
                        }
                    )
    return reports


def _handle_query(args):
    remote = _get_remote(args)
    try:
        if remote:
            result = remote.predict(args.project, args.sql, api_name="/query_project")
        else:
            result = SQLiteStorage.query_project(args.project, args.sql)
    except FileNotFoundError as e:
        error_exit(str(e))
    except ValueError as e:
        error_exit(str(e))

    if args.json:
        print(format_json(result))
    else:
        print(format_query_result(result))


def _datetime_to_iso(value):
    return value.isoformat() if value is not None else None


def _space_url(space) -> str | None:
    host = getattr(space, "host", None)
    if host:
        return host if host.startswith("http") else f"https://{host}"

    subdomain = getattr(space, "subdomain", None)
    if subdomain:
        return f"https://{subdomain}.hf.space"

    space_id = getattr(space, "id", None)
    if not space_id:
        return None
    return f"https://huggingface.co/spaces/{space_id}"


def _serialize_space(space) -> dict:
    space_id = getattr(space, "id", "")
    namespace, _, name = space_id.partition("/")
    return {
        "id": space_id,
        "namespace": namespace,
        "name": name or space_id,
        "author": getattr(space, "author", None) or namespace,
        "private": bool(getattr(space, "private", False)),
        "sdk": getattr(space, "sdk", None),
        "url": _space_url(space),
        "last_modified": _datetime_to_iso(
            getattr(space, "last_modified", None)
            or getattr(space, "lastModified", None)
        ),
        "created_at": _datetime_to_iso(getattr(space, "created_at", None)),
        "tags": getattr(space, "tags", None) or [],
    }


def _trackio_space_namespaces(api, token: str | None, author: str | None) -> list[str]:
    if author:
        return [author]

    if not token:
        error_exit(
            "Log in with `huggingface-cli login`, pass `--hf-token`, or provide `--author`."
        )

    try:
        whoami = api.whoami(token=token, cache=True)
    except Exception as e:
        error_exit(f"Failed to read Hugging Face account information: {e}")

    namespaces = [whoami["name"]]
    for org in whoami.get("orgs", []):
        org_name = org.get("name") if isinstance(org, dict) else org
        if org_name:
            namespaces.append(org_name)

    return list(dict.fromkeys(namespaces))


def _handle_list_spaces(args):
    if _get_space(args):
        error_exit("The 'list spaces' command does not support --space.")
    if args.limit is not None and args.limit < 0:
        error_exit("--limit must be zero or greater.")

    token = args.hf_token or huggingface_hub.utils.get_token()
    api = huggingface_hub.HfApi(token=token)
    namespaces = _trackio_space_namespaces(api, token, args.author)

    spaces_by_id = {}
    try:
        for namespace in namespaces:
            spaces = api.list_spaces(
                author=namespace,
                filter="trackio",
                full=True,
                token=token,
            )
            for space in spaces:
                space_id = getattr(space, "id", None)
                if space_id:
                    spaces_by_id[space_id] = _serialize_space(space)
    except Exception as e:
        error_exit(f"Failed to list Trackio Spaces: {e}")

    spaces = sorted(
        spaces_by_id.values(),
        key=lambda space: space.get("last_modified") or "",
        reverse=True,
    )
    if args.limit is not None:
        spaces = spaces[: args.limit]

    if args.json:
        print(format_json({"spaces": spaces}))
    else:
        print(format_spaces(spaces))


def main():
    parser = argparse.ArgumentParser(description="Trackio CLI")
    parser.add_argument(
        "--space",
        required=False,
        help="HF Space ID (e.g. 'user/space') or Space URL to query remotely.",
    )
    parser.add_argument(
        "--hf-token",
        required=False,
        help="HF token for accessing private Spaces.",
    )
    subparsers = parser.add_subparsers(dest="command")

    ui_parser = subparsers.add_parser(
        "show", help="Show the Trackio dashboard UI for a project"
    )
    ui_parser.add_argument(
        "--project", required=False, help="Project name to show in the dashboard"
    )
    ui_parser.add_argument(
        "--theme",
        required=False,
        default="default",
        help="A Gradio Theme to use for the dashboard instead of the default, can be a built-in theme (e.g. 'soft', 'citrus'), or a theme from the Hub (e.g. 'gstaff/xkcd').",
    )
    ui_parser.add_argument(
        "--mcp-server",
        action="store_true",
        help="Enable MCP server functionality. The Trackio dashboard will be set up as an MCP server and certain functions will be exposed as MCP tools.",
    )
    ui_parser.add_argument(
        "--footer",
        action="store_true",
        default=True,
        help="Show the Gradio footer. Use --no-footer to hide it.",
    )
    ui_parser.add_argument(
        "--no-footer",
        dest="footer",
        action="store_false",
        help="Hide the Gradio footer.",
    )
    ui_parser.add_argument(
        "--color-palette",
        required=False,
        help="Comma-separated list of hex color codes for plot lines (e.g. '#FF0000,#00FF00,#0000FF'). If not provided, the TRACKIO_COLOR_PALETTE environment variable will be used, or the default palette if not set.",
    )
    ui_parser.add_argument(
        "--host",
        required=False,
        help="Host to bind the server to (e.g. '0.0.0.0' for remote access). If not provided, defaults to '127.0.0.1' (localhost only).",
    )
    ui_parser.add_argument(
        "--frontend",
        required=False,
        help="Custom frontend directory to serve. Must contain index.html.",
    )

    subparsers.add_parser(
        "status",
        help="Show the status of all local Trackio projects, including sync status.",
    )

    sync_parser = subparsers.add_parser(
        "sync",
        help="Sync a local project's database to a Hugging Face Space. If the Space does not exist, it will be created.",
    )
    sync_parser.add_argument(
        "--project",
        required=False,
        help="The name of the local project.",
    )
    sync_parser.add_argument(
        "--space-id",
        required=False,
        help="The Hugging Face Space ID where the project will be synced (e.g. username/space_id). If not provided, uses the previously-configured Space.",
    )
    sync_parser.add_argument(
        "--all",
        action="store_true",
        dest="sync_all",
        help="Sync all projects that have unsynced data to their configured Spaces.",
    )
    sync_parser.add_argument(
        "--private",
        action="store_true",
        help="Make the Hugging Face Space private if creating a new Space. By default, the repo will be public unless the organization's default is private. This value is ignored if the repo already exists.",
    )
    sync_parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite the existing database without prompting for confirmation.",
    )
    sync_parser.add_argument(
        "--sdk",
        choices=["gradio", "static"],
        default="gradio",
        help="The type of Space to deploy. 'gradio' (default) deploys a live Gradio server. 'static' deploys a static Space that reads from an HF Bucket.",
    )
    sync_parser.add_argument(
        "--frontend",
        required=False,
        help="Custom frontend directory to deploy. Must contain index.html.",
    )

    freeze_parser = subparsers.add_parser(
        "freeze",
        help="Create a one-time static Space snapshot from a project's data.",
    )
    freeze_parser.add_argument(
        "--space-id",
        required=True,
        help="The source Gradio Space ID (e.g. username/space_id).",
    )
    freeze_parser.add_argument(
        "--project",
        required=True,
        help="The name of the project to freeze into a static snapshot.",
    )
    freeze_parser.add_argument(
        "--new-space-id",
        required=False,
        help="The Space ID for the new static Space. Defaults to {space_id}_static.",
    )
    freeze_parser.add_argument(
        "--private",
        action="store_true",
        help="Make the new static Space private.",
    )
    freeze_parser.add_argument(
        "--frontend",
        required=False,
        help="Custom frontend directory to deploy to the frozen static Space.",
    )

    config_parser = subparsers.add_parser(
        "config",
        help="Manage persistent Trackio configuration.",
    )
    config_subparsers = config_parser.add_subparsers(
        dest="config_command",
        required=True,
    )
    config_subparsers.add_parser("get", help="Show current Trackio config.")
    config_set_parser = config_subparsers.add_parser(
        "set",
        help="Set a persistent Trackio config value.",
    )
    config_set_parser.add_argument(
        "key",
        choices=["frontend"],
        help="Config key to set.",
    )
    config_set_parser.add_argument(
        "frontend",
        help="Frontend directory to persist.",
    )
    config_unset_parser = config_subparsers.add_parser(
        "unset",
        help="Unset a persistent Trackio config value.",
    )
    config_unset_parser.add_argument(
        "key",
        choices=["frontend"],
        help="Config key to unset.",
    )

    list_parser = subparsers.add_parser(
        "list",
        help="List projects, runs, or metrics",
    )
    list_subparsers = list_parser.add_subparsers(dest="list_type", required=True)

    list_projects_parser = list_subparsers.add_parser(
        "projects",
        help="List all projects",
    )
    list_projects_parser.add_argument(
        "--json",
        action="store_true",
        help="Output in JSON format",
    )

    list_spaces_parser = list_subparsers.add_parser(
        "spaces",
        help="List Trackio Spaces for your Hugging Face account and organizations",
    )
    list_spaces_parser.add_argument(
        "--author",
        required=False,
        help="Only list Trackio Spaces under this user or organization namespace.",
    )
    list_spaces_parser.add_argument(
        "--limit",
        type=int,
        required=False,
        help="Maximum number of Spaces to return.",
    )
    list_spaces_parser.add_argument(
        "--json",
        action="store_true",
        help="Output in JSON format",
    )

    list_runs_parser = list_subparsers.add_parser(
        "runs",
        help="List runs for a project",
    )
    list_runs_parser.add_argument(
        "--project",
        required=True,
        help="Project name",
    )
    list_runs_parser.add_argument(
        "--json",
        action="store_true",
        help="Output in JSON format",
    )

    list_metrics_parser = list_subparsers.add_parser(
        "metrics",
        help="List metrics for a run",
    )
    list_metrics_parser.add_argument(
        "--project",
        required=True,
        help="Project name",
    )
    list_metrics_parser.add_argument(
        "--run",
        required=True,
        help="Run name",
    )
    list_metrics_parser.add_argument(
        "--json",
        action="store_true",
        help="Output in JSON format",
    )

    list_system_metrics_parser = list_subparsers.add_parser(
        "system-metrics",
        help="List system metrics for a run",
    )
    list_system_metrics_parser.add_argument(
        "--project",
        required=True,
        help="Project name",
    )
    list_system_metrics_parser.add_argument(
        "--run",
        required=True,
        help="Run name",
    )
    list_system_metrics_parser.add_argument(
        "--json",
        action="store_true",
        help="Output in JSON format",
    )

    list_alerts_parser = list_subparsers.add_parser(
        "alerts",
        help="List alerts for a project or run",
    )
    list_alerts_parser.add_argument(
        "--project",
        required=True,
        help="Project name",
    )
    list_alerts_parser.add_argument(
        "--run",
        required=False,
        help="Run name (optional)",
    )
    list_alerts_parser.add_argument(
        "--level",
        required=False,
        help="Filter by alert level (info, warn, error)",
    )
    list_alerts_parser.add_argument(
        "--json",
        action="store_true",
        help="Output in JSON format",
    )
    list_alerts_parser.add_argument(
        "--since",
        required=False,
        help="Only show alerts after this ISO 8601 timestamp",
    )

    list_reports_parser = list_subparsers.add_parser(
        "reports",
        help="List markdown reports for a project or run",
    )
    list_reports_parser.add_argument(
        "--project",
        required=True,
        help="Project name",
    )
    list_reports_parser.add_argument(
        "--run",
        required=False,
        help="Run name (optional)",
    )
    list_reports_parser.add_argument(
        "--json",
        action="store_true",
        help="Output in JSON format",
    )

    list_artifacts_parser = list_subparsers.add_parser(
        "artifacts",
        help="List artifacts for a project",
    )
    list_artifacts_parser.add_argument(
        "--project",
        required=True,
        help="Project name",
    )
    list_artifacts_parser.add_argument(
        "--json",
        action="store_true",
        help="Output in JSON format",
    )

    get_parser = subparsers.add_parser(
        "get",
        help="Get project, run, or metric information",
    )
    get_subparsers = get_parser.add_subparsers(dest="get_type", required=True)

    get_project_parser = get_subparsers.add_parser(
        "project",
        help="Get project summary",
    )
    get_project_parser.add_argument(
        "--project",
        required=True,
        help="Project name",
    )
    get_project_parser.add_argument(
        "--json",
        action="store_true",
        help="Output in JSON format",
    )

    get_run_parser = get_subparsers.add_parser(
        "run",
        help="Get run summary",
    )
    get_run_parser.add_argument(
        "--project",
        required=True,
        help="Project name",
    )
    get_run_parser.add_argument(
        "--run",
        required=True,
        help="Run name",
    )
    get_run_parser.add_argument(
        "--json",
        action="store_true",
        help="Output in JSON format",
    )

    get_artifact_parser = get_subparsers.add_parser(
        "artifact",
        help="Get an artifact version (manifest, aliases, metadata)",
    )
    get_artifact_parser.add_argument(
        "--project",
        required=True,
        help="Project name",
    )
    get_artifact_parser.add_argument(
        "--name",
        required=True,
        help="Artifact name",
    )
    get_artifact_parser.add_argument(
        "--version",
        required=False,
        help="Version or alias to resolve (e.g. 'v2' or 'best'). Defaults to latest.",
    )
    get_artifact_parser.add_argument(
        "--json",
        action="store_true",
        help="Output in JSON format",
    )

    get_metric_parser = get_subparsers.add_parser(
        "metric",
        help="Get metric values for a run",
    )
    get_metric_parser.add_argument(
        "--project",
        required=True,
        help="Project name",
    )
    get_metric_parser.add_argument(
        "--run",
        required=True,
        help="Run name",
    )
    get_metric_parser.add_argument(
        "--metric",
        required=True,
        help="Metric name",
    )
    get_metric_parser.add_argument(
        "--step",
        type=int,
        required=False,
        help="Get metric at exactly this step",
    )
    get_metric_parser.add_argument(
        "--around",
        type=int,
        required=False,
        help="Get metrics around this step (use with --window)",
    )
    get_metric_parser.add_argument(
        "--at-time",
        required=False,
        help="Get metrics around this ISO 8601 timestamp (use with --window)",
    )
    get_metric_parser.add_argument(
        "--window",
        type=int,
        required=False,
        default=10,
        help="Window size: ±steps for --around, ±seconds for --at-time (default: 10)",
    )
    get_metric_parser.add_argument(
        "--json",
        action="store_true",
        help="Output in JSON format",
    )

    get_snapshot_parser = get_subparsers.add_parser(
        "snapshot",
        help="Get all metrics at/around a step or timestamp",
    )
    get_snapshot_parser.add_argument(
        "--project",
        required=True,
        help="Project name",
    )
    get_snapshot_parser.add_argument(
        "--run",
        required=True,
        help="Run name",
    )
    get_snapshot_parser.add_argument(
        "--step",
        type=int,
        required=False,
        help="Get all metrics at exactly this step",
    )
    get_snapshot_parser.add_argument(
        "--around",
        type=int,
        required=False,
        help="Get all metrics around this step (use with --window)",
    )
    get_snapshot_parser.add_argument(
        "--at-time",
        required=False,
        help="Get all metrics around this ISO 8601 timestamp (use with --window)",
    )
    get_snapshot_parser.add_argument(
        "--window",
        type=int,
        required=False,
        default=10,
        help="Window size: ±steps for --around, ±seconds for --at-time (default: 10)",
    )
    get_snapshot_parser.add_argument(
        "--json",
        action="store_true",
        help="Output in JSON format",
    )

    get_system_metric_parser = get_subparsers.add_parser(
        "system-metric",
        help="Get system metric values for a run",
    )
    get_system_metric_parser.add_argument(
        "--project",
        required=True,
        help="Project name",
    )
    get_system_metric_parser.add_argument(
        "--run",
        required=True,
        help="Run name",
    )
    get_system_metric_parser.add_argument(
        "--metric",
        required=False,
        help="System metric name (optional, if not provided returns all system metrics)",
    )
    get_system_metric_parser.add_argument(
        "--json",
        action="store_true",
        help="Output in JSON format",
    )

    get_alerts_parser = get_subparsers.add_parser(
        "alerts",
        help="Get alerts for a project or run",
    )
    get_alerts_parser.add_argument(
        "--project",
        required=True,
        help="Project name",
    )
    get_alerts_parser.add_argument(
        "--run",
        required=False,
        help="Run name (optional)",
    )
    get_alerts_parser.add_argument(
        "--level",
        required=False,
        help="Filter by alert level (info, warn, error)",
    )
    get_alerts_parser.add_argument(
        "--json",
        action="store_true",
        help="Output in JSON format",
    )
    get_alerts_parser.add_argument(
        "--since",
        required=False,
        help="Only show alerts after this ISO 8601 timestamp",
    )

    get_report_parser = get_subparsers.add_parser(
        "report",
        help="Get markdown report entries for a run",
    )
    get_report_parser.add_argument(
        "--project",
        required=True,
        help="Project name",
    )
    get_report_parser.add_argument(
        "--run",
        required=True,
        help="Run name",
    )
    get_report_parser.add_argument(
        "--report",
        required=True,
        help="Report metric name",
    )
    get_report_parser.add_argument(
        "--json",
        action="store_true",
        help="Output in JSON format",
    )

    query_parser = subparsers.add_parser(
        "query",
        help="Run a read-only SQL query against a project database",
    )
    query_subparsers = query_parser.add_subparsers(dest="query_type", required=True)
    query_project_parser = query_subparsers.add_parser(
        "project",
        help="Run a read-only SQL query against a project's SQLite database",
    )
    query_project_parser.add_argument(
        "--project",
        required=True,
        help="Project name",
    )
    query_project_parser.add_argument(
        "--sql",
        required=True,
        help="Read-only SQL query to execute",
    )
    query_project_parser.add_argument(
        "--json",
        action="store_true",
        help="Output in JSON format",
    )

    skills_parser = subparsers.add_parser(
        "skills",
        help="Manage Trackio skills for AI coding assistants",
    )
    skills_subparsers = skills_parser.add_subparsers(
        dest="skills_action", required=True
    )
    skills_add_parser = skills_subparsers.add_parser(
        "add",
        help="Download and install the Trackio skill for an AI assistant",
    )
    skills_add_parser.add_argument(
        "--cursor",
        action="store_true",
        help="Install for Cursor",
    )
    skills_add_parser.add_argument(
        "--claude",
        action="store_true",
        help="Install for Claude Code",
    )
    skills_add_parser.add_argument(
        "--codex",
        action="store_true",
        help="Install for Codex",
    )
    skills_add_parser.add_argument(
        "--opencode",
        action="store_true",
        help="Install for OpenCode",
    )
    skills_add_parser.add_argument(
        "--global",
        dest="global_",
        action="store_true",
        help="Install globally (user-level) instead of in the current project directory",
    )
    skills_add_parser.add_argument(
        "--dest",
        type=str,
        required=False,
        help="Install into a custom destination (path to skills directory)",
    )
    skills_add_parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing skill if it already exists",
    )
    skills_add_parser.add_argument(
        "--no-command",
        dest="no_command",
        action="store_true",
        help="Do not install the /logbook slash command alongside the skill",
    )

    logbook_parser = subparsers.add_parser(
        "logbook",
        help="Create and publish a shareable experiment logbook",
    )
    logbook_sub = logbook_parser.add_subparsers(dest="logbook_action", required=True)

    lb_open = logbook_sub.add_parser(
        "open", help="Start or attach to the logbook in this directory"
    )
    lb_open.add_argument(
        "space_id", nargs="?", help="Optional HF Space id to publish to"
    )
    lb_open.add_argument("--title", help="Logbook title (only when creating)")

    lb_note = logbook_sub.add_parser("note", help="Append a finding to the logbook")
    lb_note.add_argument("body", help="The finding text")
    lb_note.add_argument("--title", help="Short heading for this entry")
    lb_note.add_argument("--page", default="index", help="Target page slug")
    lb_note.add_argument("--link", action="append", default=[], help="URL to unfurl")
    lb_note.add_argument(
        "--artifact", action="append", default=[], help="Trackio artifact name:vN"
    )

    lb_page = logbook_sub.add_parser(
        "page", help="Create a page (returns a slug to link from the index)"
    )
    lb_page.add_argument("title", help="Page title")
    lb_page.add_argument("--parent", default="index", help="Parent page slug")

    lb_serve = logbook_sub.add_parser("serve", help="Preview the logbook locally")
    lb_serve.add_argument("--port", type=int, default=7861)
    lb_serve.add_argument("--no-browser", action="store_true")

    lb_pub = logbook_sub.add_parser(
        "publish", help="Publish to a static HF Space (first publish enables auto-sync)"
    )
    lb_pub.add_argument("space_id", nargs="?", help="HF Space id (username/space)")

    logbook_sub.add_parser(
        "sync", help="Push local edits to the Space now (after the first publish)"
    )

    logbook_sub.add_parser("_sync", help=argparse.SUPPRESS)

    args, unknown_args = parser.parse_known_args()
    if unknown_args:
        trailing_global_parser = argparse.ArgumentParser(add_help=False)
        trailing_global_parser.add_argument("--space", required=False)
        trailing_global_parser.add_argument("--hf-token", required=False)
        trailing_globals, remaining_unknown = trailing_global_parser.parse_known_args(
            unknown_args
        )
        if remaining_unknown:
            parser.error(f"unrecognized arguments: {' '.join(remaining_unknown)}")
        if trailing_globals.space is not None:
            args.space = trailing_globals.space
        if trailing_globals.hf_token is not None:
            args.hf_token = trailing_globals.hf_token

    if args.command in ("show", "status", "sync", "freeze", "skills") and _get_space(
        args
    ):
        error_exit(
            f"The '{args.command}' command does not support --space (remote mode)."
        )

    if args.command == "show":
        color_palette = None
        if args.color_palette:
            color_palette = [color.strip() for color in args.color_palette.split(",")]
        show(
            project=args.project,
            theme=args.theme,
            mcp_server=args.mcp_server,
            footer=args.footer,
            color_palette=color_palette,
            host=args.host,
            frontend_dir=args.frontend,
        )
    elif args.command == "status":
        _handle_status()
    elif args.command == "sync":
        _handle_sync(args)
    elif args.command == "freeze":
        freeze(
            space_id=args.space_id,
            project=args.project,
            new_space_id=args.new_space_id,
            private=args.private,
            frontend_dir=args.frontend,
        )
    elif args.command == "config":
        _handle_config(args)
    elif args.command == "list":
        if args.list_type == "spaces":
            _handle_list_spaces(args)
            return

        remote = _get_remote(args)
        if args.list_type == "projects":
            if remote:
                projects = remote.predict(api_name="/get_all_projects")
            else:
                projects = SQLiteStorage.get_projects()
            if args.json:
                print(format_json({"projects": projects}))
            else:
                print(format_list(projects, "Projects"))
        elif args.list_type == "runs":
            if remote:
                run_records = remote.predict(
                    args.project, api_name="/get_runs_for_project"
                )
                runs = [r["name"] if isinstance(r, dict) else r for r in run_records]
            else:
                db_path = SQLiteStorage.get_project_db_path(args.project)
                if not db_path.exists():
                    error_exit(f"Project '{args.project}' not found.")
                runs = SQLiteStorage.get_runs(args.project)
            if args.json:
                print(format_json({"project": args.project, "runs": runs}))
            else:
                print(format_list(runs, f"Runs in '{args.project}'"))
        elif args.list_type == "metrics":
            if remote:
                metrics = remote.predict(
                    args.project, args.run, api_name="/get_metrics_for_run"
                )
            else:
                db_path = SQLiteStorage.get_project_db_path(args.project)
                if not db_path.exists():
                    error_exit(f"Project '{args.project}' not found.")
                runs = SQLiteStorage.get_runs(args.project)
                if args.run not in runs:
                    error_exit(
                        f"Run '{args.run}' not found in project '{args.project}'."
                    )
                metrics = SQLiteStorage.get_all_metrics_for_run(args.project, args.run)
            if args.json:
                print(
                    format_json(
                        {"project": args.project, "run": args.run, "metrics": metrics}
                    )
                )
            else:
                print(
                    format_list(
                        metrics, f"Metrics for '{args.run}' in '{args.project}'"
                    )
                )
        elif args.list_type == "system-metrics":
            if remote:
                system_metrics = remote.predict(
                    args.project, args.run, api_name="/get_system_metrics_for_run"
                )
            else:
                db_path = SQLiteStorage.get_project_db_path(args.project)
                if not db_path.exists():
                    error_exit(f"Project '{args.project}' not found.")
                runs = SQLiteStorage.get_runs(args.project)
                if args.run not in runs:
                    error_exit(
                        f"Run '{args.run}' not found in project '{args.project}'."
                    )
                system_metrics = SQLiteStorage.get_all_system_metrics_for_run(
                    args.project, args.run
                )
            if args.json:
                print(
                    format_json(
                        {
                            "project": args.project,
                            "run": args.run,
                            "system_metrics": system_metrics,
                        }
                    )
                )
            else:
                print(format_system_metric_names(system_metrics))
        elif args.list_type == "alerts":
            if remote:
                alerts = remote.predict(
                    args.project,
                    args.run,
                    args.level,
                    args.since,
                    api_name="/get_alerts",
                )
            else:
                db_path = SQLiteStorage.get_project_db_path(args.project)
                if not db_path.exists():
                    error_exit(f"Project '{args.project}' not found.")
                alerts = SQLiteStorage.get_alerts(
                    args.project,
                    run_name=args.run,
                    level=args.level,
                    since=args.since,
                )
            if args.json:
                print(
                    format_json(
                        {
                            "project": args.project,
                            "run": args.run,
                            "level": args.level,
                            "since": args.since,
                            "alerts": alerts,
                        }
                    )
                )
            else:
                print(format_alerts(alerts))
        elif args.list_type == "reports":
            if remote:
                run_records = remote.predict(
                    args.project, api_name="/get_runs_for_project"
                )
                runs = [r["name"] if isinstance(r, dict) else r for r in run_records]
            else:
                db_path = SQLiteStorage.get_project_db_path(args.project)
                if not db_path.exists():
                    error_exit(f"Project '{args.project}' not found.")
                runs = SQLiteStorage.get_runs(args.project)
            if args.run and args.run not in runs:
                error_exit(f"Run '{args.run}' not found in project '{args.project}'.")

            target_runs = [args.run] if args.run else runs
            all_reports = []
            for run_name in target_runs:
                if remote:
                    logs = remote.predict(args.project, run_name, api_name="/get_logs")
                else:
                    logs = SQLiteStorage.get_logs(args.project, run_name)
                all_reports.extend(_extract_reports(run_name, logs))

            if args.json:
                print(
                    format_json(
                        {
                            "project": args.project,
                            "run": args.run,
                            "reports": all_reports,
                        }
                    )
                )
            else:
                report_lines = [
                    f"{entry['run']} | {entry['report']} | step={entry['step']} | {entry['timestamp']}"
                    for entry in all_reports
                ]
                if args.run:
                    print(
                        format_list(
                            report_lines,
                            f"Reports for '{args.run}' in '{args.project}'",
                        )
                    )
                else:
                    print(format_list(report_lines, f"Reports in '{args.project}'"))
        elif args.list_type == "artifacts":
            if remote:
                artifacts = remote.predict(args.project, api_name="/get_artifacts")
            else:
                db_path = SQLiteStorage.get_project_db_path(args.project)
                if not db_path.exists():
                    error_exit(f"Project '{args.project}' not found.")
                artifacts = SQLiteStorage.get_artifacts(args.project)
            if args.json:
                print(format_json({"project": args.project, "artifacts": artifacts}))
            else:
                print(format_artifacts(artifacts, args.project))
    elif args.command == "get":
        remote = _get_remote(args)
        if args.get_type == "artifact":
            if remote:
                record = remote.predict(
                    args.project,
                    args.name,
                    args.version,
                    api_name="/get_artifact_manifest",
                )
            else:
                db_path = SQLiteStorage.get_project_db_path(args.project)
                if not db_path.exists():
                    error_exit(f"Project '{args.project}' not found.")
                record = SQLiteStorage.get_artifact_manifest(
                    args.project, args.name, args.version
                )
            if record is None:
                spec = f":{args.version}" if args.version else ""
                error_exit(
                    f"Artifact '{args.name}{spec}' not found in project "
                    f"'{args.project}'."
                )
            if args.json:
                print(format_json(record))
            else:
                print(format_artifact(record))
        elif args.get_type == "project":
            if remote:
                summary = remote.predict(args.project, api_name="/get_project_summary")
            else:
                db_path = SQLiteStorage.get_project_db_path(args.project)
                if not db_path.exists():
                    error_exit(f"Project '{args.project}' not found.")
                summary = get_project_summary(args.project)
            if args.json:
                print(format_json(summary))
            else:
                print(format_project_summary(summary))
        elif args.get_type == "run":
            if remote:
                summary = remote.predict(
                    args.project, args.run, api_name="/get_run_summary"
                )
            else:
                db_path = SQLiteStorage.get_project_db_path(args.project)
                if not db_path.exists():
                    error_exit(f"Project '{args.project}' not found.")
                runs = SQLiteStorage.get_runs(args.project)
                if args.run not in runs:
                    error_exit(
                        f"Run '{args.run}' not found in project '{args.project}'."
                    )
                summary = get_run_summary(args.project, args.run)
            if args.json:
                print(format_json(summary))
            else:
                print(format_run_summary(summary))
        elif args.get_type == "metric":
            at_time = getattr(args, "at_time", None)
            if remote:
                values = remote.predict(
                    args.project,
                    args.run,
                    args.metric,
                    args.step,
                    args.around,
                    at_time,
                    args.window,
                    api_name="/get_metric_values",
                )
            else:
                db_path = SQLiteStorage.get_project_db_path(args.project)
                if not db_path.exists():
                    error_exit(f"Project '{args.project}' not found.")
                runs = SQLiteStorage.get_runs(args.project)
                if args.run not in runs:
                    error_exit(
                        f"Run '{args.run}' not found in project '{args.project}'."
                    )
                metrics = SQLiteStorage.get_all_metrics_for_run(args.project, args.run)
                if args.metric not in metrics:
                    error_exit(
                        f"Metric '{args.metric}' not found in run '{args.run}' of project '{args.project}'."
                    )
                values = SQLiteStorage.get_metric_values(
                    args.project,
                    args.run,
                    args.metric,
                    step=args.step,
                    around_step=args.around,
                    at_time=at_time,
                    window=args.window,
                )
            if args.json:
                print(
                    format_json(
                        {
                            "project": args.project,
                            "run": args.run,
                            "metric": args.metric,
                            "values": values,
                        }
                    )
                )
            else:
                print(format_metric_values(values))
        elif args.get_type == "snapshot":
            if not args.step and not args.around and not getattr(args, "at_time", None):
                error_exit(
                    "Provide --step, --around (with --window), or --at-time (with --window)."
                )
            at_time = getattr(args, "at_time", None)
            if remote:
                snapshot = remote.predict(
                    args.project,
                    args.run,
                    args.step,
                    args.around,
                    at_time,
                    args.window,
                    api_name="/get_snapshot",
                )
            else:
                db_path = SQLiteStorage.get_project_db_path(args.project)
                if not db_path.exists():
                    error_exit(f"Project '{args.project}' not found.")
                runs = SQLiteStorage.get_runs(args.project)
                if args.run not in runs:
                    error_exit(
                        f"Run '{args.run}' not found in project '{args.project}'."
                    )
                snapshot = SQLiteStorage.get_snapshot(
                    args.project,
                    args.run,
                    step=args.step,
                    around_step=args.around,
                    at_time=at_time,
                    window=args.window,
                )
            if args.json:
                result = {
                    "project": args.project,
                    "run": args.run,
                    "metrics": snapshot,
                }
                if args.step is not None:
                    result["step"] = args.step
                if args.around is not None:
                    result["around"] = args.around
                    result["window"] = args.window
                if at_time is not None:
                    result["at_time"] = at_time
                    result["window"] = args.window
                print(format_json(result))
            else:
                print(format_snapshot(snapshot))
        elif args.get_type == "system-metric":
            if remote:
                system_metrics = remote.predict(
                    args.project, args.run, api_name="/get_system_logs"
                )
                if args.metric:
                    all_system_metric_names = remote.predict(
                        args.project,
                        args.run,
                        api_name="/get_system_metrics_for_run",
                    )
                    if args.metric not in all_system_metric_names:
                        error_exit(
                            f"System metric '{args.metric}' not found in run '{args.run}' of project '{args.project}'."
                        )
                    filtered_metrics = [
                        {
                            k: v
                            for k, v in entry.items()
                            if k == "timestamp" or k == args.metric
                        }
                        for entry in system_metrics
                        if args.metric in entry
                    ]
                    if args.json:
                        print(
                            format_json(
                                {
                                    "project": args.project,
                                    "run": args.run,
                                    "metric": args.metric,
                                    "values": filtered_metrics,
                                }
                            )
                        )
                    else:
                        print(format_system_metrics(filtered_metrics))
                else:
                    if args.json:
                        print(
                            format_json(
                                {
                                    "project": args.project,
                                    "run": args.run,
                                    "system_metrics": system_metrics,
                                }
                            )
                        )
                    else:
                        print(format_system_metrics(system_metrics))
            else:
                db_path = SQLiteStorage.get_project_db_path(args.project)
                if not db_path.exists():
                    error_exit(f"Project '{args.project}' not found.")
                runs = SQLiteStorage.get_runs(args.project)
                if args.run not in runs:
                    error_exit(
                        f"Run '{args.run}' not found in project '{args.project}'."
                    )
                if args.metric:
                    system_metrics = SQLiteStorage.get_system_logs(
                        args.project, args.run
                    )
                    all_system_metric_names = (
                        SQLiteStorage.get_all_system_metrics_for_run(
                            args.project, args.run
                        )
                    )
                    if args.metric not in all_system_metric_names:
                        error_exit(
                            f"System metric '{args.metric}' not found in run '{args.run}' of project '{args.project}'."
                        )
                    filtered_metrics = [
                        {
                            k: v
                            for k, v in entry.items()
                            if k == "timestamp" or k == args.metric
                        }
                        for entry in system_metrics
                        if args.metric in entry
                    ]
                    if args.json:
                        print(
                            format_json(
                                {
                                    "project": args.project,
                                    "run": args.run,
                                    "metric": args.metric,
                                    "values": filtered_metrics,
                                }
                            )
                        )
                    else:
                        print(format_system_metrics(filtered_metrics))
                else:
                    system_metrics = SQLiteStorage.get_system_logs(
                        args.project, args.run
                    )
                    if args.json:
                        print(
                            format_json(
                                {
                                    "project": args.project,
                                    "run": args.run,
                                    "system_metrics": system_metrics,
                                }
                            )
                        )
                    else:
                        print(format_system_metrics(system_metrics))
        elif args.get_type == "alerts":
            if remote:
                alerts = remote.predict(
                    args.project,
                    args.run,
                    args.level,
                    args.since,
                    api_name="/get_alerts",
                )
            else:
                db_path = SQLiteStorage.get_project_db_path(args.project)
                if not db_path.exists():
                    error_exit(f"Project '{args.project}' not found.")
                alerts = SQLiteStorage.get_alerts(
                    args.project,
                    run_name=args.run,
                    level=args.level,
                    since=args.since,
                )
            if args.json:
                print(
                    format_json(
                        {
                            "project": args.project,
                            "run": args.run,
                            "level": args.level,
                            "since": args.since,
                            "alerts": alerts,
                        }
                    )
                )
            else:
                print(format_alerts(alerts))
        elif args.get_type == "report":
            if remote:
                logs = remote.predict(args.project, args.run, api_name="/get_logs")
            else:
                db_path = SQLiteStorage.get_project_db_path(args.project)
                if not db_path.exists():
                    error_exit(f"Project '{args.project}' not found.")
                runs = SQLiteStorage.get_runs(args.project)
                if args.run not in runs:
                    error_exit(
                        f"Run '{args.run}' not found in project '{args.project}'."
                    )
                logs = SQLiteStorage.get_logs(args.project, args.run)

            reports = _extract_reports(args.run, logs, report_name=args.report)
            if not reports:
                error_exit(
                    f"Report '{args.report}' not found in run '{args.run}' of project '{args.project}'."
                )

            if args.json:
                print(
                    format_json(
                        {
                            "project": args.project,
                            "run": args.run,
                            "report": args.report,
                            "values": reports,
                        }
                    )
                )
            else:
                output = []
                for idx, entry in enumerate(reports, start=1):
                    output.append(
                        f"Entry {idx} | step={entry['step']} | timestamp={entry['timestamp']}"
                    )
                    output.append(entry["content"])
                    if idx < len(reports):
                        output.append("-" * 80)
                print("\n".join(output))
    elif args.command == "query":
        if args.query_type == "project":
            _handle_query(args)
    elif args.command == "skills":
        if args.skills_action == "add":
            _handle_skills_add(args)
    elif args.command == "logbook":
        _handle_logbook(args)
    else:
        parser.print_help()


def _sync_suffix(lb, proj):
    if lb.is_autosync(proj):
        space = lb.read_metadata(proj).get("space_id")
        return f" · syncing to {space}…"
    return ""


def _handle_logbook(args):
    from trackio import logbook as lb

    action = args.logbook_action
    try:
        if action == "open":
            proj = lb.find_project_dir()
            if proj is not None:
                if args.space_id:
                    metadata = lb.read_metadata(proj)
                    metadata["space_id"] = args.space_id
                    lb.write_metadata(proj, metadata)
                print(f"Attached to existing logbook at {lb.logbook_root(proj)}")
                return
            proj = lb.create_logbook(
                args.title or "Untitled Experiment", space_id=args.space_id
            )
            print(f"Opened logbook at {lb.logbook_root(proj)}")
            if args.space_id:
                print(f"Will publish to: {args.space_id}")
            print('Log findings with: trackio logbook note "..."')
        elif action == "note":
            proj = lb.require_project_dir()
            lb.add_note(
                proj,
                args.body,
                title=args.title,
                page_slug=args.page,
                links=args.link,
                artifacts=args.artifact,
            )
            print(f"Logged (page: {args.page}).{_sync_suffix(lb, proj)}")
            lb.trigger_autosync(proj)
        elif action == "page":
            proj = lb.require_project_dir()
            page_slug = lb.add_page(proj, args.title, parent_slug=args.parent)
            print(
                f"Created page '{page_slug}'. Link it from a page with "
                f"[{args.title}](#/{page_slug})"
            )
            lb.trigger_autosync(proj)
        elif action == "_sync":
            lb.sync_worker()
        elif action == "serve":
            lb.serve(port=args.port, open_browser=not args.no_browser)
        elif action == "publish":
            print(f"Published: {lb.publish(space_id=args.space_id)}")
        elif action == "sync":
            proj = lb.require_project_dir()
            if not lb.is_autosync(proj):
                error_exit("Publish first: trackio logbook publish <username/space>")
            lb.trigger_autosync(proj)
            print(f"Syncing to {lb.read_metadata(proj).get('space_id')}…")
    except lb.LogbookError as e:
        error_exit(str(e))


def _handle_skills_add(args):
    import shutil
    from pathlib import Path

    CENTRAL_LOCAL = Path(".agents/skills")
    CENTRAL_GLOBAL = Path("~/.agents/skills")
    CLAUDE_LOCAL = Path(".claude/skills")
    CLAUDE_GLOBAL = Path("~/.claude/skills")

    SKILL_ID = "trackio"
    GITHUB_RAW = "https://raw.githubusercontent.com/gradio-app/trackio/main"
    SKILL_PREFIX = ".agents/skills/trackio"
    SKILL_FILES = [
        "SKILL.md",
        "alerts.md",
        "logging_metrics.md",
        "retrieving_metrics.md",
        "storage_schema.md",
        "logbook.md",
    ]
    COMMAND_PREFIX = ".agents/commands"
    COMMAND_FILE = "logbook.md"

    REPO_ROOT = Path(__file__).resolve().parent.parent
    USE_LOCAL = (REPO_ROOT / SKILL_PREFIX / "SKILL.md").is_file()

    if not (args.cursor or args.claude or args.codex or args.opencode or args.dest):
        error_exit(
            "Pick a destination via --cursor, --claude, --codex, --opencode, or --dest."
        )

    if USE_LOCAL:
        print(f"Using local Trackio source at {REPO_ROOT}")

    def download(url: str) -> str:
        from huggingface_hub.utils import get_session

        try:
            response = get_session().get(url)
            response.raise_for_status()
        except Exception as e:
            error_exit(
                f"Failed to download {url}\n{e}\n\n"
                "Make sure you have internet access. The skill files are fetched from "
                "the Trackio GitHub repository."
            )
        return response.text

    def get_content(prefix: str, fname: str) -> str:
        if USE_LOCAL:
            local = REPO_ROOT / prefix / fname
            if local.is_file():
                return local.read_text(encoding="utf-8")
        return download(f"{GITHUB_RAW}/{prefix}/{fname}")

    def remove_existing(path: Path, force: bool):
        if not (path.exists() or path.is_symlink()):
            return
        if not force:
            error_exit(
                f"Skill already exists at {path}.\nRe-run with --force to overwrite."
            )
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink()

    def install_to(skills_dir: Path, force: bool) -> Path:
        skills_dir = skills_dir.expanduser().resolve()
        skills_dir.mkdir(parents=True, exist_ok=True)
        dest = skills_dir / SKILL_ID
        remove_existing(dest, force)
        dest.mkdir()
        for fname in SKILL_FILES:
            (dest / fname).write_text(
                get_content(SKILL_PREFIX, fname), encoding="utf-8"
            )
        return dest

    def create_symlink(
        agent_skills_dir: Path, central_skill_path: Path, force: bool
    ) -> Path:
        agent_skills_dir = agent_skills_dir.expanduser().resolve()
        agent_skills_dir.mkdir(parents=True, exist_ok=True)
        link_path = agent_skills_dir / SKILL_ID
        remove_existing(link_path, force)
        link_path.symlink_to(os.path.relpath(central_skill_path, agent_skills_dir))
        return link_path

    def install_command(command_dir: Path, force: bool) -> Path:
        command_dir = command_dir.expanduser().resolve()
        command_dir.mkdir(parents=True, exist_ok=True)
        dest = command_dir / COMMAND_FILE
        if dest.exists() and not force:
            error_exit(
                f"Command already exists at {dest}.\nRe-run with --force to overwrite."
            )
        dest.write_text(get_content(COMMAND_PREFIX, COMMAND_FILE), encoding="utf-8")
        return dest

    global_targets = {
        "cursor": Path("~/.cursor/skills"),
        "claude": CLAUDE_GLOBAL,
        "codex": Path("~/.codex/skills"),
        "opencode": Path("~/.opencode/skills"),
    }
    local_targets = {
        "cursor": Path(".cursor/skills"),
        "claude": CLAUDE_LOCAL,
        "codex": Path(".codex/skills"),
        "opencode": Path(".opencode/skills"),
    }
    targets_dict = global_targets if args.global_ else local_targets

    command_targets_global = {
        "cursor": Path("~/.cursor/commands"),
        "claude": Path("~/.claude/commands"),
    }
    command_targets_local = {
        "cursor": Path(".cursor/commands"),
        "claude": Path(".claude/commands"),
    }
    command_dict = command_targets_global if args.global_ else command_targets_local

    if args.dest:
        if args.cursor or args.claude or args.codex or args.opencode or args.global_:
            error_exit("--dest cannot be combined with agent flags or --global.")
        skill_dest = install_to(Path(args.dest), args.force)
        print(f"Installed '{SKILL_ID}' to {skill_dest}")
        return

    selected = [
        name
        for name, flag in (
            ("cursor", args.cursor),
            ("claude", args.claude),
            ("codex", args.codex),
            ("opencode", args.opencode),
        )
        if flag
    ]

    central_path = CENTRAL_GLOBAL if args.global_ else CENTRAL_LOCAL
    central_skill_path = install_to(central_path, args.force)
    print(f"Installed '{SKILL_ID}' to central location: {central_skill_path}")

    for name in selected:
        link_path = create_symlink(targets_dict[name], central_skill_path, args.force)
        print(f"Created symlink: {link_path}")

    if not args.no_command:
        for name in selected:
            if name in command_dict:
                cmd_path = install_command(command_dict[name], args.force)
                print(f"Installed '/logbook' command: {cmd_path}")
            else:
                print(
                    f"Skipped '/logbook' command for {name} "
                    "(no slash-command directory convention)."
                )


if __name__ == "__main__":
    main()
