import argparse
import time
import webbrowser
from pathlib import Path

import trackio

THEME_DIRS = {
    "brutalist-lab": "examples/custom-frontends/brutalist-lab/frontend",
    "signal-console": "examples/custom-frontends/signal-console/frontend",
    "sunrise-cards": "examples/custom-frontends/sunrise-cards/frontend",
    "editorial-grid": "examples/custom-frontends/editorial-grid/frontend",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Launch the four Trackio custom frontend themes in separate tabs."
    )
    parser.add_argument(
        "--project",
        help="Optional Trackio project to open in all four tabs.",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host to bind each Trackio server to.",
    )
    parser.add_argument(
        "--start-port",
        type=int,
        default=7860,
        help="Port for the first theme. The others use consecutive ports.",
    )
    parser.add_argument(
        "--no-open",
        action="store_true",
        help="Start the servers without opening browser tabs.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    repo_root = Path(__file__).resolve().parent.parent
    apps = []

    print("* Launching Trackio theme previews...")
    for offset, (theme_name, relative_dir) in enumerate(THEME_DIRS.items()):
        frontend_dir = repo_root / relative_dir
        server_port = args.start_port + offset
        app, local_url, _share_url, full_url = trackio.show(
            project=args.project,
            frontend_dir=frontend_dir,
            host=args.host,
            server_port=server_port,
            open_browser=False,
            block_thread=False,
        )
        apps.append(app)
        print(f"  {theme_name}: {local_url}")
        if not args.no_open:
            webbrowser.open(full_url)

    print("* Press Ctrl+C to stop all four servers.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n* Shutting down theme previews...")
        for app in apps:
            app.close(verbose=False)


if __name__ == "__main__":
    main()
