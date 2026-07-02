import csv
import fnmatch
import json
import os
from datetime import datetime, timezone
from pathlib import Path

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
            Deprecated. Use `bucket_id` instead.
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

    with csv_path.open(newline="", encoding="utf-8") as csv_file:
        reader = csv.DictReader(csv_file)
        source_columns = reader.fieldnames or []
        rows = list(reader)

    if not rows:
        raise ValueError("CSV file is empty")

    column_mapping = utils.simplify_column_names(source_columns)
    normalized_rows = [
        {column_mapping[key]: value for key, value in row.items()} for row in rows
    ]
    columns = list(normalized_rows[0].keys())

    step_column = None
    for col in columns:
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
    for column in columns:
        if column == step_column:
            continue
        if column == "timestamp":
            continue

        try:
            for row in normalized_rows:
                value = row[column]
                if value in ("", None):
                    continue
                float(value)
        except (ValueError, TypeError):
            continue
        numeric_columns.append(column)

    for row in normalized_rows:
        metrics = {}
        for column in numeric_columns:
            value = row[column]
            if value not in ("", None):
                metrics[column] = float(value)

        if metrics:
            metrics_list.append(metrics)
            steps.append(int(float(row[step_column])))

            if "timestamp" in row and row["timestamp"] not in ("", None):
                timestamps.append(str(row["timestamp"]))
            else:
                timestamps.append("")

    if not metrics_list:
        raise ValueError(
            f"No numeric metric data found in CSV file: {csv_path}. Columns other "
            "than 'step' and 'timestamp' must contain numeric values."
        )

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

    space_id, dataset_id, _ = utils.preprocess_space_and_dataset_ids(
        space_id, dataset_id
    )
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
            Deprecated. Use `bucket_id` instead.
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
                if "wall_time" in group_df.columns and not utils.is_missing_value(
                    row["wall_time"]
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

    space_id, dataset_id, _ = utils.preprocess_space_and_dataset_ids(
        space_id, dataset_id
    )
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


def _wandb_step_metric_definitions(json_config: str) -> dict[str, str]:
    """
    Extracts `wandb.define_metric()` step-metric mappings from a wandb run config.

    wandb stores metric definitions in the run config under `_wandb.value.m` as a
    list of records keyed by `MetricRecord` protobuf field number: `"1"` is the
    metric name, `"2"` is a metric glob, `"4"` is the step metric name, and `"5"`
    is the 1-based index of the record that defines the metric's step metric (the
    client writes the name, the server rewrites it to an index). Returns a mapping
    of metric name/glob -> step metric name.
    """
    try:
        records = (
            json.loads(json_config).get("_wandb", {}).get("value", {}).get("m", [])
        )
    except (ValueError, TypeError, AttributeError):
        return {}
    if not isinstance(records, list):
        return {}
    mapping: dict[str, str] = {}
    for record in records:
        if not isinstance(record, dict):
            continue
        pattern = record.get("1") or record.get("2")
        if not pattern:
            continue
        step_metric = record.get("4")
        step_index = record.get("5")
        if not step_metric and isinstance(step_index, int):
            if 1 <= step_index <= len(records) and isinstance(
                records[step_index - 1], dict
            ):
                step_metric = records[step_index - 1].get("1")
        if step_metric:
            mapping[str(pattern)] = str(step_metric)
    return mapping


def _resolve_step_metric(key: str, step_metrics: dict[str, str]) -> str | None:
    """Resolves the step metric for a key: exact match first, then glob patterns."""
    if key in step_metrics:
        return step_metrics[key]
    for pattern, step_metric in step_metrics.items():
        if fnmatch.fnmatchcase(key, pattern):
            return step_metric
    return None


def import_wandb(
    wandb_project: str,
    project: str,
    run_ids: list[str] | None = None,
    name: str | None = None,
    step_metrics: dict[str, str] | None = None,
    space_id: str | None = None,
    dataset_id: str | None = None,
    private: bool | None = None,
    force: bool = False,
) -> None:
    """
    Imports the runs of a Weights & Biases project into a Trackio project. Each wandb
    run is imported as a separate run, with its full metric history and config.

    Metrics logged with a custom step metric (`wandb.define_metric(..., step_metric=...)`)
    are imported at the value of that step metric, so they keep the same x-axis as in
    wandb. This matters because wandb merges everything logged at the same internal step
    into one history row: without splitting, metrics on a custom axis would be imported
    at the wrong step. Step-metric definitions are read from each run's stored config
    and can be extended or overridden with the `step_metrics` argument; the step-metric
    keys themselves are encoded as steps rather than imported as metrics.

    Args:
        wandb_project (`str`):
            The wandb project to import, as `"entity/project"`.
        project (`str`):
            The name of the Trackio project to import the runs into. Must not be an
            existing project.
        run_ids (`list[str]`, *optional*):
            If provided, only the wandb runs with these IDs are imported. By default,
            all runs of the wandb project are imported.
        name (`str`, *optional*):
            A name prefix for the imported runs (if not provided, the wandb run names
            are used as-is).
        step_metrics (`dict[str, str]`, *optional*):
            A mapping of metric name (or glob, e.g. `"eval/*"`) to the metric that
            serves as its x-axis, e.g. `{"eval/*": "eval_iter"}`. Merged with (and
            taking precedence over) the definitions stored in each run.
        space_id (`str`, *optional*):
            If provided, the project will be logged to a Hugging Face Space instead of a
            local directory. Should be a complete Space name like `"username/reponame"`
            or `"orgname/reponame"`, or just `"reponame"` in which case the Space will
            be created in the currently-logged-in Hugging Face user's namespace. If the
            Space does not exist, it will be created. If the Space already exists, the
            project will be logged to it.
        dataset_id (`str`, *optional*):
            Deprecated. Use `bucket_id` instead.
        private (`bool`, *optional*):
            Whether to make the Space private. If None (default), the repo will be
            public unless the organization's default is private. This value is ignored
            if the repo already exists.
    """
    try:
        import wandb
    except ImportError:
        raise ImportError(
            "The `wandb` package is not installed but is required for `import_wandb`. Please install trackio with the `wandb` extra: `pip install trackio[wandb]`."
        )

    if SQLiteStorage.get_runs(project):
        raise ValueError(
            f"Project '{project}' already exists. Cannot import wandb runs into existing project."
        )

    api = wandb.Api()
    runs = list(api.runs(wandb_project))
    if run_ids is not None:
        runs = [run for run in runs if run.id in run_ids]
    if not runs:
        raise ValueError(f"No wandb runs found in '{wandb_project}'")

    internal_keys = {"_step", "_runtime", "_timestamp", "_wandb"}
    total_imported = 0
    imported_runs = []
    used_names = set()

    for run in runs:
        run_step_metrics = _wandb_step_metric_definitions(
            getattr(run, "json_config", None) or "{}"
        )
        run_step_metrics.update(step_metrics or {})
        axis_keys = set(run_step_metrics.values())

        run_name = run.name or run.id
        if name:
            run_name = f"{name}_{run_name}"
        if run_name in used_names:
            run_name = f"{run_name}-{run.id}"
        used_names.add(run_name)

        metrics_list = []
        steps = []
        timestamps = []

        for row in run.scan_history():
            default_step = int(row.get("_step", 0))
            if row.get("_timestamp") is not None:
                timestamp = datetime.fromtimestamp(
                    float(row["_timestamp"]), tz=timezone.utc
                ).isoformat()
            else:
                timestamp = ""

            by_axis: dict[str | None, dict] = {}
            for key, value in row.items():
                if key in internal_keys or key in axis_keys or value is None:
                    continue
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    continue
                axis = _resolve_step_metric(key, run_step_metrics)
                by_axis.setdefault(axis, {})[key] = value

            for axis, metrics in by_axis.items():
                if axis is not None and isinstance(row.get(axis), (int, float)):
                    step = int(row[axis])
                else:
                    step = default_step
                metrics_list.append(metrics)
                steps.append(step)
                timestamps.append(timestamp)

        if not metrics_list:
            print(f"* Skipping wandb run '{run.id}': no numeric metric data found")
            continue

        config = {}
        for key, value in dict(run.config).items():
            try:
                json.dumps(value)
            except (TypeError, ValueError):
                continue
            config[key] = value

        SQLiteStorage.bulk_log(
            project=project,
            run=run_name,
            metrics_list=metrics_list,
            steps=steps,
            timestamps=timestamps,
            config=config or None,
        )

        total_imported += len(metrics_list)
        imported_runs.append(run_name)
        print(
            f"* Imported {len(metrics_list)} rows from wandb run '{run.id}' as run '{run_name}'"
        )

    if not imported_runs:
        raise ValueError("No valid wandb run data could be imported")

    print(f"* Total imported rows: {total_imported}")
    print(f"* Created runs: {', '.join(imported_runs)}")

    space_id, dataset_id, _ = utils.preprocess_space_and_dataset_ids(
        space_id, dataset_id
    )
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
