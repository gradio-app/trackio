import os
from typing import Any

import gradio as gr
import huggingface_hub as hf
import pandas as pd

HfApi = hf.HfApi()

try:
    from trackio.sqlite_storage import SQLiteStorage
    from trackio.utils import RESERVED_KEYS, TRACKIO_LOGO_PATH
except:  # noqa: E722
    from sqlite_storage import SQLiteStorage
    from utils import RESERVED_KEYS, TRACKIO_LOGO_PATH

css = """
#run-cb .wrap {
    gap: 2px;
}
#run-cb .wrap label {
    line-height: 1;
    padding: 6px;
}
"""

COLOR_PALETTE = [
    "#3B82F6",
    "#EF4444",
    "#10B981",
    "#F59E0B",
    "#8B5CF6",
    "#EC4899",
    "#06B6D4",
    "#84CC16",
    "#F97316",
    "#6366F1",
]


def get_color_mapping(runs: list[str], smoothing: bool) -> dict[str, str]:
    """Generate color mapping for runs, with transparency for original data when smoothing is enabled."""
    color_map = {}

    for i, run in enumerate(runs):
        base_color = COLOR_PALETTE[i % len(COLOR_PALETTE)]

        if smoothing:
            color_map[f"{run}_smoothed"] = base_color
            color_map[f"{run}_original"] = base_color + "4D"
        else:
            color_map[run] = base_color

    return color_map


def get_projects(request: gr.Request):
    dataset_id = os.environ.get("TRACKIO_DATASET_ID")
    projects = SQLiteStorage.get_projects()
    if project := request.query_params.get("project"):
        interactive = False
    else:
        interactive = True
        project = projects[0] if projects else None
    return gr.Dropdown(
        label="Project",
        choices=projects,
        value=project,
        allow_custom_value=True,
        interactive=interactive,
        info=f"&#x21bb; Synced to <a href='https://huggingface.co/{dataset_id}' target='_blank'>{dataset_id}</a> every 5 min"
        if dataset_id
        else None,
    )


def get_runs(project) -> list[str]:
    if not project:
        return []
    return SQLiteStorage.get_runs(project)


def load_run_data(project: str | None, run: str | None, smoothing: bool):
    if not project or not run:
        return None
    metrics = SQLiteStorage.get_metrics(project, run)
    if not metrics:
        return None
    df = pd.DataFrame(metrics)

    if "step" not in df.columns:
        df["step"] = range(len(df))

    if smoothing:
        numeric_cols = df.select_dtypes(include="number").columns
        numeric_cols = [c for c in numeric_cols if c not in RESERVED_KEYS]

        df_original = df.copy()
        df_original["run"] = f"{run}_original"
        df_original["data_type"] = "original"

        df_smoothed = df.copy()
        window_size = max(3, min(10, len(df) // 10))  # Adaptive window size
        df_smoothed[numeric_cols] = (
            df_smoothed[numeric_cols]
            .rolling(window=window_size, center=True, min_periods=1)
            .mean()
        )
        df_smoothed["run"] = f"{run}_smoothed"
        df_smoothed["data_type"] = "smoothed"

        combined_df = pd.concat([df_original, df_smoothed], ignore_index=True)
        return combined_df
    else:
        df["run"] = run
        df["data_type"] = "original"
        return df


def update_runs(project, filter_text, user_interacted_with_runs=False):
    if project is None:
        runs = []
        num_runs = 0
    else:
        runs = get_runs(project)
        num_runs = len(runs)
        if filter_text:
            runs = [r for r in runs if filter_text in r]
    if not user_interacted_with_runs:
        return gr.CheckboxGroup(choices=runs, value=runs), gr.Textbox(
            label=f"Runs ({num_runs})"
        )
    else:
        return gr.CheckboxGroup(choices=runs), gr.Textbox(label=f"Runs ({num_runs})")


def filter_runs(project, filter_text):
    runs = get_runs(project)
    runs = [r for r in runs if filter_text in r]
    return gr.CheckboxGroup(choices=runs, value=runs)


def toggle_timer(cb_value):
    if cb_value:
        return gr.Timer(active=True)
    else:
        return gr.Timer(active=False)


def log(
    project: str,
    run: str,
    metrics: dict[str, Any],
    dataset_id: str | None,
    hf_token: str | None,
) -> None:
    if os.getenv("SYSTEM") == "spaces":  # if we are running in Spaces
        # check auth token passed in
        if hf_token is None:
            raise "Expected an hf_token to be provided when logging to a Space"
        who = HfApi.whoami(hf_token)
        access_token = who["auth"]["accessToken"]
        owner_name = os.getenv("SPACE_AUTHOR_NAME")
        repo_name = os.getenv("SPACE_REPO_NAME")
        # make sure the token user is either the author of the space,
        # or is a member of an org that is the author.
        orgs = [o["name"] for o in who["orgs"]]
        if owner_name != who["name"] and owner_name not in orgs:
            raise PermissionError(
                "Expected the provided hf_token to be the user owner of the space, or be a member of the org owner of the space"
            )
        # reject fine-grained tokens without specific repo access
        if access_token["role"] == "fineGrained":
            matched = False
            for item in access_token["fineGrained"]["scoped"]:
                if (
                    item["entity"]["type"] == "space"
                    and item["entity"]["name"] == f"{owner_name}/{repo_name}"
                    and "repo.write" in item["permissions"]
                ):
                    matched = True
                    break
                if (
                    item["entity"]["type"] == "user"
                    and item["entity"]["name"] == owner_name
                    and "repo.write" in item["permissions"]
                ):
                    matched = True
                    break
            if not matched:
                raise PermissionError(
                    "Expected the provided hf_token with fine grained permissions to provide write access to the space"
                )
        # reject read-only tokens
        elif access_token["role"] != "write":
            raise PermissionError(
                "Expected the provided hf_token to provide write permissions"
            )
    storage = SQLiteStorage(project, run, {}, dataset_id=dataset_id)
    storage.log(metrics)


def sort_metrics_by_prefix(metrics: list[str]) -> list[str]:
    """
    Sort metrics by grouping prefixes together.
    Metrics without prefixes come first, then grouped by prefix.

    Example:
    Input: ["train/loss", "loss", "train/acc", "val/loss"]
    Output: ["loss", "train/acc", "train/loss", "val/loss"]
    """
    no_prefix = []
    with_prefix = []

    for metric in metrics:
        if "/" in metric:
            with_prefix.append(metric)
        else:
            no_prefix.append(metric)

    no_prefix.sort()

    prefix_groups = {}
    for metric in with_prefix:
        prefix = metric.split("/")[0]
        if prefix not in prefix_groups:
            prefix_groups[prefix] = []
        prefix_groups[prefix].append(metric)

    sorted_with_prefix = []
    for prefix in sorted(prefix_groups.keys()):
        sorted_with_prefix.extend(sorted(prefix_groups[prefix]))

    return no_prefix + sorted_with_prefix


def configure(request: gr.Request):
    if metrics := request.query_params.get("metrics"):
        return metrics.split(",")
    else:
        return []


with gr.Blocks(theme="citrus", title="Trackio Dashboard", css=css) as demo:
    with gr.Sidebar() as sidebar:
        gr.Markdown(
            f"<div style='display: flex; align-items: center; gap: 8px;'><img src='/gradio_api/file={TRACKIO_LOGO_PATH}' width='32' height='32'><span style='font-size: 2em; font-weight: bold;'>Trackio</span></div>"
        )
        project_dd = gr.Dropdown(label="Project")
        run_tb = gr.Textbox(label="Runs", placeholder="Type to filter...")
        run_cb = gr.CheckboxGroup(
            label="Runs", choices=[], interactive=True, elem_id="run-cb"
        )
        gr.HTML("<hr>")
        realtime_cb = gr.Checkbox(label="Refresh metrics realtime", value=True)
        smoothing_cb = gr.Checkbox(label="Smooth metrics", value=True)

    timer = gr.Timer(value=1)
    metrics_subset = gr.State([])
    user_interacted_with_run_cb = gr.State(False)

    gr.on(
        [demo.load],
        fn=configure,
        outputs=metrics_subset,
    )
    gr.on(
        [demo.load],
        fn=get_projects,
        outputs=project_dd,
        show_progress="hidden",
    )
    gr.on(
        [timer.tick],
        fn=update_runs,
        inputs=[project_dd, run_tb, user_interacted_with_run_cb],
        outputs=[run_cb, run_tb],
        show_progress="hidden",
    )
    gr.on(
        [demo.load, project_dd.change],
        fn=update_runs,
        inputs=[project_dd, run_tb],
        outputs=[run_cb, run_tb],
        show_progress="hidden",
    )

    realtime_cb.change(
        fn=toggle_timer,
        inputs=realtime_cb,
        outputs=timer,
        api_name="toggle_timer",
    )
    run_cb.input(
        fn=lambda: True,
        outputs=user_interacted_with_run_cb,
    )
    run_tb.input(
        fn=filter_runs,
        inputs=[project_dd, run_tb],
        outputs=run_cb,
    )

    gr.api(
        fn=log,
        api_name="log",
    )

    x_lim = gr.State(None)
    last_steps = gr.State({})

    def update_x_lim(select_data: gr.SelectData):
        return select_data.index

    def update_last_steps(project, runs):
        """Update the last step from all runs to detect when new data is available."""
        if not project or not runs:
            return {}

        last_steps = {}
        for run in runs:
            metrics = SQLiteStorage.get_metrics(project, run)
            if metrics:
                df = pd.DataFrame(metrics)
                if "step" not in df.columns:
                    df["step"] = range(len(df))
                if not df.empty:
                    last_steps[run] = df["step"].max().item()
                else:
                    last_steps[run] = 0
            else:
                last_steps[run] = 0

        return last_steps

    timer.tick(
        fn=update_last_steps,
        inputs=[project_dd, run_cb],
        outputs=last_steps,
        show_progress="hidden",
    )

    @gr.render(
        triggers=[
            demo.load,
            run_cb.change,
            last_steps.change,
            smoothing_cb.change,
            x_lim.change,
        ],
        inputs=[project_dd, run_cb, smoothing_cb, metrics_subset, x_lim],
        show_progress="hidden",
    )
    def update_dashboard(project, runs, smoothing, metrics_subset, x_lim_value):
        dfs = []
        original_runs = runs.copy()

        for run in runs:
            df = load_run_data(project, run, smoothing)
            if df is not None:
                dfs.append(df)

        if dfs:
            master_df = pd.concat(dfs, ignore_index=True)
        else:
            master_df = pd.DataFrame()

        if master_df.empty:
            return

        numeric_cols = master_df.select_dtypes(include="number").columns
        numeric_cols = [
            c for c in numeric_cols if c not in RESERVED_KEYS and c != "step"
        ]
        if metrics_subset:
            numeric_cols = [c for c in numeric_cols if c in metrics_subset]

        numeric_cols = sort_metrics_by_prefix(list(numeric_cols))
        color_map = get_color_mapping(original_runs, smoothing)

        with gr.Row(key="row"):
            for metric_idx, metric_name in enumerate(numeric_cols):
                metric_df = master_df.dropna(subset=[metric_name])
                if not metric_df.empty:
                    plot = gr.LinePlot(
                        metric_df,
                        x="step",
                        y=metric_name,
                        color="run" if "run" in metric_df.columns else None,
                        color_map=color_map,
                        title=metric_name,
                        key=f"plot-{metric_idx}",
                        preserved_by_key=None,
                        x_lim=x_lim_value,
                        y_lim=[
                            metric_df[metric_name].min(),
                            metric_df[metric_name].max(),
                        ],
                        show_fullscreen_button=True,
                        min_width=400,
                    )
                plot.select(update_x_lim, outputs=x_lim, key=f"select-{metric_idx}")
                plot.double_click(
                    lambda: None, outputs=x_lim, key=f"double-{metric_idx}"
                )


if __name__ == "__main__":
    demo.launch(allowed_paths=[TRACKIO_LOGO_PATH], show_api=False)
