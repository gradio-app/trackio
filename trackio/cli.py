import argparse
import os
import re
import sys
from pathlib import Path

import huggingface_hub

import trackio
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


def _maybe_handle_logbook_run_argv() -> bool:
    argv = sys.argv[1:]
    try:
        logbook_idx = argv.index("logbook")
    except ValueError:
        return False
    if len(argv) <= logbook_idx + 1 or argv[logbook_idx + 1] != "run":
        return False

    run_argv = argv[logbook_idx + 2 :]

    run_parser = argparse.ArgumentParser(
        prog=f"{os.path.basename(sys.argv[0])} logbook run",
        description=(
            "Run a command; log the command, its scripts, and output to a page"
        ),
    )
    run_parser.add_argument("--page", help="Page title or slug")
    run_parser.add_argument("--title", help="Cell title")
    run_parser.add_argument(
        "--no-artifacts",
        action="store_true",
        help="Do not record output model/data files as artifact cells",
    )
    if "--" in run_argv:
        sep = run_argv.index("--")
        opts = run_parser.parse_args(run_argv[:sep])
        command = run_argv[sep + 1 :]
    else:
        opts, command = run_parser.parse_known_args(run_argv)
    if not command:
        run_parser.error("No command provided. Use: trackio logbook run -- <command>")
    args = argparse.Namespace(
        logbook_action="run",
        page=opts.page,
        title=opts.title,
        no_artifacts=opts.no_artifacts,
        command=command,
    )
    _handle_logbook(args)
    return True


def _maybe_rewrite_logbook_read_argv() -> None:
    argv = sys.argv
    for i in range(1, len(argv) - 1):
        if argv[i] == "logbook" and argv[i + 1] == "read":
            j = i + 2
            if (
                j < len(argv)
                and not argv[j].startswith("-")
                and argv[j] not in ("pages", "page", "cell")
            ):
                argv[j : j + 1] = ["--path", argv[j]]
            return


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
    if _maybe_handle_logbook_run_argv():
        return
    _maybe_rewrite_logbook_read_argv()

    parser = argparse.ArgumentParser(description="Trackio CLI")
    parser.add_argument(
        "--version",
        action="version",
        version=f"trackio {trackio.__version__}",
    )
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
        help=(
            "Install the Trackio skill to the central .agents/skills location; "
            "pass agent flags to also symlink it for specific assistants"
        ),
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
        "--pi",
        action="store_true",
        help="Install for pi",
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
    skills_add_parser.add_argument(
        "--no-hook",
        dest="no_hook",
        action="store_true",
        help="Do not install the Claude Code hook that mirrors todos into the logbook",
    )

    logbook_parser = subparsers.add_parser(
        "logbook",
        help="Create and publish a shareable experiment logbook",
    )
    logbook_sub = logbook_parser.add_subparsers(
        dest="logbook_action",
        required=True,
        metavar="{open,cell,run,page,attach,remove,read,serve,publish,pin,sync,sync-todos}",
    )

    lb_open = logbook_sub.add_parser(
        "open", help="Start or attach to the logbook in this directory"
    )
    lb_open.add_argument(
        "space_id", nargs="?", help="Optional HF Space id to publish to"
    )
    lb_open.add_argument("--title", help="Logbook title (only when creating)")
    lb_open.add_argument(
        "--no-serve",
        action="store_true",
        help="Open or attach without launching the local logbook preview",
    )
    lb_open.add_argument("--port", type=int, default=7861)
    lb_open.add_argument("--no-browser", action="store_true")

    lb_cell = logbook_sub.add_parser(
        "cell", help="Append a typed notebook-style cell to a logbook page"
    )
    lb_cell_sub = lb_cell.add_subparsers(dest="cell_type", required=True)

    lb_cell_md = lb_cell_sub.add_parser("markdown", help="Append a markdown cell")
    lb_cell_md.add_argument(
        "body",
        help="Markdown body (literal \\n escape sequences are converted to line breaks)",
    )
    lb_cell_md.add_argument("--title", help="Cell title")
    lb_cell_md.add_argument("--page", help="Page title or slug")
    lb_cell_art = lb_cell_sub.add_parser(
        "artifact", help="Append an artifact cell referencing a Trackio artifact"
    )
    lb_cell_art.add_argument("name", help="Artifact reference project/name:vN")
    lb_cell_art.add_argument("--title", help="Cell title")
    lb_cell_art.add_argument("--page", help="Page title or slug")
    lb_cell_art.add_argument(
        "--type",
        dest="artifact_type",
        help='Artifact type, e.g. "dataset" or "model"',
    )

    lb_cell_code = lb_cell_sub.add_parser("code", help="Append a code cell")
    lb_cell_code.add_argument("--title", help="Cell title")
    lb_cell_code.add_argument("--page", help="Page title or slug")
    lb_cell_code.add_argument(
        "--code", action="append", default=[], help="Path to code/config to include"
    )
    lb_cell_code.add_argument("--code-text", help="Inline code to include")
    lb_cell_code.add_argument("--language", help="Language for --code-text")
    lb_cell_code.add_argument(
        "--output",
        default="",
        help="Output text (optional; omit for a command-only code cell)",
    )

    lb_cell_figure = lb_cell_sub.add_parser("figure", help="Append a figure cell")
    lb_cell_figure.add_argument("--title", help="Cell title")
    lb_cell_figure.add_argument("--page", help="Page title or slug")
    lb_cell_figure.add_argument(
        "--html", help="Path to an HTML or image file, or inline HTML text"
    )
    lb_cell_figure.add_argument("--html-text", help="Inline HTML text")
    lb_cell_figure.add_argument(
        "--image", help="Path to an image file (PNG, JPG, GIF, WEBP, SVG, ...)"
    )
    lb_cell_figure.add_argument("--raw", help="Path/URL/text for raw data")
    lb_cell_figure.add_argument("--raw-text", help="Inline raw data")
    lb_cell_figure.add_argument(
        "--inline-plotlyjs",
        action="store_true",
        help=(
            "Embed the full Plotly.js library in the page (can be several MB). "
            "By default an inlined Plotly.js bundle is rewritten to a CDN "
            "reference to keep pages small."
        ),
    )

    lb_cell_dash = lb_cell_sub.add_parser(
        "dashboard", help="Embed a Trackio dashboard for a project"
    )
    lb_cell_dash.add_argument("project", help="Trackio project name")
    lb_cell_dash.add_argument(
        "--space",
        dest="space_id",
        help="HF Space id (owner/name) hosting the dashboard",
    )
    lb_cell_dash.add_argument("--title", help="Cell title")
    lb_cell_dash.add_argument("--page", help="Page title or slug")

    lb_cell_remove = lb_cell_sub.add_parser(
        "remove", help="Remove a cell from a page by its cell id"
    )
    lb_cell_remove.add_argument("cell_id", help="Cell id to remove")
    lb_cell_remove.add_argument("--page", help="Page title or slug to scope the search")

    lb_run = logbook_sub.add_parser(
        "run",
        help="Run a command; log the command, its scripts, and output to a page",
    )
    lb_run.add_argument("--page", help="Page title or slug")
    lb_run.add_argument("--title", help="Cell title")
    lb_run.add_argument(
        "--no-artifacts",
        action="store_true",
        help="Do not record output model/data files as artifact cells",
    )
    lb_run.add_argument("command", nargs="*")

    lb_page = logbook_sub.add_parser(
        "page", help="Create or select a page and make it the default target"
    )
    lb_page.add_argument("title", help="Page title")

    lb_attach = logbook_sub.add_parser(
        "attach", help="Attach external data to this logbook"
    )
    lb_attach_sub = lb_attach.add_subparsers(dest="attach_type", required=True)
    lb_attach_trace = lb_attach_sub.add_parser(
        "trace", help="Attach an agent session JSON or JSONL trace"
    )
    lb_attach_trace.add_argument("filepath", help="Path to the agent session file")
    lb_attach_trace.add_argument("--title", help="Display title for this session")
    lb_attach_trace.add_argument(
        "--no-scrub",
        action="store_true",
        help=(
            "Do not scrub secrets from the trace before storing it. By default "
            "tokens, keys and passwords are redacted."
        ),
    )

    lb_remove = logbook_sub.add_parser(
        "remove", help="Remove attached data from this logbook"
    )
    lb_remove_sub = lb_remove.add_subparsers(dest="remove_type", required=True)
    lb_remove_trace = lb_remove_sub.add_parser(
        "trace", help="Remove an attached agent session"
    )
    lb_remove_trace.add_argument("session_id", help="Attached session id")

    lb_read = logbook_sub.add_parser(
        "read", help="Read logbook pages/cells in an agent-friendly form"
    )
    lb_read.add_argument(
        "--path",
        help=(
            "Logbook to read: local path, HF Space id, or URL "
            "(can also be passed positionally: trackio logbook read <source>)"
        ),
    )
    lb_read.add_argument("--json", action="store_true", help="Output JSON")
    lb_read.add_argument(
        "--head",
        type=int,
        default=None,
        help="Lines of code shown per code cell (default 3; 0 hides code)",
    )
    lb_read.add_argument(
        "--tail",
        type=int,
        default=None,
        help="Lines of output shown per code cell (default 3; 0 hides output)",
    )
    lb_read.add_argument(
        "--raw-limit",
        type=int,
        default=None,
        help="Inline figure raw data up to this many chars (default 500; 0 disables)",
    )
    lb_read_sub = lb_read.add_subparsers(dest="read_target")
    lb_read_pages = lb_read_sub.add_parser("pages", help="List logbook pages")
    lb_read_pages.add_argument("--json", action="store_true", help="Output JSON")
    lb_read_page = lb_read_sub.add_parser("page", help="Read a page for agents")
    lb_read_page.add_argument("page", nargs="?", help="Page title or slug")
    lb_read_page.add_argument("--json", action="store_true", help="Output JSON")
    lb_read_page.add_argument(
        "--head", type=int, default=argparse.SUPPRESS, help="Code lines per code cell"
    )
    lb_read_page.add_argument(
        "--tail", type=int, default=argparse.SUPPRESS, help="Output lines per code cell"
    )
    lb_read_page.add_argument(
        "--raw-limit",
        type=int,
        default=argparse.SUPPRESS,
        help="Inline figure raw data up to this many chars",
    )
    lb_read_cell = lb_read_sub.add_parser("cell", help="Read one cell by id")
    lb_read_cell.add_argument("cell_id", help="Cell id")
    lb_read_cell.add_argument("--json", action="store_true", help="Output JSON")
    lb_read_cell.add_argument("--full", action="store_true", help="Include full body")
    lb_read_cell.add_argument(
        "--raw", action="store_true", help="Include figure raw data"
    )
    lb_read_cell.add_argument("--html", action="store_true", help="Include figure HTML")

    lb_serve = logbook_sub.add_parser("serve", help="Preview the logbook locally")
    lb_serve.add_argument("path", nargs="?", help="Logbook workspace/path to serve")
    lb_serve.add_argument("--port", type=int, default=7861)
    lb_serve.add_argument("--no-browser", action="store_true")

    lb_pub = logbook_sub.add_parser(
        "publish", help="Publish the current logbook state to Hugging Face"
    )
    lb_pub.add_argument("space_id", nargs="?", help="HF Space id (username/space)")
    lb_pub.add_argument(
        "--private",
        action="store_true",
        help="Make the published logbook Space itself private.",
    )
    lb_pub.add_argument(
        "--public",
        action="store_true",
        help=(
            "Publish the trace Dataset and artifacts Bucket as PUBLIC (they are "
            "private by default) and embed trace/workspace content inline in the "
            "static Space. By default the Space stores references only."
        ),
    )

    lb_pin = logbook_sub.add_parser(
        "pin",
        help="Pin (or unpin) a cell so it surfaces on the logbook intro",
    )
    lb_pin.add_argument(
        "cell_id",
        nargs="?",
        help="Cell id to pin (default: the most recent cell on the target page)",
    )
    lb_pin.add_argument(
        "--page",
        help="Page title or slug to scope the search / pick the last cell from",
    )
    lb_pin.add_argument(
        "--unpin", action="store_true", help="Unpin the cell instead of pinning it"
    )

    logbook_sub.add_parser(
        "sync",
        help="Regenerate the logbook site files from the current page sources",
    )

    logbook_sub.add_parser("sync-todos")

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


def _logbook_cell_target(lb, proj, args):
    return lb.resolve_page(proj, getattr(args, "page", None))


def _print_logbook_pages(pages):
    if not pages:
        print("No pages.")
        return
    print("Pages:")
    for page in pages:
        count = page["cell_count"]
        print(
            f"- {page['slug']} · {page['title']} · "
            f"{count} cell{'' if count == 1 else 's'}"
        )


def _print_logbook_page_outline(page):
    print(f"Page: {page['title']} ({page['slug']})")
    if not page["cells"]:
        print("No cells.")
        return
    for cell in page["cells"]:
        created = (
            f" · {cell['created_at'].replace('T', ' ')[:16]}"
            if cell.get("created_at")
            else ""
        )
        print(f"\n### {cell['title']} · {cell['type']} · {cell['id']}{created}")
        if cell.get("preview"):
            print(cell["preview"].rstrip())
    print(
        "\nFetch full payloads with: trackio logbook read cell <cell-id> "
        "[--full|--raw|--html]"
    )


def _print_logbook_cell(cell):
    print(f"Cell: {cell['title']} ({cell['id']})")
    print(f"Page: {cell['page_title']} ({cell['page']})")
    print(f"Type: {cell['type']}")
    if cell.get("created_at"):
        print(f"Created: {cell['created_at']}")
    content_keys = [key for key in ("body", "raw", "html") if key in cell]
    if not content_keys:
        if cell["type"] == "code":
            print("\nBody omitted. Use --full to include code/output.")
        elif cell["type"] == "figure":
            print("\nFigure content omitted. Use --raw, --html, or --full.")
        return
    for key in content_keys:
        label = key.upper()
        print(f"\n--- {label} ---\n")
        print(cell[key])


def _read_logbook_payload(path_or_text, inline_text):
    if inline_text is not None:
        return inline_text
    if not path_or_text:
        return ""
    path = Path(path_or_text)
    if path.is_file():
        return path.read_text(encoding="utf-8")
    return path_or_text


def _handle_logbook(args):
    from trackio import logbook as lb

    action = args.logbook_action
    try:
        if action == "open":
            print("Warning: Trackio Logbook is an experimental feature.")
            proj = lb.find_project_dir()
            if proj is not None:
                if args.space_id:
                    metadata = lb.read_metadata(proj)
                    metadata["space_id"] = args.space_id
                    lb.write_metadata(proj, metadata)
                print(f"Attached to existing logbook at {lb.logbook_root(proj)}")
                if args.title:
                    print(
                        "Note: --title was ignored because this logbook already "
                        "exists. To retitle it, edit the '# ...' heading in "
                        f"{lb.logbook_root(proj) / 'pages' / 'index.md'}."
                    )
            elif args.space_id:
                proj = lb.clone_logbook(args.space_id)
                if proj is not None:
                    print(
                        f"Cloned logbook from {args.space_id} into "
                        f"{lb.logbook_root(proj)}"
                    )
            if proj is None:
                proj = lb.create_logbook(
                    args.title or os.path.basename(os.getcwd()), space_id=args.space_id
                )
                print(f"Opened logbook at {lb.logbook_root(proj)}")
                if args.space_id:
                    print(f"Will publish to: {args.space_id}")
            if not args.no_serve:
                lb.start_preview(proj, port=args.port, open_browser=not args.no_browser)
        elif action == "run":
            proj = lb.require_project_dir()
            command = list(args.command or [])
            if command and command[0] == "--":
                command = command[1:]
            if not command:
                error_exit("No command provided. Use: trackio logbook run -- <command>")
            rc = lb.run_and_log(
                proj,
                command,
                page=args.page,
                title=args.title,
                capture_artifacts=not getattr(args, "no_artifacts", False),
            )
            slug = lb.read_metadata(proj).get("last_page", "?")
            print(f"Logged run to page '{slug}'.")
            sys.exit(rc)
        elif action == "cell" and args.cell_type == "remove":
            proj = lb.require_project_dir()
            result = lb.remove_cell(proj, args.cell_id, page=args.page)
            print(
                f"Removed {result['type']} cell {args.cell_id} "
                f"from page '{result['page']}'."
            )
        elif action == "cell":
            proj = lb.require_project_dir()
            slug = _logbook_cell_target(lb, proj, args)
            if args.cell_type == "markdown":
                # Agent/tool callers often send a single argument containing
                # escaped newlines. Treat those as Markdown line breaks while
                # preserving normal shell-provided newlines unchanged.
                body = args.body.replace("\\r\\n", "\n").replace("\\n", "\n")
                lb.add_markdown_cell(proj, slug, body, title=args.title)
            elif args.cell_type == "artifact":
                lb.add_artifact_cell(
                    proj,
                    slug,
                    args.name,
                    title=args.title,
                    artifact_type=args.artifact_type,
                )
            elif args.cell_type == "code":
                lb.add_code_cell(
                    proj,
                    slug,
                    args.output,
                    title=args.title,
                    code_paths=args.code,
                    code_text=args.code_text,
                    language=args.language,
                )
            elif args.cell_type == "figure":
                if args.image:
                    html = lb.figure_html_from_image(args.image)
                elif (
                    args.html
                    and args.html_text is None
                    and Path(args.html).is_file()
                    and lb.is_figure_image_path(args.html)
                ):
                    # `--html plot.png` — embed the image instead of trying to
                    # read a binary file as UTF-8 text.
                    html = lb.figure_html_from_image(args.html)
                else:
                    html = _read_logbook_payload(args.html, args.html_text)
                raw = _read_logbook_payload(args.raw, args.raw_text)
                lb.add_figure_cell(
                    proj,
                    slug,
                    html=html,
                    raw=raw,
                    title=args.title,
                    inline_plotlyjs=args.inline_plotlyjs,
                )
            elif args.cell_type == "dashboard":
                lb.add_dashboard_cell(
                    proj,
                    slug,
                    args.project,
                    space_id=args.space_id,
                    title=args.title,
                )
            print(f"Logged {args.cell_type} cell to page '{slug}'.")
        elif action == "page":
            proj = lb.require_project_dir()
            page_slug = lb.ensure_page(proj, args.title)
            print(f"Selected page '{page_slug}' as default.")
        elif action == "attach":
            proj = lb.require_project_dir()
            if args.attach_type == "trace":
                scrub = not args.no_scrub
                trace = lb.attach_trace(
                    proj, args.filepath, title=args.title, scrub=scrub
                )
                print(
                    f"Attached {trace.get('provider', 'agent')} trace "
                    f"'{trace['id']}' ({trace.get('event_count', 0)} events)."
                )
                if scrub:
                    redactions = trace.get("scrub_redactions", 0)
                    print(
                        f"Scrubbed secrets before storing: {redactions} "
                        f"redaction{'' if redactions == 1 else 's'}."
                    )
                else:
                    print(
                        "Warning: --no-scrub set; secrets were NOT redacted from "
                        "this trace."
                    )
        elif action == "remove":
            proj = lb.require_project_dir()
            if args.remove_type == "trace":
                lb.remove_trace(proj, args.session_id)
                print(f"Removed attached trace '{args.session_id}'.")
        elif action == "pin":
            proj = lb.require_project_dir()
            cell_id = args.cell_id or lb.last_cell_id(proj, page=args.page)
            if not cell_id:
                error_exit(
                    "No cell to pin. Pass a cell id, or add a cell first "
                    "(optionally scope with --page)."
                )
            res = lb.set_cell_pinned(
                proj, cell_id, pinned=not args.unpin, page=args.page
            )
            verb = "Unpinned" if args.unpin else "Pinned"
            print(f"{verb} cell {cell_id} on page '{res['page']}'.")
        elif action == "read":
            source, view = lb.split_read_view(args.path)
            proj = lb.resolve_read_source(source)
            preview_opts = {
                "head": lb.DEFAULT_HEAD
                if getattr(args, "head", None) is None
                else args.head,
                "tail": lb.DEFAULT_TAIL
                if getattr(args, "tail", None) is None
                else args.tail,
                "raw_limit": lb.DEFAULT_RAW_LIMIT
                if getattr(args, "raw_limit", None) is None
                else args.raw_limit,
            }
            if args.read_target is None and view == "trace":
                text = lb.read_traces(proj)
                print(
                    format_json({"view": "trace", "text": text}) if args.json else text
                )
            elif args.read_target is None and view == "workspace":
                text = lb.read_workspace_tree(proj)
                print(
                    format_json({"view": "workspace", "text": text})
                    if args.json
                    else text
                )
            elif args.read_target is None:
                if args.json:
                    print(format_json(lb.read_logbook_data(proj, **preview_opts)))
                else:
                    print(lb.read_logbook(proj, **preview_opts))
            elif args.read_target == "pages":
                pages = lb.list_pages(proj)
                if args.json:
                    print(format_json({"pages": pages}))
                else:
                    _print_logbook_pages(pages)
            elif args.read_target == "page":
                page = lb.read_page_outline(proj, args.page, **preview_opts)
                if args.json:
                    print(format_json(page))
                else:
                    _print_logbook_page_outline(page)
            elif args.read_target == "cell":
                cell = lb.read_cell(
                    proj,
                    args.cell_id,
                    include_full=args.full,
                    include_raw=args.raw,
                    include_html=args.html,
                )
                if args.json:
                    print(format_json(cell))
                else:
                    _print_logbook_cell(cell)
        elif action == "sync":
            proj = lb.require_project_dir()
            lb.write_site_files(proj)
            print(f"Synced logbook site files at {lb.logbook_root(proj)}.")
        elif action == "sync-todos":
            lb.sync_todos_from_stdin()
        elif action == "serve":
            lb.serve(path=args.path, port=args.port, open_browser=not args.no_browser)
        elif action == "publish":
            proj = lb.require_project_dir()
            metadata = lb.read_metadata(proj)
            if not (args.space_id or metadata.get("space_id")):
                raise lb.LogbookError(
                    "No Space id. Provide one: trackio logbook publish <username/space>"
                )
            inventory = lb.publication_inventory(proj)
            visibility = "PUBLIC" if args.public else "PRIVATE"
            if inventory["trace_count"] or inventory["workspace_file_count"]:
                print(
                    f"Attached traces ({inventory['trace_count']}) and Workspace "
                    f"files ({inventory['workspace_file_count']}) will be published "
                    f"to {visibility} repos."
                )
                if args.public:
                    print(
                        "  --public: trace/workspace content will also be embedded "
                        "inline in the static Space."
                    )
                else:
                    print(
                        "  The static Space will store references only "
                        "(no trace/workspace content or names)."
                    )
            url = lb.publish(
                space_id=args.space_id,
                hf_token=args.hf_token,
                private=args.private,
                public=args.public,
            )
            print(f"Published: {url}")
            space_id = lb.read_metadata(lb.require_project_dir()).get("space_id")
            if space_id:
                subdomain = re.sub(r"[^a-z0-9]+", "-", space_id.lower()).strip("-")
                print(f"Rendered at: https://{subdomain}.static.hf.space/")
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

    def install_command(
        command_dir: Path, force: bool, strip_frontmatter: bool = False
    ) -> Path:
        import re

        command_dir = command_dir.expanduser().resolve()
        command_dir.mkdir(parents=True, exist_ok=True)
        dest = command_dir / COMMAND_FILE
        if dest.exists() and not force:
            error_exit(
                f"Command already exists at {dest}.\nRe-run with --force to overwrite."
            )
        content = get_content(COMMAND_PREFIX, COMMAND_FILE)
        if strip_frontmatter:
            content = re.sub(r"\A---\n.*?\n---\n+", "", content, flags=re.S)
        dest.write_text(content, encoding="utf-8")
        return dest

    global_targets = {
        "cursor": Path("~/.cursor/skills"),
        "claude": CLAUDE_GLOBAL,
        "codex": Path("~/.codex/skills"),
        "opencode": Path("~/.opencode/skills"),
        "pi": Path("~/.pi/agent/skills"),
    }
    local_targets = {
        "cursor": Path(".cursor/skills"),
        "claude": CLAUDE_LOCAL,
        "codex": Path(".codex/skills"),
        "opencode": Path(".opencode/skills"),
        "pi": Path(".pi/skills"),
    }
    targets_dict = global_targets if args.global_ else local_targets

    command_targets_global = {
        "cursor": Path("~/.cursor/commands"),
        "claude": Path("~/.claude/commands"),
        "codex": Path("~/.codex/prompts"),
        "opencode": Path("~/.config/opencode/commands"),
        "pi": Path("~/.pi/agent/prompts"),
    }
    command_targets_local = {
        "cursor": Path(".cursor/commands"),
        "claude": Path(".claude/commands"),
        "codex": Path("~/.codex/prompts"),
        "opencode": Path(".opencode/commands"),
        "pi": Path(".pi/prompts"),
    }
    command_dict = command_targets_global if args.global_ else command_targets_local
    COMMAND_NOTES = {
        "codex": " (Codex only reads ~/.codex/prompts; restart Codex to pick it up)"
    }
    STRIP_FRONTMATTER = {"pi"}

    if args.dest:
        if (
            args.cursor
            or args.claude
            or args.codex
            or args.opencode
            or args.pi
            or args.global_
        ):
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
            ("pi", args.pi),
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
                cmd_path = install_command(
                    command_dict[name],
                    args.force,
                    strip_frontmatter=name in STRIP_FRONTMATTER,
                )
                note = COMMAND_NOTES.get(name, "")
                print(f"Installed '/logbook' command: {cmd_path}{note}")
            else:
                print(
                    f"Skipped '/logbook' command for {name} "
                    "(no slash-command directory convention)."
                )

    if args.claude and not args.no_hook:
        hook_path = _install_claude_logbook_hook(args.global_)
        if hook_path:
            print(f"Installed logbook todo-sync hook: {hook_path}")


def _install_claude_logbook_hook(global_: bool):
    import json
    from pathlib import Path

    settings = (
        Path("~/.claude/settings.json") if global_ else Path(".claude/settings.json")
    ).expanduser()
    settings.parent.mkdir(parents=True, exist_ok=True)
    data = {}
    if settings.exists():
        try:
            data = json.loads(settings.read_text(encoding="utf-8"))
        except Exception:
            print(f"Could not parse {settings}; skipping hook install.")
            return None
    command = "trackio logbook sync-todos"
    hooks = data.setdefault("hooks", {})
    post = hooks.setdefault("PostToolUse", [])
    for entry in post:
        for h in entry.get("hooks", []):
            if h.get("command") == command:
                return settings
    post.append(
        {
            "matcher": "TodoWrite",
            "hooks": [{"type": "command", "command": command}],
        }
    )
    settings.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return settings


if __name__ == "__main__":
    main()
