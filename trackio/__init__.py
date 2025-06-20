import contextvars
import os
import webbrowser
from pathlib import Path

import pandas as pd
from gradio_client import Client

from trackio import deploy, utils
from trackio.run import Run
from trackio.sqlite_storage import SQLiteStorage
from trackio.ui import demo
from trackio.utils import TRACKIO_DIR, TRACKIO_LOGO_PATH

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
        space_id: If provided, the project will be logged to a Hugging Face Space instead of a local directory. Should be a complete Space name like "username/reponame". If the Space does not exist, it will be created. If the Space already exists, the project will be logged to it.
        dataset_id: If provided, a persistent Hugging Face Dataset will be created and the metrics will be synced to it every 5 minutes. Should be a complete Dataset name like "username/datasetname". If the Dataset does not exist, it will be created. If the Dataset already exists, the project will be appended to it.
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
        project=project, client=client, name=name, config=config
    )
    current_run.set(run)
    globals()["config"] = run.config
    return run


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
    utils.block_except_in_notebook()


def import_csv(
    csv_path: str,
    project: str,
    name: str | None = None,
    space_id: str | None = None,
    dataset_id: str | None = None,
) -> None:
    """
    Imports a CSV file into a Trackio project.

    Args:
        csv_path: The str or Path to the CSV file to import.
        project: The name of the project to import the CSV file into. Must not be an existing project.
        name: The name of the Run to import the CSV file into. If not provided, a default name will be generated.
        space_id: If provided, the project will be logged to a Hugging Face Space instead of a local directory. Should be a complete Space name like "username/reponame". If the Space does not exist, it will be created. If the Space already exists, the project will be logged to it.
        dataset_id: If provided, a persistent Hugging Face Dataset will be created and the metrics will be synced to it every 5 minutes. Should be a complete Dataset name like "username/datasetname". If the Dataset does not exist, it will be created. If the Dataset already exists, the project will be appended to it.
    """
    if SQLiteStorage.get_runs(project):
        raise ValueError(
            f"Project '{project}' already exists. Cannot import CSV into existing project."
        )

    csv_path = Path(csv_path)
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV file not found: {csv_path}")

    df = pd.read_csv(csv_path)
    if df.empty:
        raise ValueError("CSV file is empty")

    column_mapping = utils.simplify_column_names(df.columns.tolist())
    df = df.rename(columns=column_mapping)

    step_column = None
    for col in df.columns:
        if col.lower() == "step":
            step_column = col
            break

    if step_column is None:
        raise ValueError("CSV file must contain a 'step' or 'Step' column")

    if name is None:
        name = csv_path.stem

    storage = SQLiteStorage(project, name, {})

    metrics_list = []
    steps = []
    timestamps = []

    numeric_columns = []
    for column in df.columns:
        if column == step_column:
            continue
        if column == "timestamp":
            continue

        try:
            pd.to_numeric(df[column], errors="raise")
            numeric_columns.append(column)
        except (ValueError, TypeError):
            continue

    for _, row in df.iterrows():
        metrics = {}
        for column in numeric_columns:
            if pd.notna(row[column]):
                metrics[column] = float(row[column])

        if metrics:
            metrics_list.append(metrics)
            steps.append(int(row[step_column]))

            if "timestamp" in df.columns and pd.notna(row["timestamp"]):
                timestamps.append(str(row["timestamp"]))
            else:
                timestamps.append("")

    if metrics_list:
        storage.bulk_log(metrics_list, steps, timestamps)

    print(
        f"* Imported {len(metrics_list)} rows from {csv_path} into project '{project}' as run '{name}'"
    )
    print(
        f"* Metrics found: {', '.join(metrics_list[0].keys())}"
    )
    if space_id is None:
        utils.print_dashboard_instructions(project)
    else:
        deploy.create_space_if_not_exists(space_id, dataset_id)
        print(
            f"* View dashboard by going to: {deploy.SPACE_URL.format(space_id=space_id)}"
        )
