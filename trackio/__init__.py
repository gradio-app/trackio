import hashlib
import os
import warnings
import webbrowser
from pathlib import Path
from typing import Any

from gradio.blocks import BUILT_IN_THEMES
from gradio.themes import Default as DefaultTheme
from gradio.themes import ThemeClass
from gradio_client import Client

from trackio import context_vars, deploy, utils
from trackio.imports import import_csv, import_tf_events
from trackio.media import TrackioImage
from trackio.run import Run
from trackio.sqlite_storage import SQLiteStorage
from trackio.ui import demo
from trackio.utils import TRACKIO_DIR, TRACKIO_LOGO_DIR

__version__ = Path(__file__).parent.joinpath("version.txt").read_text().strip()

__all__ = ["init", "log", "finish", "show", "import_csv", "import_tf_events", "Image"]

Image = TrackioImage


config = {}

DEFAULT_THEME = "citrus"


def init(
    project: str,
    name: str | None = None,
    space_id: str | None = None,
    dataset_id: str | None = None,
    config: dict | None = None,
    resume: str = "never",
    settings: Any = None,
) -> Run:
    """
    Creates a new Trackio project and returns a Run object.

    Args:
        project: The name of the project (can be an existing project to continue tracking or a new project to start tracking from scratch).
        name: The name of the run (if not provided, a default name will be generated).
        space_id: If provided, the project will be logged to a Hugging Face Space instead of a local directory. Should be a complete Space name like "username/reponame" or "orgname/reponame", or just "reponame" in which case the Space will be created in the currently-logged-in Hugging Face user's namespace. If the Space does not exist, it will be created. If the Space already exists, the project will be logged to it.
        dataset_id: If a space_id is provided, a persistent Hugging Face Dataset will be created and the metrics will be synced to it every 5 minutes. Specify a Dataset with name like "username/datasetname" or "orgname/datasetname", or "datasetname" (uses currently-logged-in Hugging Face user's namespace), or None (uses the same name as the Space but with the "_dataset" suffix). If the Dataset does not exist, it will be created. If the Dataset already exists, the project will be appended to it.
        config: A dictionary of configuration options. Provided for compatibility with wandb.init()
        resume: Controls how to handle resuming a run. Can be one of:
            - "must": Must resume the run with the given name, raises error if run doesn't exist
            - "allow": Resume the run if it exists, otherwise create a new run
            - "never": Never resume a run, always create a new one
        settings: Not used. Provided for compatibility with wandb.init()
    """
    if settings is not None:
        warnings.warn(
            "* Warning: settings is not used. Provided for compatibility with wandb.init(). Please create an issue at: https://github.com/gradio-app/trackio/issues if you need a specific feature implemented."
        )

    if space_id is None and dataset_id is not None:
        raise ValueError("Must provide a `space_id` when `dataset_id` is provided.")
    space_id, dataset_id = utils.preprocess_space_and_dataset_ids(space_id, dataset_id)
    url = context_vars.current_server.get()

    if url is None:
        if space_id is None:
            _, url, _ = demo.launch(
                show_api=False,
                inline=False,
                quiet=True,
                prevent_thread_lock=True,
                show_error=True,
            )
        else:
            url = space_id
        context_vars.current_server.set(url)

    if (
        context_vars.current_project.get() is None
        or context_vars.current_project.get() != project
    ):
        print(f"* Trackio project initialized: {project}")

        if dataset_id is not None:
            os.environ["TRACKIO_DATASET_ID"] = dataset_id
            print(
                f"* Trackio metrics will be synced to Hugging Face Dataset: {dataset_id}"
            )
        if space_id is None:
            print(f"* Trackio metrics logged to: {TRACKIO_DIR}")
            utils.print_dashboard_instructions(project)
        else:
            deploy.create_space_if_not_exists(space_id, dataset_id)
            print(
                f"* View dashboard by going to: {deploy.SPACE_URL.format(space_id=space_id)}"
            )
    context_vars.current_project.set(project)

    client = None
    if not space_id:
        client = Client(url, verbose=False)

    if resume == "must":
        if name is None:
            raise ValueError("Must provide a run name when resume='must'")
        if name not in SQLiteStorage.get_runs(project):
            raise ValueError(f"Run '{name}' does not exist in project '{project}'")
    elif resume == "allow":
        if name is not None and name in SQLiteStorage.get_runs(project):
            print(f"* Resuming existing run: {name}")
    elif resume == "never":
        if name is not None and name in SQLiteStorage.get_runs(project):
            name = None
    else:
        raise ValueError("resume must be one of: 'must', 'allow', or 'never'")

    run = Run(
        url=url,
        project=project,
        client=client,
        name=name,
        config=config,
        space_id=space_id,
    )
    context_vars.current_run.set(run)
    globals()["config"] = run.config
    return run


def log(metrics: dict, step: int | None = None) -> None:
    """
    Logs metrics to the current run.

    Args:
        metrics: A dictionary of metrics to log.
        step: The step number. If not provided, the step will be incremented automatically.
    """
    run = context_vars.current_run.get()
    if run is None:
        raise RuntimeError("Call trackio.init() before trackio.log().")
    run.log(
        metrics=metrics,
        step=step,
    )


def finish():
    """
    Finishes the current run.
    """
    run = context_vars.current_run.get()
    if run is None:
        raise RuntimeError("Call trackio.init() before trackio.finish().")
    run.finish()


def show(project: str | None = None, theme: str | ThemeClass = DEFAULT_THEME):
    """
    Launches the Trackio dashboard.

    Args:
        project: The name of the project whose runs to show. If not provided, all projects will be shown and the user can select one.
        theme: The Gradio theme to use. Can be any built-in Gradio theme (e.g. "citrus", "soft", "default"), theme from the Hub (https://huggingface.co/spaces/gradio/theme-gallery), or a custom gradio.themes.ThemeClass
    """
    if theme != DEFAULT_THEME:
        # TODO: It's a little hacky to reproduce this theme-setting logic from Gradio Blocks,
        # but in Gradio 6.0, the theme will be set in `launch()` instead, which means that we
        # will be able to remove this code.
        if isinstance(theme, str):
            if theme.lower() in BUILT_IN_THEMES:
                theme = BUILT_IN_THEMES[theme.lower()]
            else:
                try:
                    theme = ThemeClass.from_hub(theme)
                except Exception as e:
                    warnings.warn(f"Cannot load {theme}. Caught Exception: {str(e)}")
                    theme = DefaultTheme()
        if not isinstance(theme, ThemeClass):
            warnings.warn("Theme should be a class loaded from gradio.themes")
            theme = DefaultTheme()
        demo.theme: ThemeClass = theme
        demo.theme_css = theme._get_theme_css()
        demo.stylesheets = theme._stylesheets
        theme_hasher = hashlib.sha256()
        theme_hasher.update(demo.theme_css.encode("utf-8"))
        demo.theme_hash = theme_hasher.hexdigest()

    _, url, share_url = demo.launch(
        show_api=False,
        quiet=True,
        inline=False,
        prevent_thread_lock=True,
        favicon_path=TRACKIO_LOGO_DIR / "trackio_logo_light.png",
        allowed_paths=[TRACKIO_LOGO_DIR],
    )

    base_url = share_url + "/" if share_url else url
    dashboard_url = base_url + f"?project={project}" if project else base_url
    print(f"* Trackio UI launched at: {dashboard_url}")
    webbrowser.open(dashboard_url)
    utils.block_except_in_notebook()
