"""The main page for the Trackio UI."""

import os
import re
import secrets
import shutil
from dataclasses import dataclass
from typing import Any

import gradio as gr
import numpy as np
import pandas as pd

try:
    import trackio.utils as utils
    from trackio.media import (
        TrackioAudio,
        TrackioImage,
        TrackioVideo,
        get_project_media_path,
    )
    from trackio.sqlite_storage import SQLiteStorage
    from trackio.typehints import LogEntry, UploadEntry
    from trackio.ui import fns
    from trackio.ui.components.colored_checkbox import ColoredCheckboxGroup
    from trackio.ui.files import files_page
    from trackio.ui.helpers.run_selection import RunSelection
    from trackio.ui.media_page import media_page
    from trackio.ui.run_detail import run_detail_page
    from trackio.ui.runs import run_page
except ImportError:
    import utils
    from media import (
        TrackioAudio,
        TrackioImage,
        TrackioVideo,
        get_project_media_path,
    )
    from sqlite_storage import SQLiteStorage
    from typehints import LogEntry, UploadEntry
    from ui import fns
    from ui.components.colored_checkbox import ColoredCheckboxGroup
    from ui.files import files_page
    from ui.helpers.run_selection import RunSelection
    from ui.media_page import media_page
    from ui.run_detail import run_detail_page
    from ui.runs import run_page


INSTRUCTIONS_SPACES = """
## Start logging with Trackio 🤗

To start logging to this Trackio dashboard, first make sure you have the Trackio library installed. You can do this by running:

```bash
pip install trackio
```

Then, start logging to this Trackio dashboard by passing in the `space_id` to `trackio.init()`:

```python
import trackio
trackio.init(project="my-project", space_id="{}")
```

Then call `trackio.log()` to log metrics.

```python
for i in range(10):
    trackio.log({{"loss": 1/(i+1)}})
```

Finally, call `trackio.finish()` to finish the run.

```python
trackio.finish()
```
"""

INSTRUCTIONS_LOCAL = """
## Start logging with Trackio 🤗
 
You can create a new project by calling `trackio.init()`:

```python
import trackio
trackio.init(project="my-project")
 ```

Then call `trackio.log()` to log metrics.

```python
for i in range(10):
    trackio.log({"loss": 1/(i+1)})
```

Finally, call `trackio.finish()` to finish the run.

```python
trackio.finish()
```

Read the [Trackio documentation](https://huggingface.co/docs/trackio/en/index) for more examples.
"""


def get_runs(project) -> list[str]:
    if not project:
        return []
    return SQLiteStorage.get_runs(project)


def upload_db_to_space(
    project: str, uploaded_db: gr.FileData, hf_token: str | None
) -> None:
    """
    Uploads the database of a local Trackio project to a Hugging Face Space.
    """
    fns.check_hf_token_has_write_access(hf_token)
    db_project_path = SQLiteStorage.get_project_db_path(project)
    os.makedirs(os.path.dirname(db_project_path), exist_ok=True)
    shutil.copy(uploaded_db["path"], db_project_path)


def get_available_metrics(project: str, runs: list[str]) -> list[str]:
    """Get all available metrics across all runs for x-axis selection."""
    if not project or not runs:
        return ["step", "time"]

    all_metrics = set()
    for run in runs:
        metrics = SQLiteStorage.get_logs(project, run)
        if metrics:
            df = pd.DataFrame(metrics)
            numeric_cols = df.select_dtypes(include="number").columns
            numeric_cols = [c for c in numeric_cols if c not in utils.RESERVED_KEYS]
            all_metrics.update(numeric_cols)

    all_metrics.add("step")
    all_metrics.add("time")

    sorted_metrics = utils.sort_metrics_by_prefix(list(all_metrics))

    result = ["step", "time"]
    for metric in sorted_metrics:
        if metric not in result:
            result.append(metric)

    return result


@dataclass
class MediaData:
    caption: str | None
    file_path: str
    type: str


def extract_media(logs: list[dict]) -> dict[str, list[MediaData]]:
    media_by_key: dict[str, list[MediaData]] = {}
    logs = sorted(logs, key=lambda x: x.get("step", 0))
    for log in logs:
        for key, value in log.items():
            if isinstance(value, dict):
                type = value.get("_type")
                if (
                    type == TrackioImage.TYPE
                    or type == TrackioVideo.TYPE
                    or type == TrackioAudio.TYPE
                ):
                    if key not in media_by_key:
                        media_by_key[key] = []
                    try:
                        media_data = MediaData(
                            file_path=utils.MEDIA_DIR / value.get("file_path"),
                            type=type,
                            caption=value.get("caption"),
                        )
                        media_by_key[key].append(media_data)
                    except Exception as e:
                        print(f"Media currently unavailable: {key}: {e}")
    return media_by_key


def load_run_data(
    project: str | None,
    run: str | None,
    smoothing_granularity: int = 0,
    x_axis: str = "step",
    log_scale_x: bool = False,
    log_scale_y: bool = False,
) -> tuple[pd.DataFrame, dict]:
    if not project or not run:
        return None, None

    logs = SQLiteStorage.get_logs(project, run)
    if not logs:
        return None, None

    media = extract_media(logs)
    df = pd.DataFrame(logs)

    if "step" not in df.columns:
        df["step"] = range(len(df))

    if x_axis == "time" and "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        first_timestamp = df["timestamp"].min()
        df["time"] = (df["timestamp"] - first_timestamp).dt.total_seconds()
        x_column = "time"
    elif x_axis == "step":
        x_column = "step"
    else:
        x_column = x_axis

    if log_scale_x and x_column in df.columns:
        x_vals = df[x_column]
        if (x_vals <= 0).any():
            df[x_column] = np.log10(np.maximum(x_vals, 0) + 1)
        else:
            df[x_column] = np.log10(x_vals)

    if log_scale_y:
        numeric_cols = df.select_dtypes(include="number").columns
        y_cols = [
            c for c in numeric_cols if c not in utils.RESERVED_KEYS and c != x_column
        ]
        for y_col in y_cols:
            if y_col in df.columns:
                y_vals = df[y_col]
                if (y_vals <= 0).any():
                    df[y_col] = np.log10(np.maximum(y_vals, 0) + 1)
                else:
                    df[y_col] = np.log10(y_vals)

    if smoothing_granularity > 0:
        numeric_cols = df.select_dtypes(include="number").columns
        numeric_cols = [c for c in numeric_cols if c not in utils.RESERVED_KEYS]

        df_original = df.copy()
        df_original["run"] = run
        df_original["data_type"] = "original"

        df_smoothed = df.copy()
        window_size = max(3, min(smoothing_granularity, len(df)))
        df_smoothed[numeric_cols] = (
            df_smoothed[numeric_cols]
            .rolling(window=window_size, center=True, min_periods=1)
            .mean()
        )
        df_smoothed["run"] = f"{run}_smoothed"
        df_smoothed["data_type"] = "smoothed"

        combined_df = pd.concat([df_original, df_smoothed], ignore_index=True)
        combined_df["x_axis"] = x_column
        return combined_df, media
    else:
        df["run"] = run
        df["data_type"] = "original"
        df["x_axis"] = x_column
        return df, media


def refresh_runs(
    project: str | None,
    filter_text: str | None,
    selection: RunSelection,
    selected_runs_from_url: list[str] | None = None,
):
    if project is None:
        runs: list[str] = []
    else:
        runs = get_runs(project)
        if filter_text:
            runs = [r for r in runs if filter_text in r]

    preferred = None
    if selected_runs_from_url:
        preferred = [r for r in runs if r in selected_runs_from_url]

    did_change = selection.update_choices(runs, preferred)
    return (
        fns.run_checkbox_update(selection) if did_change else gr.skip(),
        gr.Textbox(label=f"Runs ({len(runs)})"),
        selection,
    )


def generate_embed(project: str, metrics: str, selection: RunSelection) -> str:
    return utils.generate_embed_code(project, metrics, selection.selected)


def update_x_axis_choices(project, selection):
    """Update x-axis dropdown choices based on available metrics."""
    runs = selection.selected
    available_metrics = get_available_metrics(project, runs)
    return gr.Dropdown(
        label="X-axis",
        choices=available_metrics,
        value="step",
    )


def toggle_timer(cb_value):
    if cb_value:
        return gr.Timer(active=True)
    else:
        return gr.Timer(active=False)


def bulk_upload_media(uploads: list[UploadEntry], hf_token: str | None) -> None:
    """
    Uploads media files to a Trackio dashboard. Each entry in the list is a tuple of the project, run, and media file to be uploaded.
    Also handles uplaoding project-level files to the project's files directory (if the run and step are not provided).
    """
    fns.check_hf_token_has_write_access(hf_token)
    for upload in uploads:
        media_path = get_project_media_path(
            project=upload["project"],
            run=upload["run"],
            step=upload["step"],
            relative_path=upload["relative_path"],
        )
        shutil.copy(upload["uploaded_file"]["path"], media_path)


def log(
    project: str,
    run: str,
    metrics: dict[str, Any],
    step: int | None,
    hf_token: str | None,
) -> None:
    """
    Note: this method is not used in the latest versions of Trackio (replaced by bulk_log) but
    is kept for backwards compatibility for users who are connecting to a newer version of
    a Trackio Spaces dashboard with an older version of Trackio installed locally.
    """
    fns.check_hf_token_has_write_access(hf_token)
    SQLiteStorage.log(project=project, run=run, metrics=metrics, step=step)


def bulk_log(
    logs: list[LogEntry],
    hf_token: str | None,
) -> None:
    """
    Logs a list of metrics to a Trackio dashboard. Each entry in the list is a dictionary of the project, run, a dictionary of metrics, and optionally, a step and config.
    """
    fns.check_hf_token_has_write_access(hf_token)

    logs_by_run = {}
    for log_entry in logs:
        key = (log_entry["project"], log_entry["run"])
        if key not in logs_by_run:
            logs_by_run[key] = {"metrics": [], "steps": [], "config": None}
        logs_by_run[key]["metrics"].append(log_entry["metrics"])
        logs_by_run[key]["steps"].append(log_entry.get("step"))
        if log_entry.get("config") and logs_by_run[key]["config"] is None:
            logs_by_run[key]["config"] = log_entry["config"]

    for (project, run), data in logs_by_run.items():
        SQLiteStorage.bulk_log(
            project=project,
            run=run,
            metrics_list=data["metrics"],
            steps=data["steps"],
            config=data["config"],
        )


def get_metric_values(
    project: str,
    run: str,
    metric_name: str,
) -> list[dict]:
    """
    Get all values for a specific metric in a project/run.
    Returns a list of dictionaries with timestamp, step, and value.
    """
    return SQLiteStorage.get_metric_values(project, run, metric_name)


def get_runs_for_project(
    project: str,
) -> list[str]:
    """
    Get all runs for a given project.
    Returns a list of run names.
    """
    return SQLiteStorage.get_runs(project)


def get_metrics_for_run(
    project: str,
    run: str,
) -> list[str]:
    """
    Get all metrics for a given project and run.
    Returns a list of metric names.
    """
    return SQLiteStorage.get_all_metrics_for_run(project, run)


def filter_metrics_by_regex(metrics: list[str], filter_pattern: str) -> list[str]:
    """
    Filter metrics using regex pattern.

    Args:
        metrics: List of metric names to filter
        filter_pattern: Regex pattern to match against metric names

    Returns:
        List of metric names that match the pattern
    """
    if not filter_pattern.strip():
        return metrics

    try:
        pattern = re.compile(filter_pattern, re.IGNORECASE)
        return [metric for metric in metrics if pattern.search(metric)]
    except re.error:
        return [
            metric for metric in metrics if filter_pattern.lower() in metric.lower()
        ]


def get_all_projects() -> list[str]:
    """
    Get all project names.
    Returns a list of project names.
    """
    return SQLiteStorage.get_projects()


def get_project_summary(project: str) -> dict:
    """
    Get a summary of a project including number of runs and recent activity.

    Args:
        project: Project name

    Returns:
        Dictionary with project summary information
    """
    runs = SQLiteStorage.get_runs(project)
    if not runs:
        return {"project": project, "num_runs": 0, "runs": [], "last_activity": None}

    last_steps = SQLiteStorage.get_max_steps_for_runs(project)

    return {
        "project": project,
        "num_runs": len(runs),
        "runs": runs,
        "last_activity": max(last_steps.values()) if last_steps else None,
    }


def get_run_summary(project: str, run: str) -> dict:
    """
    Get a summary of a specific run including metrics and configuration.

    Args:
        project: Project name
        run: Run name

    Returns:
        Dictionary with run summary information
    """
    logs = SQLiteStorage.get_logs(project, run)
    metrics = SQLiteStorage.get_all_metrics_for_run(project, run)

    if not logs:
        return {
            "project": project,
            "run": run,
            "num_logs": 0,
            "metrics": [],
            "config": None,
            "last_step": None,
        }

    df = pd.DataFrame(logs)
    config = logs[0].get("config") if logs else None
    last_step = df["step"].max() if "step" in df.columns else len(logs) - 1

    return {
        "project": project,
        "run": run,
        "num_logs": len(logs),
        "metrics": metrics,
        "config": config,
        "last_step": last_step,
    }


def configure(request: gr.Request):
    sidebar_param = request.query_params.get("sidebar")
    match sidebar_param:
        case "collapsed":
            sidebar = gr.Sidebar(open=False, visible=True)
        case "hidden":
            sidebar = gr.Sidebar(open=False, visible=False)
        case _:
            sidebar = gr.Sidebar(open=True, visible=True)

    metrics_param = request.query_params.get("metrics", "")
    runs_param = request.query_params.get("runs", "")
    selected_runs = runs_param.split(",") if runs_param else []
    navbar_param = request.query_params.get("navbar")
    x_min_param = request.query_params.get("xmin")
    x_max_param = request.query_params.get("xmax")
    x_min = float(x_min_param) if x_min_param is not None else None
    x_max = float(x_max_param) if x_max_param is not None else None
    smoothing_param = request.query_params.get("smoothing")
    smoothing_value = int(smoothing_param) if smoothing_param is not None else 10

    match navbar_param:
        case "hidden":
            navbar = gr.Navbar(visible=False)
        case _:
            navbar = gr.Navbar(visible=True)

    return (
        [],
        sidebar,
        metrics_param,
        selected_runs,
        navbar,
        [x_min, x_max],
        smoothing_value,
    )


CSS = """
.logo-light { display: block; } 
.logo-dark { display: none; }
.dark .logo-light { display: none; }
.dark .logo-dark { display: block; }
.dark .caption-label { color: white; }

.info-container {
    position: relative;
    display: inline;
}
.info-checkbox {
    position: absolute;
    opacity: 0;
    pointer-events: none;
}
.info-icon {
    border-bottom: 1px dotted;
    cursor: pointer;
    user-select: none;
    color: var(--color-accent);
}
.info-expandable {
    display: none;
    opacity: 0;
    transition: opacity 0.2s ease-in-out;
}
.info-checkbox:checked ~ .info-expandable {
    display: inline;
    opacity: 1;
}
.info-icon:hover { opacity: 0.8; }
.accent-link { font-weight: bold; }

.media-gallery .fixed-height { min-height: 275px; }
.media-group, .media-group > div { background: none; }
.media-group .tabs { padding: 0.5em; }
.media-tab { max-height: 500px; overflow-y: scroll; }
.media-audio-accordion > button { 
    border-bottom-width: 1px;
    padding-bottom: 3px;
}
.media-audio-item {
    border-width: 1px !important;
    border-radius: 0.5em;
}
.media-audio-row {
    gap: 0.25em;
    margin-bottom: 0.25em;
}

.tab-like-container {
    visibility: hidden;
}
"""

HEAD = """
<script>
function setCookie(name, value, days) {
    var expires = "";
    if (days) {
        var date = new Date();
        date.setTime(date.getTime() + (days * 24 * 60 * 60 * 1000));
        expires = "; expires=" + date.toUTCString();
    }
    document.cookie = name + "=" + (value || "") + expires + "; path=/; SameSite=Lax";
}

function getCookie(name) {
    var nameEQ = name + "=";
    var ca = document.cookie.split(';');
    for(var i=0;i < ca.length;i++) {
        var c = ca[i];
        while (c.charAt(0)==' ') c = c.substring(1,c.length);
        if (c.indexOf(nameEQ) == 0) return c.substring(nameEQ.length,c.length);
    }
    return null;
}

(function() {
    const urlParams = new URLSearchParams(window.location.search);
    const writeToken = urlParams.get('write_token');
    const footerParam = urlParams.get('footer');
    
    if (writeToken) {
        setCookie('trackio_write_token', writeToken, 7);
                
        // Only remove write_token from URL if not in iframe
        // In iframes, keep it in URL as cookies may be blocked
        const inIframe = window.self !== window.top;
        if (!inIframe) {
            urlParams.delete('write_token');
            const newUrl = window.location.pathname + 
                (urlParams.toString() ? '?' + urlParams.toString() : '') + 
                window.location.hash;
            window.history.replaceState({}, document.title, newUrl);
        }
    }
    
    if (footerParam === 'false') {
        const style = document.createElement('style');
        style.textContent = 'footer { display: none !important; }';
        document.head.appendChild(style);
    }
})();
</script>
"""


gr.set_static_paths(paths=[utils.MEDIA_DIR])

with gr.Blocks(title="Trackio Dashboard") as demo:
    with gr.Sidebar(open=False) as sidebar:
        logo_urls = utils.get_logo_urls()
        logo = gr.Markdown(
            f"""
                <img src='{logo_urls["light"]}' width='80%' class='logo-light'>
                <img src='{logo_urls["dark"]}' width='80%' class='logo-dark'>            
            """
        )
        project_dd = gr.Dropdown(label="Project", allow_custom_value=True)

        embed_code = gr.Code(
            label="Embed this view",
            max_lines=2,
            lines=2,
            language="html",
            visible=bool(os.environ.get("SPACE_HOST")),
        )
        with gr.Group():
            run_tb = gr.Textbox(label="Runs", placeholder="Type to filter...")
            run_group_by_dd = gr.Dropdown(label="Group by...", choices=[], value=None)
            grouped_runs_panel = gr.Group(visible=False)
        run_cb = ColoredCheckboxGroup(choices=[], colors=[], label="Runs")

        gr.HTML("<hr>")
        realtime_cb = gr.Checkbox(label="Refresh metrics realtime", value=True)
        smoothing_slider = gr.Slider(
            label="Smoothing Factor",
            minimum=0,
            maximum=20,
            value=10,
            step=1,
            info="0 = no smoothing",
        )
        x_axis_dd = gr.Dropdown(
            label="X-axis",
            choices=["step", "time"],
            value="step",
        )
        log_scale_x_cb = gr.Checkbox(label="Log scale X-axis", value=False)
        log_scale_y_cb = gr.Checkbox(label="Log scale Y-axis", value=False)
        metric_filter_tb = gr.Textbox(
            label="Metric Filter (regex)",
            placeholder="e.g., loss|ndcg@10|gpu",
            value="",
            info="Filter metrics using regex patterns. Leave empty to show all metrics.",
        )

    navbar = gr.Navbar(
        value=[
            ("Metrics", ""),
            ("Media & Tables", "/media"),
            ("Runs", "/runs"),
            ("Files", "/files"),
        ],
        main_page_name=False,
    )
    timer = gr.Timer(value=1)
    metrics_subset = gr.State([])
    selected_runs_from_url = gr.State([])
    run_selection_state = gr.State(RunSelection())
    x_lim = gr.State(None)

    gr.on(
        [demo.load],
        fn=configure,
        outputs=[
            metrics_subset,
            sidebar,
            metric_filter_tb,
            selected_runs_from_url,
            navbar,
            x_lim,
            smoothing_slider,
        ],
        queue=False,
        api_visibility="private",
    )
    gr.on(
        [demo.load],
        fn=fns.get_projects,
        outputs=project_dd,
        show_progress="hidden",
        queue=False,
        api_visibility="private",
    )
    gr.on(
        [timer.tick],
        fn=refresh_runs,
        inputs=[project_dd, run_tb, run_selection_state, selected_runs_from_url],
        outputs=[run_cb, run_tb, run_selection_state],
        show_progress="hidden",
        api_visibility="private",
    )
    gr.on(
        [timer.tick],
        fn=lambda: gr.Dropdown(info=fns.get_project_info()),
        outputs=[project_dd],
        show_progress="hidden",
        api_visibility="private",
    )
    gr.on(
        [demo.load, project_dd.change],
        fn=refresh_runs,
        inputs=[project_dd, run_tb, run_selection_state, selected_runs_from_url],
        outputs=[run_cb, run_tb, run_selection_state],
        show_progress="hidden",
        queue=False,
        api_visibility="private",
    ).then(
        fn=update_x_axis_choices,
        inputs=[project_dd, run_selection_state],
        outputs=x_axis_dd,
        show_progress="hidden",
        queue=False,
        api_visibility="private",
    ).then(
        fn=generate_embed,
        inputs=[project_dd, metric_filter_tb, run_selection_state],
        outputs=[embed_code],
        show_progress="hidden",
        api_visibility="private",
        queue=False,
    ).then(
        fns.update_navbar_value,
        inputs=[project_dd],
        outputs=[navbar],
        show_progress="hidden",
        api_visibility="private",
        queue=False,
    ).then(
        fn=fns.get_group_by_fields,
        inputs=[project_dd],
        outputs=[run_group_by_dd],
        show_progress="hidden",
        api_visibility="private",
        queue=False,
    )

    gr.on(
        [run_cb.input],
        fn=update_x_axis_choices,
        inputs=[project_dd, run_selection_state],
        outputs=x_axis_dd,
        show_progress="hidden",
        queue=False,
        api_visibility="private",
    )
    gr.on(
        [metric_filter_tb.change, run_cb.change],
        fn=generate_embed,
        inputs=[project_dd, metric_filter_tb, run_selection_state],
        outputs=embed_code,
        show_progress="hidden",
        api_visibility="private",
        queue=False,
    )

    def toggle_group_view(group_by_dd):
        return (
            gr.CheckboxGroup(visible=not bool(group_by_dd)),
            gr.Group(visible=bool(group_by_dd)),
        )

    gr.on(
        [run_group_by_dd.change],
        fn=toggle_group_view,
        inputs=[run_group_by_dd],
        outputs=[run_cb, grouped_runs_panel],
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
    ).then(
        fn=generate_embed,
        inputs=[project_dd, metric_filter_tb, run_selection_state],
        outputs=embed_code,
        show_progress="hidden",
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

    gr.api(
        fn=upload_db_to_space,
        api_name="upload_db_to_space",
    )
    gr.api(
        fn=bulk_upload_media,
        api_name="bulk_upload_media",
    )
    gr.api(
        fn=log,
        api_name="log",
    )
    gr.api(
        fn=bulk_log,
        api_name="bulk_log",
    )
    gr.api(
        fn=get_metric_values,
        api_name="get_metric_values",
    )
    gr.api(
        fn=get_runs_for_project,
        api_name="get_runs_for_project",
    )
    gr.api(
        fn=get_metrics_for_run,
        api_name="get_metrics_for_run",
    )
    gr.api(
        fn=get_all_projects,
        api_name="get_all_projects",
    )
    gr.api(
        fn=get_project_summary,
        api_name="get_project_summary",
    )
    gr.api(
        fn=get_run_summary,
        api_name="get_run_summary",
    )

    last_steps = gr.State({})

    def update_x_lim(select_data: gr.SelectData):
        return select_data.index

    def update_last_steps(project):
        """Check the last step for each run to detect when new data is available."""
        if not project:
            return {}
        return SQLiteStorage.get_max_steps_for_runs(project)

    timer.tick(
        fn=update_last_steps,
        inputs=[project_dd],
        outputs=last_steps,
        show_progress="hidden",
        api_visibility="private",
    )

    @gr.render(
        triggers=[
            demo.load,
            run_cb.change,
            last_steps.change,
            smoothing_slider.change,
            x_lim.change,
            x_axis_dd.change,
            log_scale_x_cb.change,
            log_scale_y_cb.change,
            metric_filter_tb.change,
        ],
        inputs=[
            project_dd,
            run_cb,
            smoothing_slider,
            metrics_subset,
            x_lim,
            x_axis_dd,
            log_scale_x_cb,
            log_scale_y_cb,
            metric_filter_tb,
            run_selection_state,
        ],
        show_progress="hidden",
        queue=False,
    )
    def update_dashboard(
        project,
        runs,
        smoothing_granularity,
        metrics_subset,
        x_lim_value,
        x_axis,
        log_scale_x,
        log_scale_y,
        metric_filter,
        selection,
    ):
        dfs = []
        original_runs = runs.copy()

        for run in runs:
            df, _ = load_run_data(
                project, run, smoothing_granularity, x_axis, log_scale_x, log_scale_y
            )
            if df is not None:
                dfs.append(df)

        if dfs:
            if smoothing_granularity > 0:
                original_dfs = []
                smoothed_dfs = []
                for df in dfs:
                    original_data = df[df["data_type"] == "original"]
                    smoothed_data = df[df["data_type"] == "smoothed"]
                    if not original_data.empty:
                        original_dfs.append(original_data)
                    if not smoothed_data.empty:
                        smoothed_dfs.append(smoothed_data)

                all_dfs = original_dfs + smoothed_dfs
                master_df = (
                    pd.concat(all_dfs, ignore_index=True) if all_dfs else pd.DataFrame()
                )

            else:
                master_df = pd.concat(dfs, ignore_index=True)
        else:
            master_df = pd.DataFrame()

        if master_df.empty:
            if not SQLiteStorage.get_projects():
                if space_id := utils.get_space():
                    gr.Markdown(INSTRUCTIONS_SPACES.format(space_id))
                else:
                    gr.Markdown(INSTRUCTIONS_LOCAL)
            else:
                gr.Markdown("*Waiting for runs to appear...*")
            return

        x_column = "step"
        if dfs and not dfs[0].empty and "x_axis" in dfs[0].columns:
            x_column = dfs[0]["x_axis"].iloc[0]

        numeric_cols = master_df.select_dtypes(include="number").columns
        numeric_cols = [c for c in numeric_cols if c not in utils.RESERVED_KEYS]
        if x_column and x_column in numeric_cols:
            numeric_cols.remove(x_column)

        if metrics_subset:
            numeric_cols = [c for c in numeric_cols if c in metrics_subset]

        if metric_filter and metric_filter.strip():
            numeric_cols = filter_metrics_by_regex(list(numeric_cols), metric_filter)

        ordered_groups, nested_metric_groups = utils.order_metrics_by_plot_preference(
            list(numeric_cols)
        )
        all_runs = selection.choices if selection else original_runs
        color_map = utils.get_color_mapping(all_runs, smoothing_granularity > 0)

        metric_idx = 0
        for group_name in ordered_groups:
            group_data = nested_metric_groups[group_name]

            total_plot_count = sum(
                1
                for m in group_data["direct_metrics"]
                if not master_df.dropna(subset=[m]).empty
            ) + sum(
                sum(1 for m in metrics if not master_df.dropna(subset=[m]).empty)
                for metrics in group_data["subgroups"].values()
            )
            group_label = (
                f"{group_name} ({total_plot_count})"
                if total_plot_count > 0
                else group_name
            )

            with gr.Accordion(
                label=group_label,
                open=True,
                key=f"accordion-{group_name}",
                preserved_by_key=["value", "open"],
            ):
                if group_data["direct_metrics"]:
                    with gr.Draggable(
                        key=f"row-{group_name}-direct", orientation="row"
                    ):
                        for metric_name in group_data["direct_metrics"]:
                            metric_df = master_df.dropna(subset=[metric_name])
                            color = "run" if "run" in metric_df.columns else None
                            downsampled_df, updated_x_lim = utils.downsample(
                                metric_df,
                                x_column,
                                metric_name,
                                color,
                                x_lim_value,
                            )
                            if not metric_df.empty:
                                plot = gr.LinePlot(
                                    downsampled_df,
                                    x=x_column,
                                    y=metric_name,
                                    y_title=metric_name.split("/")[-1],
                                    color=color,
                                    color_map=color_map,
                                    colors_in_legend=original_runs,
                                    title=metric_name,
                                    key=f"plot-{metric_idx}",
                                    preserved_by_key=None,
                                    buttons=["fullscreen", "export"],
                                    x_lim=updated_x_lim,
                                    min_width=400,
                                )
                                plot.select(
                                    update_x_lim,
                                    outputs=x_lim,
                                    key=f"select-{metric_idx}",
                                )
                                plot.double_click(
                                    lambda: None,
                                    outputs=x_lim,
                                    key=f"double-{metric_idx}",
                                )
                            metric_idx += 1

                if group_data["subgroups"]:
                    for subgroup_name in sorted(group_data["subgroups"].keys()):
                        subgroup_metrics = group_data["subgroups"][subgroup_name]

                        subgroup_plot_count = sum(
                            1
                            for m in subgroup_metrics
                            if not master_df.dropna(subset=[m]).empty
                        )
                        subgroup_label = (
                            f"{subgroup_name} ({subgroup_plot_count})"
                            if subgroup_plot_count > 0
                            else subgroup_name
                        )

                        with gr.Accordion(
                            label=subgroup_label,
                            open=True,
                            key=f"accordion-{group_name}-{subgroup_name}",
                            preserved_by_key=["value", "open"],
                        ):
                            with gr.Draggable(
                                key=f"row-{group_name}-{subgroup_name}",
                                orientation="row",
                            ):
                                for metric_name in subgroup_metrics:
                                    metric_df = master_df.dropna(subset=[metric_name])
                                    color = (
                                        "run" if "run" in metric_df.columns else None
                                    )
                                    downsampled_df, updated_x_lim = utils.downsample(
                                        metric_df,
                                        x_column,
                                        metric_name,
                                        color,
                                        x_lim_value,
                                    )
                                    if not metric_df.empty:
                                        plot = gr.LinePlot(
                                            downsampled_df,
                                            x=x_column,
                                            y=metric_name,
                                            y_title=metric_name.split("/")[-1],
                                            color=color,
                                            color_map=color_map,
                                            colors_in_legend=original_runs,
                                            title=metric_name,
                                            key=f"plot-{metric_idx}",
                                            preserved_by_key=None,
                                            buttons=["fullscreen", "export"],
                                            x_lim=updated_x_lim,
                                            min_width=400,
                                        )
                                        plot.select(
                                            update_x_lim,
                                            outputs=x_lim,
                                            key=f"select-{metric_idx}",
                                        )
                                        plot.double_click(
                                            lambda: None,
                                            outputs=x_lim,
                                            key=f"double-{metric_idx}",
                                        )
                                    metric_idx += 1

    with grouped_runs_panel:

        @gr.render(
            triggers=[
                demo.load,
                project_dd.change,
                run_group_by_dd.change,
                run_tb.input,
                run_selection_state.change,
                last_steps.change,
            ],
            inputs=[project_dd, run_group_by_dd, run_tb, run_selection_state],
            show_progress="hidden",
            queue=False,
        )
        def render_grouped_runs(project, group_key, filter_text, selection):
            if not group_key:
                return
            selection = selection or RunSelection()
            groups = fns.group_runs_by_config(project, group_key, filter_text)

            for label, runs in groups.items():
                ordered_current = utils.ordered_subset(runs, selection.selected)

                with gr.Group():
                    show_group_cb = gr.Checkbox(
                        label="Show/Hide",
                        value=bool(ordered_current),
                        key=f"show-cb-{group_key}-{label}",
                        preserved_by_key=["value"],
                    )

                    with gr.Accordion(
                        f"{label} ({len(runs)})",
                        open=False,
                        key=f"accordion-{group_key}-{label}",
                        preserved_by_key=["open"],
                    ):
                        color_palette = utils.get_color_palette()
                        choice_indices = {
                            run: i for i, run in enumerate(selection.choices)
                        }
                        colors = [
                            color_palette[
                                choice_indices.get(run, 0) % len(color_palette)
                            ]
                            for run in runs
                        ]
                        group_cb = ColoredCheckboxGroup(
                            choices=runs,
                            value=ordered_current,
                            colors=colors,
                            label=f"Runs ({len(runs)})",
                            key=f"group-cb-{group_key}-{label}",
                            preserved_by_key=None,
                        )

                        gr.on(
                            [group_cb.input],
                            fn=fns.handle_group_checkbox_change,
                            inputs=[
                                group_cb,
                                run_selection_state,
                                gr.State(runs),
                            ],
                            outputs=[
                                run_selection_state,
                                group_cb,
                                run_cb,
                            ],
                            show_progress="hidden",
                            api_visibility="private",
                            queue=False,
                        )

                        gr.on(
                            [show_group_cb.change],
                            fn=fns.handle_group_toggle,
                            inputs=[
                                show_group_cb,
                                run_selection_state,
                                gr.State(runs),
                            ],
                            outputs=[run_selection_state, group_cb, run_cb],
                            show_progress="hidden",
                            api_visibility="private",
                            queue=False,
                        )


with demo.route("Media", show_in_navbar=False):
    media_page.render()
with demo.route("Runs", show_in_navbar=False):
    run_page.render()
with demo.route("Run", show_in_navbar=False):
    run_detail_page.render()
with demo.route("Files", show_in_navbar=False):
    files_page.render()

write_token = secrets.token_urlsafe(32)
demo.write_token = write_token
run_page.write_token = write_token
run_detail_page.write_token = write_token
files_page.write_token = write_token

if __name__ == "__main__":
    demo.launch(
        allowed_paths=[utils.TRACKIO_LOGO_DIR, utils.TRACKIO_DIR],
        footer_links=["gradio", "settings"],
        show_error=True,
    )
