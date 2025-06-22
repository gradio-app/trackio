import contextvars
import time
import webbrowser
from pathlib import Path

import huggingface_hub
from gradio_client import Client
from httpx import ReadTimeout
from huggingface_hub.errors import RepositoryNotFoundError

from trackio.deploy import deploy_as_space
from trackio.run import Run
from trackio.sqlite_storage import SQLiteStorage
from trackio.ui import demo
from trackio.utils import TRACKIO_DIR, TRACKIO_LOGO_PATH, block_except_in_notebook

__version__ = Path(__file__).parent.joinpath("version.txt").read_text().strip()


current_run: contextvars.ContextVar[Run | None] = contextvars.ContextVar(
    "current_run", default=None
)
current_project: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "current_project", default=None
)
current_server: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "current_server", default=None
)

config = {}
SPACE_URL = "https://huggingface.co/spaces/{space_id}"

YELLOW = "\033[93m"
BOLD = "\033[1m"
RESET = "\033[0m"


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
    if not current_server.get() and space_id is None:
        _, url, _ = demo.launch(
            show_api=False, inline=False, quiet=True, prevent_thread_lock=True
        )
        current_server.set(url)
    else:
        url = current_server.get()

    if current_project.get() is None or current_project.get() != project:
        print(f"* Trackio project initialized: {project}")

        if space_id is None:
            print(f"* Trackio metrics logged to: {TRACKIO_DIR}")
            print("* View dashboard by running in your terminal:")
            print(f'{BOLD}{YELLOW}trackio show --project "{project}"{RESET}')
            print(f'* or by running in Python: trackio.show(project="{project}")')
        else:
            create_space_if_not_exists(space_id, dataset_id)
            print(
                f"* View dashboard by going to: {SPACE_URL.format(space_id=space_id)}"
            )
    current_project.set(project)

    space_or_url = space_id if space_id else url
    client = Client(space_or_url, verbose=False)

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
        project=project, client=client, name=name, config=config, dataset_id=dataset_id
    )
    current_run.set(run)
    globals()["config"] = run.config
    return run


def create_space_if_not_exists(
    space_id: str,
    dataset_id: str | None = None,
) -> None:
    """
    Creates a new Hugging Face Space if it does not exist.

    Args:
        space_id: The ID of the Space to create.
        dataset_id: The ID of the Dataset to create.
    """
    if "/" not in space_id:
        username = huggingface_hub.whoami()["name"]
        space_id = f"{username}/{space_id}"
    if dataset_id is not None and "/" not in dataset_id:
        username = huggingface_hub.whoami()["name"]
        dataset_id = f"{username}/{dataset_id}"
    if dataset_id is None:
        dataset_id = f"{space_id}_dataset"
    try:
        huggingface_hub.repo_info(space_id, repo_type="space")
        print(f"* Found existing space: {SPACE_URL.format(space_id=space_id)}")
        return
    except RepositoryNotFoundError:
        pass

    print(f"* Creating new space: {SPACE_URL.format(space_id=space_id)}")
    deploy_as_space(space_id, dataset_id)

    client = None
    for _ in range(30):
        try:
            client = Client(space_id, verbose=False)
            if client:
                break
        except ReadTimeout:
            print("* Space is not yet ready. Waiting 5 seconds...")
            time.sleep(5)
        except ValueError as e:
            print(f"* Space gave error {e}. Trying again in 5 seconds...")
            time.sleep(5)


def log(metrics: dict) -> None:
    """
    Logs metrics to the current run.

    Args:
        metrics: A dictionary of metrics to log.
    """
    if current_run.get() is None:
        raise RuntimeError("Call trackio.init() before log().")
    current_run.get().log(metrics)


def finish():
    """
    Finishes the current run.
    """
    if current_run.get() is None:
        raise RuntimeError("Call trackio.init() before finish().")
    current_run.get().finish()


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
    block_except_in_notebook()
