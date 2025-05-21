from typing import Any

import gradio as gr
import pandas as pd

try:
    from trackio.sqlite_storage import SQLiteStorage
    from trackio.utils import RESERVED_KEYS, TRACKIO_LOGO_PATH
except:  # noqa: E722
    from sqlite_storage import SQLiteStorage
    from utils import RESERVED_KEYS, TRACKIO_LOGO_PATH


def get_projects(request: gr.Request):
    storage = SQLiteStorage("", "", {})
    projects = storage.get_projects()
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
    )


def get_runs(project):
    if not project:
        return []
    storage = SQLiteStorage("", "", {})
    return storage.get_runs(project)


def load_run_data(project: str | None, run: str | None, smoothing: bool):
    if not project or not run:
        return None
    storage = SQLiteStorage("", "", {})
    metrics = storage.get_metrics(project, run)
    if not metrics:
        return None
    df = pd.DataFrame(metrics)
    if smoothing:
        numeric_cols = df.select_dtypes(include="number").columns
        numeric_cols = [c for c in numeric_cols if c not in RESERVED_KEYS]
        df[numeric_cols] = df[numeric_cols].ewm(alpha=0.1).mean()
    if "step" not in df.columns:
        df["step"] = range(len(df))
    return df


def update_runs(project, filter_text, user_interacted_with_runs=False):
    if project is None:
        runs = []
    else:
        runs = get_runs(project)
        if filter_text:
            runs = [r for r in runs if filter_text in r]
    if not user_interacted_with_runs:
        return gr.CheckboxGroup(choices=runs, value=runs)
    else:
        return gr.CheckboxGroup(choices=runs)


def filter_runs(project, filter_text):
    runs = get_runs(project)
    runs = [r for r in runs if filter_text in r]
    return gr.CheckboxGroup(choices=runs, value=runs)


def toggle_timer(cb_value):
    if cb_value:
        return gr.Timer(active=True)
    else:
        return gr.Timer(active=False)


def log(project: str, run: str, metrics: dict[str, Any]) -> None:
    storage = SQLiteStorage(project, run, {})
    storage.log(metrics)


def configure(request: gr.Request):
    if metrics := request.query_params.get("metrics"):
        return metrics.split(",")
    else:
        return []


with gr.Blocks(theme="citrus", title="Trackio Dashboard") as demo:
    with gr.Sidebar() as sidebar:
        gr.Markdown(
            f"<div style='display: flex; align-items: center; gap: 8px;'><img src='/gradio_api/file={TRACKIO_LOGO_PATH}' width='32' height='32'><span style='font-size: 2em; font-weight: bold;'>Trackio</span></div>"
        )
        project_dd = gr.Dropdown(label="Project")
        run_tb = gr.Textbox(label="Runs (99)", placeholder="Type to filter...")
        run_cb = gr.CheckboxGroup(label="Runs", choices=[], interactive=True)
    with gr.Sidebar(position="right", open=False) as settings_sidebar:
        gr.Markdown("### ⚙️ Settings")
        realtime_cb = gr.Checkbox(label="Refresh realtime", value=True)
        smoothing_cb = gr.Checkbox(label="Smoothing", value=True)

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
        outputs=run_cb,
        show_progress="hidden",
    )
    gr.on(
        [demo.load, project_dd.change],
        fn=update_runs,
        inputs=[project_dd, run_tb],
        outputs=run_cb,
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

    def update_x_lim(select_data: gr.SelectData):
        return select_data.index

    @gr.render(
        triggers=[
            demo.load,
            run_cb.change,
            timer.tick,
            smoothing_cb.change,
            x_lim.change,
        ],
        inputs=[project_dd, run_cb, smoothing_cb, metrics_subset, x_lim],
    )
    def update_dashboard(project, runs, smoothing, metrics_subset, x_lim_value):
        dfs = []
        for run in runs:
            df = load_run_data(project, run, smoothing)
            if df is not None:
                df["run"] = run
                dfs.append(df)
        if dfs:
            master_df = pd.concat(dfs, ignore_index=True)
        else:
            master_df = pd.DataFrame()
        numeric_cols = master_df.select_dtypes(include="number").columns
        numeric_cols = [c for c in numeric_cols if c not in RESERVED_KEYS]
        if metrics_subset:
            numeric_cols = [c for c in numeric_cols if c in metrics_subset]
        plots: list[gr.LinePlot] = []
        for col in range(len(numeric_cols) // 2):
            with gr.Row(key=f"row-{col}"):
                for i in range(2):
                    plot = gr.LinePlot(
                        master_df,
                        x="step",
                        y=numeric_cols[2 * col + i],
                        color="run" if "run" in master_df.columns else None,
                        title=numeric_cols[2 * col + i],
                        key=f"plot-{col}-{i}",
                        preserved_by_key=None,
                        x_lim=x_lim_value,
                        y_lim=[
                            min(master_df[numeric_cols[2 * col + i]]),
                            max(master_df[numeric_cols[2 * col + i]]),
                        ],
                        show_fullscreen_button=True,
                    )
                    plots.append(plot)

        for plot in plots:
            plot.select(update_x_lim, outputs=x_lim)
            plot.double_click(lambda: None, outputs=x_lim)


if __name__ == "__main__":
    demo.launch(allowed_paths=[TRACKIO_LOGO_PATH], show_api=False)
