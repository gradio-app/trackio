import argparse

from trackio import show, sync
from trackio.cli_helpers import (
    error_exit,
    format_json,
    format_list,
    format_metric_values,
    format_project_summary,
    format_run_summary,
    format_system_metric_names,
    format_system_metrics,
)
from trackio.sqlite_storage import SQLiteStorage
from trackio.ui.main import get_project_summary, get_run_summary


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

    sync_parser = subparsers.add_parser(
        "sync",
        help="Sync a local project's database to a Hugging Face Space. If the Space does not exist, it will be created.",
    )
    sync_parser.add_argument(
        "--project", required=True, help="The name of the local project."
    )
    sync_parser.add_argument(
        "--space-id",
        required=True,
        help="The Hugging Face Space ID where the project will be synced (e.g. username/space_id).",
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
        )
    elif args.command == "sync":
        sync(
            project=args.project,
            space_id=args.space_id,
            private=args.private,
            force=args.force,
        )
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
            values = SQLiteStorage.get_metric_values(
                args.project, args.run, args.metric
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
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
