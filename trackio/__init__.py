import os
import webbrowser
from pathlib import Path

from gradio_client import Client

from trackio import context_vars, deploy, utils
from trackio.imports import import_csv
from trackio.run import Run
from trackio.sqlite_storage import SQLiteStorage
from trackio.ui import demo
from trackio.utils import TRACKIO_DIR, TRACKIO_LOGO_PATH

__version__ = Path(__file__).parent.joinpath("version.txt").read_text().strip()

__all__ = ["init", "log", "finish", "show", "import_csv"]


config = {}


def init(
    project: str,
    name: str | None = None,
    space_id: str | None = None,
    dataset_id: str | None = None,
    config: dict | None = None,
    resume: str = "never",
) -> Run:
    """
    Creates a new Trackio project and returns a Run object.

    Args:
        project: The name of the project (can be an existing project to continue tracking or a new project to start tracking from scratch).
        name: The name of the run (if not provided, a default name will be generated).
        space_id: If provided, the project will be logged to a Hugging Face Space instead of a local directory. Should be a complete Space name like "username/reponame" or "orgname/reponame", or just "reponame" in which case the Space will be created in the currently-logged-in Hugging Face user's namespace. If the Space does not exist, it will be created. If the Space already exists, the project will be logged to it.
        dataset_id: If provided, a persistent Hugging Face Dataset will be created and the metrics will be synced to it every 5 minutes. Should be a complete Dataset name like "username/datasetname" or "orgname/datasetname", or just "datasetname" in which case the Dataset will be created in the currently-logged-in Hugging Face user's namespace. If the Dataset does not exist, it will be created. If the Dataset already exists, the project will be appended to it. If not provided, the metrics will be logged to a local SQLite database, unless a `space_id` is provided, in which case a Dataset will be automatically created with the same name as the Space but with the "_dataset" suffix.
        config: A dictionary of configuration options. Provided for compatibility with wandb.init()
        resume: Controls how to handle resuming a run. Can be one of:
            - "must": Must resume the run with the given name, raises error if run doesn't exist
            - "allow": Resume the run if it exists, otherwise create a new run
            - "never": Never resume a run, always create a new one
    """
    url = context_vars.current_server.get()
    if url is None:
        if space_id is None:
            _, url, _ = demo.launch(
                show_api=False, inline=False, quiet=True, prevent_thread_lock=True
            )
        else:
            url = space_id
        context_vars.current_server.set(url)

    space_id, dataset_id = utils.preprocess_space_and_dataset_ids(space_id, dataset_id)

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
    )
    context_vars.current_run.set(run)
    globals()["config"] = run.config
    return run


def log(metrics: dict) -> None:
    """
    Logs metrics to the current run.

    Args:
        metrics: A dictionary of metrics to log.
    """
    if context_vars.current_run.get() is None:
        raise RuntimeError("Call trackio.init() before log().")
    context_vars.current_run.get().log(metrics)


def finish():
    """
    Finishes the current run.
    """
    if context_vars.current_run.get() is None:
        raise RuntimeError("Call trackio.init() before finish().")
    context_vars.current_run.get().finish()


def show(project: str | None = None):
    """
    Launches the Trackio dashboard.

    Args:
        project: The name of the project whose runs to show. If not provided, all projects will be shown and the user can select one.
    """
    _, url, share_url = demo.launch(
        show_api=False,
        quiet=True,
        inline=False,
        prevent_thread_lock=True,
        favicon_path=TRACKIO_LOGO_PATH,
        allowed_paths=[TRACKIO_LOGO_PATH],
    )
    base_url = share_url + "/" if share_url else url
    dashboard_url = base_url + f"?project={project}" if project else base_url
    print(f"* Trackio UI launched at: {dashboard_url}")
    webbrowser.open(dashboard_url)
    utils.block_except_in_notebook()
