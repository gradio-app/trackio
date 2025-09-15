import argparse

from trackio import show


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
        default="citrus",
        help="A Gradio Theme to use for the dashboard instead of the default 'citrus', can be a built-in theme (e.g. 'soft', 'default'), a theme from the Hub (e.g. 'gstaff/xkcd').",
    )
    ui_parser.add_argument(
        "--read-only",
        action="store_true",
        help="Launch the dashboard in read-only mode where API endpoints for logging and uploading data are disabled",
    )

    args = parser.parse_args()

    if args.command == "show":
        show(args.project, args.theme, args.read_only)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
