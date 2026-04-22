import time
from pathlib import Path

import trackio
from playwright.sync_api import sync_playwright
from trackio import Trace

THEMES = {
    "editorial": "examples/custom-frontends/editorial/frontend",
    "signal": "examples/custom-frontends/signal/frontend",
    "starter": "examples/custom-frontends/starter/frontend",
    "sunrise": "examples/custom-frontends/sunrise/frontend",
}

PROJECT = "frontend-showcase"
RUNS = [
    "atlas",
    "beacon",
]


def seed_demo_project() -> None:
    trackio.delete_project(PROJECT, force=True)
    for run_index, run_name in enumerate(RUNS):
        trackio.init(project=PROJECT, name=run_name)
        for step in range(8):
            trackio.log(
                {
                    "loss": round(1.1 - step * 0.08 - run_index * 0.04, 4),
                    "accuracy": round(0.52 + step * 0.05 + run_index * 0.03, 4),
                    "throughput": 120 + step * 8 + run_index * 10,
                    "lr": round(0.0008 - step * 0.00006, 6),
                    "conversation": Trace(
                        messages=[
                            {"role": "system", "content": "You are monitoring a training job."},
                            {"role": "user", "content": f"Summarize step {step} for run {run_name}."},
                            {
                                "role": "assistant",
                                "content": f"Loss is trending down and accuracy is trending up at step {step}.",
                            },
                        ],
                        metadata={"label": f"{run_name}-step-{step}", "group": "monitoring"},
                    ),
                }
            )
        trackio.finish()


def capture() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    apps = []
    try:
        seed_demo_project()
        for offset, (theme_name, relative_dir) in enumerate(THEMES.items()):
            frontend_dir = repo_root / relative_dir
            server_port = 7860 + offset
            app, local_url, _share_url, _full_url = trackio.show(
                project=PROJECT,
                frontend_dir=frontend_dir,
                host="127.0.0.1",
                server_port=server_port,
                open_browser=False,
                block_thread=False,
            )
            apps.append(app)

            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                page = browser.new_page(viewport={"width": 1440, "height": 1100}, device_scale_factor=1)
                page.goto(f"{local_url}?project={PROJECT}", wait_until="networkidle")
                page.screenshot(path=str(repo_root / "examples" / "custom-frontends" / theme_name / "screenshot.png"))
                browser.close()
            time.sleep(0.2)
    finally:
        for app in apps:
            app.close(verbose=False)
        trackio.delete_project(PROJECT, force=True)


if __name__ == "__main__":
    capture()
