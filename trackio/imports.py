import os
from pathlib import Path

import pandas as pd

from trackio import deploy, utils
from trackio.sqlite_storage import SQLiteStorage


def import_csv(
    csv_path: str | Path,
    project: str,
    name: str | None = None,
    space_id: str | None = None,
    dataset_id: str | None = None,
    private: bool | None = None,
    force: bool = False,
) -> None:
    """
    Imports a CSV file into a Trackio project. The CSV file must contain a `"step"`
    column, may optionally contain a `"timestamp"` column, and any other columns will be
    treated as metrics. It should also include a header row with the column names.

    TODO: call init() and return a Run object so that the user can continue to log metrics to it.

    Args:
        csv_path (`str` or `Path`):
            The str or Path to the CSV file to import.
        project (`str`):
            The name of the project to import the CSV file into. Must not be an existing
            project.
        name (`str`, *optional*):
            The name of the Run to import the CSV file into. If not provided, a default
            name will be generated.
        name (`str`, *optional*):
            The name of the run (if not provided, a default name will be generated).
        space_id (`str`, *optional*):
            If provided, the project will be logged to a Hugging Face Space instead of a
            local directory. Should be a complete Space name like `"username/reponame"`
            or `"orgname/reponame"`, or just `"reponame"` in which case the Space will
            be created in the currently-logged-in Hugging Face user's namespace. If the
            Space does not exist, it will be created. If the Space already exists, the
            project will be logged to it.
        dataset_id (`str`, *optional*):
            If provided, a persistent Hugging Face Dataset will be created and the
            metrics will be synced to it every 5 minutes. Should be a complete Dataset
            name like `"username/datasetname"` or `"orgname/datasetname"`, or just
            `"datasetname"` in which case the Dataset will be created in the
            currently-logged-in Hugging Face user's namespace. If the Dataset does not
            exist, it will be created. If the Dataset already exists, the project will
            be appended to it. If not provided, the metrics will be logged to a local
            SQLite database, unless a `space_id` is provided, in which case a Dataset
            will be automatically created with the same name as the Space but with the
            `"_dataset"` suffix.
        private (`bool`, *optional*):
            Whether to make the Space private. If None (default), the repo will be
            public unless the organization's default is private. This value is ignored
            if the repo already exists.
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
            value = row[column]
            if bool(pd.notna(value)):
                metrics[column] = float(value)

        if metrics:
            metrics_list.append(metrics)
            steps.append(int(row[step_column]))

            if "timestamp" in df.columns and bool(pd.notna(row["timestamp"])):
                timestamps.append(str(row["timestamp"]))
            else:
                timestamps.append("")

    if metrics_list:
        SQLiteStorage.bulk_log(
            project=project,
            run=name,
            metrics_list=metrics_list,
            steps=steps,
            timestamps=timestamps,
        )

    print(
        f"* Imported {len(metrics_list)} rows from {csv_path} into project '{project}' as run '{name}'"
    )
    print(f"* Metrics found: {', '.join(metrics_list[0].keys())}")

    space_id, dataset_id = utils.preprocess_space_and_dataset_ids(space_id, dataset_id)
    if dataset_id is not None:
        os.environ["TRACKIO_DATASET_ID"] = dataset_id
        print(f"* Trackio metrics will be synced to Hugging Face Dataset: {dataset_id}")

    if space_id is None:
        utils.print_dashboard_instructions(project)
    else:
        deploy.create_space_if_not_exists(
            space_id=space_id, dataset_id=dataset_id, private=private
        )
        deploy.wait_until_space_exists(space_id=space_id)
        deploy.upload_db_to_space(project=project, space_id=space_id, force=force)
        print(
            f"* View dashboard by going to: {deploy.SPACE_URL.format(space_id=space_id)}"
        )


def import_tf_events(
    log_dir: str | Path,
    project: str,
    name: str | None = None,
    space_id: str | None = None,
    dataset_id: str | None = None,
    private: bool | None = None,
    force: bool = False,
) -> None:
    """
    Imports TensorFlow Events files from a directory into a Trackio project. Each
    subdirectory in the log directory will be imported as a separate run.

    Args:
        log_dir (`str` or `Path`):
            The str or Path to the directory containing TensorFlow Events files.
        project (`str`):
            The name of the project to import the TensorFlow Events files into. Must not
            be an existing project.
        name (`str`, *optional*):
            The name prefix for runs (if not provided, will use directory names). Each
            subdirectory will create a separate run.
        space_id (`str`, *optional*):
            If provided, the project will be logged to a Hugging Face Space instead of a
            local directory. Should be a complete Space name like `"username/reponame"`
            or `"orgname/reponame"`, or just `"reponame"` in which case the Space will
            be created in the currently-logged-in Hugging Face user's namespace. If the
            Space does not exist, it will be created. If the Space already exists, the
            project will be logged to it.
        dataset_id (`str`, *optional*):
            If provided, a persistent Hugging Face Dataset will be created and the
            metrics will be synced to it every 5 minutes. Should be a complete Dataset
            name like `"username/datasetname"` or `"orgname/datasetname"`, or just
            `"datasetname"` in which case the Dataset will be created in the
            currently-logged-in Hugging Face user's namespace. If the Dataset does not
            exist, it will be created. If the Dataset already exists, the project will
            be appended to it. If not provided, the metrics will be logged to a local
            SQLite database, unless a `space_id` is provided, in which case a Dataset
            will be automatically created with the same name as the Space but with the
            `"_dataset"` suffix.
        private (`bool`, *optional*):
            Whether to make the Space private. If None (default), the repo will be
            public unless the organization's default is private. This value is ignored
            if the repo already exists.
    """
    try:
        from tbparse import SummaryReader
    except ImportError:
        raise ImportError(
            "The `tbparse` package is not installed but is required for `import_tf_events`. Please install trackio with the `tensorboard` extra: `pip install trackio[tensorboard]`."
        )

    if SQLiteStorage.get_runs(project):
        raise ValueError(
            f"Project '{project}' already exists. Cannot import TF events into existing project."
        )

    path = Path(log_dir)
    if not path.exists():
        raise FileNotFoundError(f"TF events directory not found: {path}")

    # Use tbparse to read all tfevents files in the directory structure
    reader = SummaryReader(str(path), extra_columns={"dir_name"})
    df = reader.scalars

    if df.empty:
        raise ValueError(f"No TensorFlow events data found in {path}")

    total_imported = 0
    imported_runs = []

    # Group by dir_name to create separate runs
    for dir_name, group_df in df.groupby("dir_name"):
        try:
            # Determine run name based on directory name
            if dir_name == "":
                run_name = "main"  # For files in the root directory
            else:
                run_name = dir_name  # Use directory name

            if name:
                run_name = f"{name}_{run_name}"

            if group_df.empty:
                print(f"* Skipping directory {dir_name}: no scalar data found")
                continue

            metrics_list = []
            steps = []
            timestamps = []

            for _, row in group_df.iterrows():
                # Convert row values to appropriate types
                tag = str(row["tag"])
                value = float(row["value"])
                step = int(row["step"])

                metrics = {tag: value}
                metrics_list.append(metrics)
                steps.append(step)

                # Use wall_time if present, else fallback
                if "wall_time" in group_df.columns and not bool(
                    pd.isna(row["wall_time"])
                ):
                    timestamps.append(str(row["wall_time"]))
                else:
                    timestamps.append("")

            if metrics_list:
                SQLiteStorage.bulk_log(
                    project=project,
                    run=str(run_name),
                    metrics_list=metrics_list,
                    steps=steps,
                    timestamps=timestamps,
                )

                total_imported += len(metrics_list)
                imported_runs.append(run_name)

                print(
                    f"* Imported {len(metrics_list)} scalar events from directory '{dir_name}' as run '{run_name}'"
                )
                print(f"* Metrics in this run: {', '.join(set(group_df['tag']))}")

        except Exception as e:
            print(f"* Error processing directory {dir_name}: {e}")
            continue

    if not imported_runs:
        raise ValueError("No valid TensorFlow events data could be imported")

    print(f"* Total imported events: {total_imported}")
    print(f"* Created runs: {', '.join(imported_runs)}")

    space_id, dataset_id = utils.preprocess_space_and_dataset_ids(space_id, dataset_id)
    if dataset_id is not None:
        os.environ["TRACKIO_DATASET_ID"] = dataset_id
        print(f"* Trackio metrics will be synced to Hugging Face Dataset: {dataset_id}")

    if space_id is None:
        utils.print_dashboard_instructions(project)
    else:
        deploy.create_space_if_not_exists(
            space_id, dataset_id=dataset_id, private=private
        )
        deploy.wait_until_space_exists(space_id)
        deploy.upload_db_to_space(project, space_id, force=force)
        print(
            f"* View dashboard by going to: {deploy.SPACE_URL.format(space_id=space_id)}"
        )
