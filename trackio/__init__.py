import glob
import json
import logging
import os
import warnings
import webbrowser
from pathlib import Path
from typing import Any

import huggingface_hub
from gradio.themes import ThemeClass
from gradio.utils import TupleNoPrint
from gradio_client import Client, handle_file
from huggingface_hub import SpaceStorage
from huggingface_hub.errors import LocalTokenNotFoundError

from trackio import context_vars, deploy, utils
from trackio.deploy import sync
from trackio.histogram import Histogram
from trackio.imports import import_csv, import_tf_events
from trackio.media import TrackioAudio, TrackioImage, TrackioVideo
from trackio.run import Run
from trackio.sqlite_storage import SQLiteStorage
from trackio.table import Table
from trackio.typehints import UploadEntry
from trackio.ui.main import CSS, HEAD, demo
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
    "sync",
    "delete_project",
    "import_csv",
    "import_tf_events",
    "save",
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
    try:
        space_id, dataset_id = utils.preprocess_space_and_dataset_ids(
            space_id, dataset_id
        )
    except LocalTokenNotFoundError as e:
        raise LocalTokenNotFoundError(
            f"You must be logged in to Hugging Face locally when `space_id` is provided to deploy to a Space. {e}"
        ) from e
    url = context_vars.current_server.get()
    share_url = context_vars.current_share_server.get()

    if url is None:
        if space_id is None:
            _, url, share_url = demo.launch(
                css=CSS,
                head=HEAD,
                footer_links=["gradio", "settings"],
                inline=False,
                quiet=True,
                prevent_thread_lock=True,
                show_error=True,
                favicon_path=TRACKIO_LOGO_DIR / "trackio_logo_light.png",
                allowed_paths=[TRACKIO_LOGO_DIR, TRACKIO_DIR],
            )
            context_vars.current_space_id.set(None)
        else:
            url = space_id
            share_url = None
            context_vars.current_space_id.set(space_id)

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
                    base_url, project=project, write_token=demo.write_token, footer=True
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


def delete_project(project: str, force: bool = False) -> bool:
    """
    Deletes a project by removing its local SQLite database.

    Args:
        project (`str`):
            The name of the project to delete.
        force (`bool`, *optional*, defaults to `False`):
            If `True`, deletes the project without prompting for confirmation.
            If `False`, prompts the user to confirm before deleting.

    Returns:
        `bool`: `True` if the project was deleted, `False` otherwise.
    """
    db_path = SQLiteStorage.get_project_db_path(project)

    if not db_path.exists():
        print(f"* Project '{project}' does not exist.")
        return False

    if not force:
        response = input(
            f"Are you sure you want to delete project '{project}'? "
            f"This will permanently delete all runs and metrics. (y/N): "
        )
        if response.lower() not in ["y", "yes"]:
            print("* Deletion cancelled.")
            return False

    try:
        db_path.unlink()

        for suffix in ("-wal", "-shm"):
            sidecar = Path(str(db_path) + suffix)
            if sidecar.exists():
                sidecar.unlink()

        print(f"* Project '{project}' has been deleted.")
        return True
    except Exception as e:
        print(f"* Error deleting project '{project}': {e}")
        return False


def save(
    glob_str: str | Path,
    project: str | None = None,
) -> str:
    """
    Saves files to a project (not linked to a specific run). If Trackio is running
    locally, the file(s) will be moved to the project's files directory. If Trackio is
    running in a Space, the file(s) will be uploaded to the Space's files directory.

    Args:
        glob_str (`str` or `Path`):
            The file path or glob pattern to save. Can be a single file or a pattern
            matching multiple files (e.g., `"*.py"`, `"models/**/*.pth"`).
        project (`str`, *optional*):
            The name of the project to save files to. If not provided, uses the current
            project from `trackio.init()`. If no project is initialized, raises an
            error.

    Returns:
        `str`: The path where the file(s) were saved (project's files directory).

    Example:
        ```python
        import trackio

        trackio.init(project="my-project")
        trackio.save("config.yaml")
        trackio.save("models/*.pth")
        ```
    """
    if project is None:
        project = context_vars.current_project.get()
        if project is None:
            raise RuntimeError(
                "No project specified. Either call trackio.init() first or provide a "
                "project parameter to trackio.save()."
            )

    glob_str = Path(glob_str)
    base_path = Path.cwd().resolve()

    matched_files = []
    if glob_str.is_file():
        matched_files = [glob_str.resolve()]
    else:
        pattern = str(glob_str)
        if not glob_str.is_absolute():
            pattern = str((Path.cwd() / glob_str).resolve())
        matched_files = [
            Path(f).resolve()
            for f in glob.glob(pattern, recursive=True)
            if Path(f).is_file()
        ]

    if not matched_files:
        raise ValueError(f"No files found matching pattern: {glob_str}")

    url = context_vars.current_server.get()
    current_run = context_vars.current_run.get()

    upload_entries = []

    for file_path in matched_files:
        try:
            relative_to_base = file_path.relative_to(base_path)
        except ValueError:
            relative_to_base = Path(file_path.name)

        if current_run is not None:
            # If a run is active, use its queue to upload the file to the project's files directory
            # as it's more efficent than uploading files one by one. But we should not use the run name
            # as the files should be stored in the project's files directory, not the run's, hence
            # the use_run_name flag is set to False.
            current_run._queue_upload(
                file_path,
                step=None,
                relative_path=str(relative_to_base.parent),
                use_run_name=False,
            )
        else:
            upload_entry: UploadEntry = {
                "project": project,
                "run": None,
                "step": None,
                "relative_path": str(relative_to_base),
                "uploaded_file": handle_file(file_path),
            }
            upload_entries.append(upload_entry)

    if upload_entries:
        if url is None:
            raise RuntimeError(
                "No server available. Call trackio.init() before trackio.save() to start the server."
            )

        try:
            client = Client(url, verbose=False, httpx_kwargs={"timeout": 90})
            client.predict(
                api_name="/bulk_upload_media",
                uploads=upload_entries,
                hf_token=huggingface_hub.utils.get_token(),
            )
        except Exception as e:
            warnings.warn(
                f"Failed to upload files: {e}. "
                "Files may not be available in the dashboard."
            )

    return str(utils.MEDIA_DIR / project / "files")


def show(
    project: str | None = None,
    *,
    theme: str | ThemeClass | None = None,
    mcp_server: bool | None = None,
    footer: bool = True,
    color_palette: list[str] | None = None,
    open_browser: bool = True,
    block_thread: bool | None = None,
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
            `TRACKIO_THEME` environment variable will be used, or if that is not set,
            the default Gradio theme will be used.
        mcp_server (`bool`, *optional*):
            If `True`, the Trackio dashboard will be set up as an MCP server and certain
            functions will be added as MCP tools. If `None` (default behavior), then the
            `GRADIO_MCP_SERVER` environment variable will be used to determine if the
            MCP server should be enabled (which is `"True"` on Hugging Face Spaces).
        footer (`bool`, *optional*, defaults to `True`):
            Whether to show the Gradio footer. When `False`, the footer will be hidden.
            This can also be controlled via the `footer` query parameter in the URL.
        color_palette (`list[str]`, *optional*):
            A list of hex color codes to use for plot lines. If not provided, the
            `TRACKIO_COLOR_PALETTE` environment variable will be used (comma-separated
            hex codes), or if that is not set, the default color palette will be used.
            Example: `['#FF0000', '#00FF00', '#0000FF']`
        open_browser (`bool`, *optional*, defaults to `True`):
            If `True` and not in a notebook, a new browser tab will be opened with the
            dashboard. If `False`, the browser will not be opened.
        block_thread (`bool`, *optional*):
            If `True`, the main thread will be blocked until the dashboard is closed.
            If `None` (default behavior), then the main thread will not be blocked if the
            dashboard is launched in a notebook, otherwise the main thread will be blocked.

        Returns:
            `app`: The Gradio app object corresponding to the dashboard launched by Trackio.
            `url`: The local URL of the dashboard.
            `share_url`: The public share URL of the dashboard.
            `full_url`: The full URL of the dashboard including the write token (will use the public share URL if launched publicly, otherwise the local URL).
    """
    if color_palette is not None:
        os.environ["TRACKIO_COLOR_PALETTE"] = ",".join(color_palette)

    theme = theme or os.environ.get("TRACKIO_THEME")

    _mcp_server = (
        mcp_server
        if mcp_server is not None
        else os.environ.get("GRADIO_MCP_SERVER", "False") == "True"
    )

    app, url, share_url = demo.launch(
        css=CSS,
        head=HEAD,
        footer_links=["gradio", "settings"] + (["api"] if _mcp_server else []),
        quiet=True,
        inline=False,
        prevent_thread_lock=True,
        favicon_path=TRACKIO_LOGO_DIR / "trackio_logo_light.png",
        allowed_paths=[TRACKIO_LOGO_DIR, TRACKIO_DIR],
        mcp_server=_mcp_server,
        theme=theme,
    )

    base_url = share_url + "/" if share_url else url
    full_url = utils.get_full_url(
        base_url, project=project, write_token=demo.write_token, footer=footer
    )

    if not utils.is_in_notebook():
        print(f"* Trackio UI launched at: {full_url}")
        if open_browser:
            webbrowser.open(full_url)
        block_thread = block_thread if block_thread is not None else True
    else:
        utils.embed_url_in_notebook(full_url)
        block_thread = block_thread if block_thread is not None else False

    if block_thread:
        utils.block_main_thread_until_keyboard_interrupt()
    return TupleNoPrint((demo, url, share_url, full_url))
