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
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
