import argparse

from trackio import show, sync
from trackio.cli_helpers import (
    error_exit,
    format_alerts,
    format_json,
    format_list,
    format_metric_values,
    format_project_summary,
    format_run_summary,
    format_snapshot,
    format_system_metric_names,
    format_system_metrics,
)
from trackio.markdown import Markdown
from trackio.sqlite_storage import SQLiteStorage
from trackio.ui.main import get_project_summary, get_run_summary


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
                    project, space_id, private=args.private, pending_only=True
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
        )


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


def main():
    parser = argparse.ArgumentParser(description="Trackio CLI")
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

    args = parser.parse_args()

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
        )
    elif args.command == "status":
        _handle_status()
    elif args.command == "sync":
        _handle_sync(args)
    elif args.command == "list":
        if args.list_type == "projects":
            projects = SQLiteStorage.get_projects()
            if args.json:
                print(format_json({"projects": projects}))
            else:
                print(format_list(projects, "Projects"))
        elif args.list_type == "runs":
            db_path = SQLiteStorage.get_project_db_path(args.project)
            if not db_path.exists():
                error_exit(f"Project '{args.project}' not found.")
            runs = SQLiteStorage.get_runs(args.project)
            if args.json:
                print(format_json({"project": args.project, "runs": runs}))
            else:
                print(format_list(runs, f"Runs in '{args.project}'"))
        elif args.list_type == "metrics":
            db_path = SQLiteStorage.get_project_db_path(args.project)
            if not db_path.exists():
                error_exit(f"Project '{args.project}' not found.")
            runs = SQLiteStorage.get_runs(args.project)
            if args.run not in runs:
                error_exit(f"Run '{args.run}' not found in project '{args.project}'.")
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
            db_path = SQLiteStorage.get_project_db_path(args.project)
            if not db_path.exists():
                error_exit(f"Project '{args.project}' not found.")
            runs = SQLiteStorage.get_runs(args.project)
            if args.run not in runs:
                error_exit(f"Run '{args.run}' not found in project '{args.project}'.")
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
            db_path = SQLiteStorage.get_project_db_path(args.project)
            if not db_path.exists():
                error_exit(f"Project '{args.project}' not found.")
            runs = SQLiteStorage.get_runs(args.project)
            if args.run and args.run not in runs:
                error_exit(f"Run '{args.run}' not found in project '{args.project}'.")

            target_runs = [args.run] if args.run else runs
            all_reports = []
            for run_name in target_runs:
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
    elif args.command == "get":
        if args.get_type == "project":
            db_path = SQLiteStorage.get_project_db_path(args.project)
            if not db_path.exists():
                error_exit(f"Project '{args.project}' not found.")
            summary = get_project_summary(args.project)
            if args.json:
                print(format_json(summary))
            else:
                print(format_project_summary(summary))
        elif args.get_type == "run":
            db_path = SQLiteStorage.get_project_db_path(args.project)
            if not db_path.exists():
                error_exit(f"Project '{args.project}' not found.")
            runs = SQLiteStorage.get_runs(args.project)
            if args.run not in runs:
                error_exit(f"Run '{args.run}' not found in project '{args.project}'.")
            summary = get_run_summary(args.project, args.run)
            if args.json:
                print(format_json(summary))
            else:
                print(format_run_summary(summary))
        elif args.get_type == "metric":
            db_path = SQLiteStorage.get_project_db_path(args.project)
            if not db_path.exists():
                error_exit(f"Project '{args.project}' not found.")
            runs = SQLiteStorage.get_runs(args.project)
            if args.run not in runs:
                error_exit(f"Run '{args.run}' not found in project '{args.project}'.")
            metrics = SQLiteStorage.get_all_metrics_for_run(args.project, args.run)
            if args.metric not in metrics:
                error_exit(
                    f"Metric '{args.metric}' not found in run '{args.run}' of project '{args.project}'."
                )
            at_time = getattr(args, "at_time", None)
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
            db_path = SQLiteStorage.get_project_db_path(args.project)
            if not db_path.exists():
                error_exit(f"Project '{args.project}' not found.")
            runs = SQLiteStorage.get_runs(args.project)
            if args.run not in runs:
                error_exit(f"Run '{args.run}' not found in project '{args.project}'.")
            if not args.step and not args.around and not getattr(args, "at_time", None):
                error_exit(
                    "Provide --step, --around (with --window), or --at-time (with --window)."
                )
            at_time = getattr(args, "at_time", None)
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
            db_path = SQLiteStorage.get_project_db_path(args.project)
            if not db_path.exists():
                error_exit(f"Project '{args.project}' not found.")
            runs = SQLiteStorage.get_runs(args.project)
            if args.run not in runs:
                error_exit(f"Run '{args.run}' not found in project '{args.project}'.")
            if args.metric:
                system_metrics = SQLiteStorage.get_system_logs(args.project, args.run)
                all_system_metric_names = SQLiteStorage.get_all_system_metrics_for_run(
                    args.project, args.run
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
                system_metrics = SQLiteStorage.get_system_logs(args.project, args.run)
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
            db_path = SQLiteStorage.get_project_db_path(args.project)
            if not db_path.exists():
                error_exit(f"Project '{args.project}' not found.")
            runs = SQLiteStorage.get_runs(args.project)
            if args.run not in runs:
                error_exit(f"Run '{args.run}' not found in project '{args.project}'.")

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
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
