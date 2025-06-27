import os
from pathlib import Path

import pandas as pd

from trackio import deploy, utils
from trackio.sqlite_storage import SQLiteStorage


def import_csv(
    csv_path: str,
    project: str,
    name: str | None = None,
    space_id: str | None = None,
    dataset_id: str | None = None,
) -> None:
    """
    Imports a CSV file into a Trackio project. The CSV file must contain a "step" column, may optionally
    contain a "timestamp" column, and any other columns will be treated as metrics. It should also include
    a header row with the column names.

    TODO: call init() and return a Run object so that the user can continue to log metrics to it.

    Args:
        csv_path: The str or Path to the CSV file to import.
        project: The name of the project to import the CSV file into. Must not be an existing project.
        name: The name of the Run to import the CSV file into. If not provided, a default name will be generated.
        name: The name of the run (if not provided, a default name will be generated).
        space_id: If provided, the project will be logged to a Hugging Face Space instead of a local directory. Should be a complete Space name like "username/reponame" or "orgname/reponame", or just "reponame" in which case the Space will be created in the currently-logged-in Hugging Face user's namespace. If the Space does not exist, it will be created. If the Space already exists, the project will be logged to it.
        dataset_id: If provided, a persistent Hugging Face Dataset will be created and the metrics will be synced to it every 5 minutes. Should be a complete Dataset name like "username/datasetname" or "orgname/datasetname", or just "datasetname" in which case the Dataset will be created in the currently-logged-in Hugging Face user's namespace. If the Dataset does not exist, it will be created. If the Dataset already exists, the project will be appended to it. If not provided, the metrics will be logged to a local SQLite database, unless a `space_id` is provided, in which case a Dataset will be automatically created with the same name as the Space but with the "_dataset" suffix.
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

    numeric_columns = [
        c
        for c in df.select_dtypes(include="number").columns
        if c not in {step_column, "timestamp"}
    ]

    col_indices = [df.columns.get_loc(c) for c in numeric_columns]
    step_idx = df.columns.get_loc(step_column)
    ts_idx = df.columns.get_loc("timestamp") if "timestamp" in df.columns else None

    for row in df.itertuples(index=False, name=None):
        metrics = {}
        for metric_name, idx in zip(numeric_columns, col_indices):
            val = row[idx]
            if pd.notna(val):
                metrics[metric_name] = float(val)

        if metrics:
            metrics_list.append(metrics)
            steps.append(int(row[step_idx]))

            if ts_idx is not None and pd.notna(row[ts_idx]):
                timestamps.append(str(row[ts_idx]))
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

    if len(metrics_list) > 1000:
        warning = "Warning: Importing more than 1000 rows may produce plots that render slowly."
    else:
        warning = ""

    print(
        f"* Imported {len(metrics_list)} rows from {csv_path} into project '{project}' as run '{name}'. {warning}"
    )
    print(f"* Metrics found: {', '.join(metrics_list[0].keys())}")

    space_id, dataset_id = utils.preprocess_space_and_dataset_ids(space_id, dataset_id)
    if dataset_id is not None:
        os.environ["TRACKIO_DATASET_ID"] = dataset_id
        print(f"* Trackio metrics will be synced to Hugging Face Dataset: {dataset_id}")

    if space_id is None:
        utils.print_dashboard_instructions(project)
    else:
        deploy.create_space_if_not_exists(space_id, dataset_id)
        deploy.wait_until_space_exists(space_id)
        deploy.upload_db_to_space(project, space_id)
        print(
            f"* View dashboard by going to: {deploy.SPACE_URL.format(space_id=space_id)}"
        )
