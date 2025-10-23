import hashlib
import json
import logging
import os
import warnings
import webbrowser
from pathlib import Path
from typing import Any

from gradio.blocks import BUILT_IN_THEMES
from gradio.themes import Default as DefaultTheme
from gradio.themes import ThemeClass
from gradio_client import Client
from huggingface_hub import SpaceStorage

from trackio import context_vars, deploy, utils
from trackio.histogram import Histogram
from trackio.imports import import_csv, import_tf_events
from trackio.media import TrackioAudio, TrackioImage, TrackioVideo
from trackio.run import Run
from trackio.sqlite_storage import SQLiteStorage
from trackio.table import Table
from trackio.ui.main import demo
from trackio.utils import TRACKIO_DIR, TRACKIO_LOGO_DIR

logging.getLogger("httpx").setLevel(logging.WARNING)

warnings.filterwarnings(
    "ignore",
    message="Empty session being created. Install gradio\\[oauth\\]",
    category=UserWarning,
    module="gradio.helpers",
)

__version__ = json.loads(Path(__file__).parent.joinpath("package.json").read_text())[
    "version"
]

__all__ = [
    "init",
    "log",
    "finish",
    "show",
    "import_csv",
    "import_tf_events",
    "Image",
    "Video",
    "Audio",
    "Table",
    "Histogram",
]

Image = TrackioImage
Video = TrackioVideo
Audio = TrackioAudio


config = {}

DEFAULT_THEME = "default"


def init(
    project: str,
    name: str | None = None,
    group: str | None = None,
    space_id: str | None = None,
    space_storage: SpaceStorage | None = None,
    dataset_id: str | None = None,
    config: dict | None = None,
    resume: str = "never",
    settings: Any = None,
    private: bool | None = None,
    embed: bool = True,
) -> Run:
    """
    Creates a new Trackio project and returns a [`Run`] object.

    Args:
        project (`str`):
            The name of the project (can be an existing project to continue tracking or
            a new project to start tracking from scratch).
        name (`str`, *optional*):
            The name of the run (if not provided, a default name will be generated).
        group (`str`, *optional*):
            The name of the group which this run belongs to in order to help organize
            related runs together. You can toggle the entire group's visibilitiy in the
            dashboard.
        space_id (`str`, *optional*):
            If provided, the project will be logged to a Hugging Face Space instead of
            a local directory. Should be a complete Space name like
            `"username/reponame"` or `"orgname/reponame"`, or just `"reponame"` in which
            case the Space will be created in the currently-logged-in Hugging Face
            user's namespace. If the Space does not exist, it will be created. If the
            Space already exists, the project will be logged to it.
        space_storage ([`~huggingface_hub.SpaceStorage`], *optional*):
            Choice of persistent storage tier.
        dataset_id (`str`, *optional*):
            If a `space_id` is provided, a persistent Hugging Face Dataset will be
            created and the metrics will be synced to it every 5 minutes. Specify a
            Dataset with name like `"username/datasetname"` or `"orgname/datasetname"`,
            or `"datasetname"` (uses currently-logged-in Hugging Face user's namespace),
            or `None` (uses the same name as the Space but with the `"_dataset"`
            suffix). If the Dataset does not exist, it will be created. If the Dataset
            already exists, the project will be appended to it.
        config (`dict`, *optional*):
            A dictionary of configuration options. Provided for compatibility with
            `wandb.init()`.
        resume (`str`, *optional*, defaults to `"never"`):
            Controls how to handle resuming a run. Can be one of:

            - `"must"`: Must resume the run with the given name, raises error if run
              doesn't exist
            - `"allow"`: Resume the run if it exists, otherwise create a new run
            - `"never"`: Never resume a run, always create a new one
        private (`bool`, *optional*):
            Whether to make the Space private. If None (default), the repo will be
            public unless the organization's default is private. This value is ignored
            if the repo already exists.
        settings (`Any`, *optional*):
            Not used. Provided for compatibility with `wandb.init()`.
        embed (`bool`, *optional*, defaults to `True`):
            If running inside a jupyter/Colab notebook, whether the dashboard should
            automatically be embedded in the cell when trackio.init() is called.

    Returns:
        `Run`: A [`Run`] object that can be used to log metrics and finish the run.
    """
    if settings is not None:
        warnings.warn(
            "* Warning: settings is not used. Provided for compatibility with wandb.init(). Please create an issue at: https://github.com/gradio-app/trackio/issues if you need a specific feature implemented."
        )

    if space_id is None and dataset_id is not None:
        raise ValueError("Must provide a `space_id` when `dataset_id` is provided.")
    space_id, dataset_id = utils.preprocess_space_and_dataset_ids(space_id, dataset_id)
    url = context_vars.current_server.get()
    share_url = context_vars.current_share_server.get()

    if url is None:
        if space_id is None:
            _, url, share_url = demo.launch(
                show_api=False,
                inline=False,
                quiet=True,
                prevent_thread_lock=True,
                show_error=True,
                favicon_path=TRACKIO_LOGO_DIR / "trackio_logo_light.png",
                allowed_paths=[TRACKIO_LOGO_DIR, TRACKIO_DIR],
            )
        else:
            url = space_id
            share_url = None
        context_vars.current_server.set(url)
        context_vars.current_share_server.set(share_url)
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
            if utils.is_in_notebook() and embed:
                base_url = share_url + "/" if share_url else url
                full_url = utils.get_full_url(
                    base_url, project=project, write_token=demo.write_token
                )
                utils.embed_url_in_notebook(full_url)
            else:
                utils.print_dashboard_instructions(project)
        else:
            deploy.create_space_if_not_exists(
                space_id, space_storage, dataset_id, private
            )
            user_name, space_name = space_id.split("/")
            space_url = deploy.SPACE_HOST_URL.format(
                user_name=user_name, space_name=space_name
            )
            print(f"* View dashboard by going to: {space_url}")
            if utils.is_in_notebook() and embed:
                utils.embed_url_in_notebook(space_url)
    context_vars.current_project.set(project)

    client = None
    if not space_id:
        client = Client(url, verbose=False)

    if resume == "must":
        if name is None:
            raise ValueError("Must provide a run name when resume='must'")
        if name not in SQLiteStorage.get_runs(project):
            raise ValueError(f"Run '{name}' does not exist in project '{project}'")
        resumed = True
    elif resume == "allow":
        resumed = name is not None and name in SQLiteStorage.get_runs(project)
    elif resume == "never":
        if name is not None and name in SQLiteStorage.get_runs(project):
            warnings.warn(
                f"* Warning: resume='never' but a run '{name}' already exists in "
                f"project '{project}'. Generating a new name and instead. If you want "
                "to resume this run, call init() with resume='must' or resume='allow'."
            )
            name = None
        resumed = False
    else:
        raise ValueError("resume must be one of: 'must', 'allow', or 'never'")

    run = Run(
        url=url,
        project=project,
        client=client,
        name=name,
        group=group,
        config=config,
        space_id=space_id,
    )

    if resumed:
        print(f"* Resumed existing run: {run.name}")
    else:
        print(f"* Created new run: {run.name}")

    context_vars.current_run.set(run)
    globals()["config"] = run.config
    return run


def log(metrics: dict, step: int | None = None) -> None:
    """
    Logs metrics to the current run.

    Args:
        metrics (`dict`):
            A dictionary of metrics to log.
        step (`int`, *optional*):
            The step number. If not provided, the step will be incremented
            automatically.
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


def show(
    project: str | None = None,
    theme: str | ThemeClass | None = None,
    mcp_server: bool | None = None,
):
    """
    Launches the Trackio dashboard.

    Args:
        project (`str`, *optional*):
            The name of the project whose runs to show. If not provided, all projects
            will be shown and the user can select one.
        theme (`str` or `ThemeClass`, *optional*):
            A Gradio Theme to use for the dashboard instead of the default Gradio theme,
            can be a built-in theme (e.g. `'soft'`, `'citrus'`), a theme from the Hub
            (e.g. `"gstaff/xkcd"`), or a custom Theme class. If not provided, the
            `TRACKIO_THEME` environment variable will be used, or if that is not set, the
            default Gradio theme will be used.
        mcp_server (`bool`, *optional*):
            If `True`, the Trackio dashboard will be set up as an MCP server and certain
            functions will be added as MCP tools. If `None` (default behavior), then the
            `GRADIO_MCP_SERVER` environment variable will be used to determine if the
            MCP server should be enabled (which is `"True"` on Hugging Face Spaces).
    """
    theme = theme or os.environ.get("TRACKIO_THEME", DEFAULT_THEME)

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

    _mcp_server = (
        mcp_server
        if mcp_server is not None
        else os.environ.get("GRADIO_MCP_SERVER", "False") == "True"
    )

    _, url, share_url = demo.launch(
        show_api=_mcp_server,
        quiet=True,
        inline=False,
        prevent_thread_lock=True,
        favicon_path=TRACKIO_LOGO_DIR / "trackio_logo_light.png",
        allowed_paths=[TRACKIO_LOGO_DIR, TRACKIO_DIR],
        mcp_server=_mcp_server,
    )

    base_url = share_url + "/" if share_url else url
    full_url = utils.get_full_url(
        base_url, project=project, write_token=demo.write_token
    )

    if not utils.is_in_notebook():
        print(f"* Trackio UI launched at: {full_url}")
        webbrowser.open(full_url)
        utils.block_main_thread_until_keyboard_interrupt()
    else:
        utils.embed_url_in_notebook(full_url)
