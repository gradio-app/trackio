"""The System Metrics page for the Trackio UI (GPU metrics, etc.)."""

import re

import gradio as gr
import pandas as pd

import trackio.utils as utils
from trackio.sqlite_storage import SQLiteStorage
from trackio.ui import fns
from trackio.ui.components.colored_checkbox import ColoredCheckboxGroup
from trackio.ui.helpers.run_selection import RunSelection

GPU_METRIC_PATTERN = re.compile(r"^((?:rank\d+/)?gpu)/(\d+)/(.+)$")


def melt_gpu_metrics(
    df: pd.DataFrame, metric_cols: list[str]
) -> tuple[pd.DataFrame, dict[str, list[str]]]:
    """
    Transform GPU metrics to combine all GPUs onto single plots.
    
    Returns:
        - Modified dataframe with melted GPU metrics
        - Dict mapping metric type (e.g. "utilization") to list of original column names
    """
    gpu_groups: dict[str, list[str]] = {}
    non_gpu_cols = []
    
    for col in metric_cols:
        match = GPU_METRIC_PATTERN.match(col)
        if match:
            prefix, gpu_id, metric_type = match.groups()
            key = f"{prefix}/{metric_type}"
            if key not in gpu_groups:
                gpu_groups[key] = []
            gpu_groups[key].append((col, gpu_id))
        else:
            non_gpu_cols.append(col)
    
    if not gpu_groups:
        return df, {}
    
    melted_dfs = []
    base_cols = ["time", "run"] if "run" in df.columns else ["time"]
    
    for metric_key, cols_and_ids in gpu_groups.items():
        for original_col, gpu_id in cols_and_ids:
            if original_col not in df.columns:
                continue
            subset = df[base_cols + [original_col]].copy()
            subset = subset.dropna(subset=[original_col])
            if subset.empty:
                continue
            subset["gpu_id"] = gpu_id
            subset = subset.rename(columns={original_col: metric_key})
            melted_dfs.append(subset)
    
    if melted_dfs:
        melted_df = pd.concat(melted_dfs, ignore_index=True)
        non_gpu_df = df[base_cols + non_gpu_cols].copy() if non_gpu_cols else None
        return melted_df, {k: [c for c, _ in v] for k, v in gpu_groups.items()}
    
    return df, {}


def refresh_runs(
    project: str | None,
    filter_text: str | None,
    selection: RunSelection,
):
    if project is None:
        runs: list[str] = []
    else:
        runs = fns.get_runs(project)
        if filter_text:
            runs = [r for r in runs if filter_text in r]

    did_change = selection.update_choices(runs)
    return (
        fns.run_checkbox_update(selection) if did_change else gr.skip(),
        gr.Textbox(label=f"Runs ({len(runs)})"),
        selection,
    )


def load_system_data(
    project: str | None,
    run: str | None,
) -> pd.DataFrame | None:
    if not project or not run:
        return None

    logs = SQLiteStorage.get_system_logs(project, run)
    if not logs:
        return None

    df = pd.DataFrame(logs)

    if "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        first_timestamp = df["timestamp"].min()
        df["time"] = (df["timestamp"] - first_timestamp).dt.total_seconds()

    df["run"] = run
    return df


with gr.Blocks() as system_page:
    with gr.Sidebar() as sidebar:
        logo = fns.create_logo()
        project_dd = fns.create_project_dropdown()

        with gr.Group():
            run_tb = gr.Textbox(label="Runs", placeholder="Type to filter...")
        run_cb = ColoredCheckboxGroup(choices=[], colors=[], label="Runs")

        gr.HTML("<hr>")
        realtime_cb = gr.Checkbox(label="Refresh metrics realtime", value=True)
        smoothing_slider = gr.Slider(
            label="Smoothing Factor",
            minimum=0,
            maximum=20,
            value=0,
            step=1,
            info="0 = no smoothing",
        )

    navbar = fns.create_navbar()
    timer = gr.Timer(value=1)
    run_selection_state = gr.State(RunSelection())
    x_lim = gr.State(None)
    last_system_update = gr.State({})

    def toggle_timer(cb_value):
        if cb_value:
            return gr.Timer(active=True)
        else:
            return gr.Timer(active=False)

    def update_x_lim(select_data: gr.SelectData):
        return select_data.index

    def check_system_metrics_update(project: str | None, runs: list[str]) -> dict:
        if not project or not runs:
            return {}
        result = {}
        for run in runs:
            logs = SQLiteStorage.get_system_logs(project, run)
            result[run] = len(logs) if logs else 0
        return result

    @gr.render(
        triggers=[
            system_page.load,
            run_cb.change,
            last_system_update.change,
            smoothing_slider.change,
            x_lim.change,
        ],
        inputs=[
            project_dd,
            run_cb,
            smoothing_slider,
            x_lim,
            run_selection_state,
        ],
        show_progress="hidden",
        queue=False,
    )
    def update_system_dashboard(
        project,
        runs,
        smoothing_granularity,
        x_lim_value,
        selection,
    ):
        dfs = []
        original_runs = runs.copy() if runs else []

        for run in runs:
            df = load_system_data(project, run)
            if df is not None:
                dfs.append(df)

        if not dfs:
            if not SQLiteStorage.has_system_metrics(project) if project else True:
                gr.Markdown(
                    """
## No System Metrics Available

System metrics (GPU) will appear here once logged. To enable automatic GPU logging:

```python
import trackio

# GPU logging is auto-enabled when nvidia-ml-py is installed and a GPU is detected
run = trackio.init(project="my-project")

# Or explicitly enable it:
run = trackio.init(project="my-project", auto_log_gpu=True)

# You can also manually log GPU metrics:
trackio.log_gpu()
```
"""
                )
            else:
                gr.Markdown("*Select runs to view system metrics*")
            return

        master_df = pd.concat(dfs, ignore_index=True)

        if master_df.empty:
            gr.Markdown("*No system metrics found for selected runs*")
            return

        x_column = "time"

        numeric_cols = master_df.select_dtypes(include="number").columns
        numeric_cols = [c for c in numeric_cols if c not in ["time", "timestamp"]]

        melted_df, gpu_metric_groups = melt_gpu_metrics(master_df, list(numeric_cols))
        non_gpu_cols = [c for c in numeric_cols if not GPU_METRIC_PATTERN.match(c)]

        if smoothing_granularity > 0:
            window_size = max(3, min(smoothing_granularity, len(master_df)))
            for col in non_gpu_cols:
                if col in master_df.columns:
                    master_df[col] = master_df.groupby("run")[col].transform(
                        lambda x: x.rolling(
                            window=window_size, center=True, min_periods=1
                        ).mean()
                    )

        all_runs = selection.choices if selection else original_runs
        color_map = utils.get_color_mapping(all_runs, False)
        gpu_ids = sorted(melted_df["gpu_id"].unique()) if "gpu_id" in melted_df.columns else []
        gpu_color_map = {gid: utils.get_color_palette()[i % len(utils.get_color_palette())] for i, gid in enumerate(gpu_ids)}

        metric_idx = 0

        if gpu_metric_groups:
            gpu_plot_count = len(gpu_metric_groups)
            with gr.Accordion(
                label=f"gpu ({gpu_plot_count})",
                open=True,
                key="sys-accordion-gpu-combined",
                preserved_by_key=["value", "open"],
            ):
                with gr.Draggable(key="sys-row-gpu-combined", orientation="row"):
                    for metric_key in sorted(gpu_metric_groups.keys()):
                        metric_df = melted_df[melted_df[metric_key].notna()].copy() if metric_key in melted_df.columns else pd.DataFrame()
                        if metric_df.empty:
                            continue
                        color = "gpu_id"
                        downsampled_df, updated_x_lim = utils.downsample(
                            metric_df, x_column, metric_key, color, x_lim_value
                        )
                        metric_display = metric_key.split("/")[-1]
                        plot = gr.LinePlot(
                            downsampled_df,
                            x=x_column,
                            y=metric_key,
                            x_title="Time (seconds)",
                            y_title=metric_display,
                            color=color,
                            color_map=gpu_color_map,
                            title=metric_key,
                            key=f"sys-plot-{metric_idx}",
                            preserved_by_key=None,
                            buttons=["fullscreen", "export"],
                            x_lim=updated_x_lim,
                            min_width=400,
                        )
                        plot.select(update_x_lim, outputs=x_lim, key=f"sys-select-{metric_idx}")
                        plot.double_click(lambda: None, outputs=x_lim, key=f"sys-double-{metric_idx}")
                        metric_idx += 1

        if non_gpu_cols:
            ordered_groups, nested_metric_groups = utils.order_metrics_by_plot_preference(non_gpu_cols)
            for group_name in ordered_groups:
                group_data = nested_metric_groups[group_name]
                total_plot_count = sum(
                    1 for m in group_data["direct_metrics"] if not master_df.dropna(subset=[m]).empty
                ) + sum(
                    sum(1 for m in metrics if not master_df.dropna(subset=[m]).empty)
                    for metrics in group_data["subgroups"].values()
                )
                if total_plot_count == 0:
                    continue
                group_label = f"{group_name} ({total_plot_count})"

                with gr.Accordion(
                    label=group_label, open=True,
                    key=f"sys-accordion-{group_name}", preserved_by_key=["value", "open"],
                ):
                    if group_data["direct_metrics"]:
                        with gr.Draggable(key=f"sys-row-{group_name}-direct", orientation="row"):
                            for metric_name in group_data["direct_metrics"]:
                                metric_df = master_df.dropna(subset=[metric_name])
                                if metric_df.empty:
                                    continue
                                color = "run" if "run" in metric_df.columns else None
                                downsampled_df, updated_x_lim = utils.downsample(
                                    metric_df, x_column, metric_name, color, x_lim_value
                                )
                                plot = gr.LinePlot(
                                    downsampled_df, x=x_column, y=metric_name,
                                    x_title="Time (seconds)", y_title=metric_name.split("/")[-1],
                                    color=color, color_map=color_map, colors_in_legend=original_runs,
                                    title=metric_name, key=f"sys-plot-{metric_idx}",
                                    preserved_by_key=None, buttons=["fullscreen", "export"],
                                    x_lim=updated_x_lim, min_width=400,
                                )
                                plot.select(update_x_lim, outputs=x_lim, key=f"sys-select-{metric_idx}")
                                plot.double_click(lambda: None, outputs=x_lim, key=f"sys-double-{metric_idx}")
                                metric_idx += 1

                    for subgroup_name in sorted(group_data["subgroups"].keys()):
                        subgroup_metrics = group_data["subgroups"][subgroup_name]
                        subgroup_plot_count = sum(
                            1 for m in subgroup_metrics if not master_df.dropna(subset=[m]).empty
                        )
                        if subgroup_plot_count == 0:
                            continue
                        with gr.Accordion(
                            label=f"{subgroup_name} ({subgroup_plot_count})", open=True,
                            key=f"sys-accordion-{group_name}-{subgroup_name}",
                            preserved_by_key=["value", "open"],
                        ):
                            with gr.Draggable(key=f"sys-row-{group_name}-{subgroup_name}", orientation="row"):
                                for metric_name in subgroup_metrics:
                                    metric_df = master_df.dropna(subset=[metric_name])
                                    if metric_df.empty:
                                        continue
                                    color = "run" if "run" in metric_df.columns else None
                                    downsampled_df, updated_x_lim = utils.downsample(
                                        metric_df, x_column, metric_name, color, x_lim_value
                                    )
                                    plot = gr.LinePlot(
                                        downsampled_df, x=x_column, y=metric_name,
                                        x_title="Time (seconds)", y_title=metric_name.split("/")[-1],
                                        color=color, color_map=color_map, colors_in_legend=original_runs,
                                        title=metric_name, key=f"sys-plot-{metric_idx}",
                                        preserved_by_key=None, buttons=["fullscreen", "export"],
                                        x_lim=updated_x_lim, min_width=400,
                                    )
                                    plot.select(update_x_lim, outputs=x_lim, key=f"sys-select-{metric_idx}")
                                    plot.double_click(lambda: None, outputs=x_lim, key=f"sys-double-{metric_idx}")
                                    metric_idx += 1

    gr.on(
        [timer.tick],
        fn=lambda: gr.Dropdown(info=fns.get_project_info()),
        outputs=[project_dd],
        show_progress="hidden",
        api_visibility="private",
    )

    gr.on(
        [timer.tick],
        fn=refresh_runs,
        inputs=[project_dd, run_tb, run_selection_state],
        outputs=[run_cb, run_tb, run_selection_state],
        show_progress="hidden",
        api_visibility="private",
    )

    gr.on(
        [timer.tick],
        fn=check_system_metrics_update,
        inputs=[project_dd, run_cb],
        outputs=last_system_update,
        show_progress="hidden",
        api_visibility="private",
    )

    gr.on(
        [system_page.load],
        fn=fns.get_projects,
        outputs=project_dd,
        show_progress="hidden",
        queue=False,
        api_visibility="private",
    ).then(
        fns.update_navbar_value,
        inputs=[project_dd],
        outputs=[navbar],
        show_progress="hidden",
        api_visibility="private",
        queue=False,
    )

    gr.on(
        [system_page.load, project_dd.change],
        fn=refresh_runs,
        inputs=[project_dd, run_tb, run_selection_state],
        outputs=[run_cb, run_tb, run_selection_state],
        show_progress="hidden",
        queue=False,
        api_visibility="private",
    ).then(
        fns.update_navbar_value,
        inputs=[project_dd],
        outputs=[navbar],
        show_progress="hidden",
        api_visibility="private",
        queue=False,
    )

    realtime_cb.change(
        fn=toggle_timer,
        inputs=realtime_cb,
        outputs=timer,
        api_visibility="private",
        queue=False,
    )

    run_cb.input(
        fn=fns.handle_run_checkbox_change,
        inputs=[run_cb, run_selection_state],
        outputs=run_selection_state,
        api_visibility="private",
        queue=False,
    )

    run_tb.input(
        fn=refresh_runs,
        inputs=[project_dd, run_tb, run_selection_state],
        outputs=[run_cb, run_tb, run_selection_state],
        api_visibility="private",
        queue=False,
        show_progress="hidden",
    )
