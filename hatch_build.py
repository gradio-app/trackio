import os
import shutil
import subprocess
from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class CustomBuildHook(BuildHookInterface):
    PLUGIN_NAME = "custom"

    def initialize(self, version: str, build_data: dict) -> None:
        if os.environ.get("SKIP_FRONTEND_BUILD") == "1":
            return

        root = Path(self.root)
        frontend = root / "trackio" / "frontend"
        dist_index = frontend / "dist" / "index.html"
        if (
            dist_index.is_file()
            and os.environ.get("TRACKIO_FRONTEND_FORCE_REBUILD") != "1"
        ):
            return

        if not (frontend / "package.json").is_file():
            return

        if not shutil.which("npm"):
            raise RuntimeError(
                "The Trackio dashboard frontend is not built (trackio/frontend/dist/index.html "
                "is missing) and npm is not available. Install Node.js and npm, then run "
                "`cd trackio/frontend && npm ci && npm run build`, or set SKIP_FRONTEND_BUILD=1 "
                "only if dist/ was produced another way."
            )

        subprocess.run(
            ["npm", "ci"],
            cwd=str(frontend),
            check=True,
        )
        subprocess.run(
            ["npm", "run", "build"],
            cwd=str(frontend),
            check=True,
        )
