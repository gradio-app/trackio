"""The main page for the Trackio UI."""

import os
import re
import secrets
import shutil
from dataclasses import dataclass
from typing import Any

import gradio as gr
import huggingface_hub as hf
import numpy as np
import pandas as pd

HfApi = hf.HfApi()

try:
    import trackio.utils as utils
    from trackio.file_storage import FileStorage
    from trackio.media import TrackioImage, TrackioVideo
    from trackio.sqlite_storage import SQLiteStorage
    from trackio.table import Table
    from trackio.typehints import LogEntry, UploadEntry
    from trackio.ui import fns
    from trackio.ui.run_detail import run_detail_page
    from trackio.ui.runs import run_page
except ImportError:
    import utils
    from file_storage import FileStorage
    from media import TrackioImage, TrackioVideo
    from sqlite_storage import SQLiteStorage
    from table import Table
    from typehints import LogEntry, UploadEntry
    from ui import fns
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


def extract_media(logs: list[dict]) -> dict[str, list[MediaData]]:
    media_by_key: dict[str, list[MediaData]] = {}
    logs = sorted(logs, key=lambda x: x.get("step", 0))
    for log in logs:
        for key, value in log.items():
            if isinstance(value, dict):
                type = value.get("_type")
                if type == TrackioImage.TYPE or type == TrackioVideo.TYPE:
                    if key not in media_by_key:
                        media_by_key[key] = []
                    try:
                        media_data = MediaData(
                            file_path=utils.MEDIA_DIR / value.get("file_path"),
                            caption=value.get("caption"),
                        )
                        media_by_key[key].append(media_data)
                    except Exception as e:
                        print(f"Media currently unavailable: {key}: {e}")
    return media_by_key


def load_run_data(
    project: str | None,
    run: str | None,
    smoothing_granularity: int,
    x_axis: str,
    log_scale: bool = False,
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

    if log_scale and x_column in df.columns:
        x_vals = df[x_column]
        if (x_vals <= 0).any():
            df[x_column] = np.log10(np.maximum(x_vals, 0) + 1)
        else:
            df[x_column] = np.log10(x_vals)

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


def update_runs(
    project, filter_text, user_interacted_with_runs=False, selected_runs_from_url=None
):
    if project is None:
        runs = []
        num_runs = 0
    else:
        runs = get_runs(project)
        num_runs = len(runs)
        if filter_text:
            runs = [r for r in runs if filter_text in r]

    if not user_interacted_with_runs:
        if selected_runs_from_url:
            value = [r for r in runs if r in selected_runs_from_url]
        else:
            value = runs
        return gr.CheckboxGroup(choices=runs, value=value), gr.Textbox(
            label=f"Runs ({num_runs})"
        )
    else:
        return gr.CheckboxGroup(choices=runs), gr.Textbox(label=f"Runs ({num_runs})")


def filter_runs(project, filter_text):
    runs = get_runs(project)
    runs = [r for r in runs if filter_text in r]
    return gr.CheckboxGroup(choices=runs, value=runs)


def update_x_axis_choices(project, runs):
    """Update x-axis dropdown choices based on available metrics."""
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


def check_auth(hf_token: str | None) -> None:
    if os.getenv("SYSTEM") == "spaces":  # if we are running in Spaces
        # check auth token passed in
        if hf_token is None:
            raise PermissionError(
                "Expected a HF_TOKEN to be provided when logging to a Space"
            )
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
                    (
                        item["entity"]["type"] == "user"
                        or item["entity"]["type"] == "org"
                    )
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


def upload_db_to_space(
    project: str, uploaded_db: gr.FileData, hf_token: str | None
) -> None:
    check_auth(hf_token)
    db_project_path = SQLiteStorage.get_project_db_path(project)
    if os.path.exists(db_project_path):
        raise gr.Error(
            f"Trackio database file already exists for project {project}, cannot overwrite."
        )
    os.makedirs(os.path.dirname(db_project_path), exist_ok=True)
    shutil.copy(uploaded_db["path"], db_project_path)


def bulk_upload_media(uploads: list[UploadEntry], hf_token: str | None) -> None:
    check_auth(hf_token)
    for upload in uploads:
        media_path = FileStorage.init_project_media_path(
            upload["project"], upload["run"], upload["step"]
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
    check_auth(hf_token)
    SQLiteStorage.log(project=project, run=run, metrics=metrics, step=step)


def bulk_log(
    logs: list[LogEntry],
    hf_token: str | None,
) -> None:
    check_auth(hf_token)

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
    match navbar_param:
        case "hidden":
            navbar = gr.Navbar(visible=False)
        case _:
            navbar = gr.Navbar(visible=True)

    return [], sidebar, metrics_param, selected_runs, navbar


def create_media_section(media_by_run: dict[str, dict[str, list[MediaData]]]):
    with gr.Accordion(label="media"):
        with gr.Group(elem_classes=("media-group")):
            for run, media_by_key in media_by_run.items():
                with gr.Tab(label=run, elem_classes=("media-tab")):
                    for key, media_item in media_by_key.items():
                        gr.Gallery(
                            [(item.file_path, item.caption) for item in media_item],
                            label=key,
                            columns=6,
                            elem_classes=("media-gallery"),
                        )


css = """
#run-cb .wrap { gap: 2px; }
#run-cb .wrap label {
    line-height: 1;
    padding: 6px;
}
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
"""

javascript = """
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
    
    if (writeToken) {
        setCookie('trackio_write_token', writeToken, 7);
        
        urlParams.delete('write_token');
        const newUrl = window.location.pathname + 
            (urlParams.toString() ? '?' + urlParams.toString() : '') + 
            window.location.hash;
        window.history.replaceState({}, document.title, newUrl);
    }
})();
</script>
"""


gr.set_static_paths(paths=[utils.MEDIA_DIR])

with gr.Blocks(title="Trackio Dashboard", css=css, head=javascript) as demo:
    with gr.Sidebar(open=False) as sidebar:
        logo = gr.Markdown(
            f"""
                <img src='/gradio_api/file={utils.TRACKIO_LOGO_DIR}/trackio_logo_type_light_transparent.png' width='80%' class='logo-light'>
                <img src='/gradio_api/file={utils.TRACKIO_LOGO_DIR}/trackio_logo_type_dark_transparent.png' width='80%' class='logo-dark'>            
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
        run_tb = gr.Textbox(label="Runs", placeholder="Type to filter...")
        run_cb = gr.CheckboxGroup(
            label="Runs",
            choices=[],
            interactive=True,
            elem_id="run-cb",
            show_select_all=True,
        )
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
        log_scale_cb = gr.Checkbox(label="Log scale X-axis", value=False)
        metric_filter_tb = gr.Textbox(
            label="Metric Filter (regex)",
            placeholder="e.g., loss|ndcg@10|gpu",
            value="",
            info="Filter metrics using regex patterns. Leave empty to show all metrics.",
        )

    navbar = gr.Navbar(value=[("Metrics", ""), ("Runs", "/runs")], main_page_name=False)
    timer = gr.Timer(value=1)
    metrics_subset = gr.State([])
    user_interacted_with_run_cb = gr.State(False)
    selected_runs_from_url = gr.State([])

    gr.on(
        [demo.load],
        fn=configure,
        outputs=[
            metrics_subset,
            sidebar,
            metric_filter_tb,
            selected_runs_from_url,
            navbar,
        ],
        queue=False,
        api_name=False,
    )
    gr.on(
        [demo.load],
        fn=fns.get_projects,
        outputs=project_dd,
        show_progress="hidden",
        queue=False,
        api_name=False,
    )
    gr.on(
        [timer.tick],
        fn=update_runs,
        inputs=[
            project_dd,
            run_tb,
            user_interacted_with_run_cb,
            selected_runs_from_url,
        ],
        outputs=[run_cb, run_tb],
        show_progress="hidden",
        api_name=False,
    )
    gr.on(
        [timer.tick],
        fn=lambda: gr.Dropdown(info=fns.get_project_info()),
        outputs=[project_dd],
        show_progress="hidden",
        api_name=False,
    )
    gr.on(
        [demo.load, project_dd.change],
        fn=update_runs,
        inputs=[project_dd, run_tb, gr.State(False), selected_runs_from_url],
        outputs=[run_cb, run_tb],
        show_progress="hidden",
        queue=False,
        api_name=False,
    ).then(
        fn=update_x_axis_choices,
        inputs=[project_dd, run_cb],
        outputs=x_axis_dd,
        show_progress="hidden",
        queue=False,
        api_name=False,
    ).then(
        fn=utils.generate_embed_code,
        inputs=[project_dd, metric_filter_tb, run_cb],
        outputs=[embed_code],
        show_progress="hidden",
        api_name=False,
        queue=False,
    ).then(
        fns.update_navbar_value,
        inputs=[project_dd],
        outputs=[navbar],
        show_progress="hidden",
        api_name=False,
        queue=False,
    )

    gr.on(
        [run_cb.input],
        fn=update_x_axis_choices,
        inputs=[project_dd, run_cb],
        outputs=x_axis_dd,
        show_progress="hidden",
        queue=False,
        api_name=False,
    )
    gr.on(
        [metric_filter_tb.change, run_cb.change],
        fn=utils.generate_embed_code,
        inputs=[project_dd, metric_filter_tb, run_cb],
        outputs=embed_code,
        show_progress="hidden",
        api_name=False,
        queue=False,
    )

    realtime_cb.change(
        fn=toggle_timer,
        inputs=realtime_cb,
        outputs=timer,
        api_name=False,
        queue=False,
    )
    run_cb.input(
        fn=lambda: True,
        outputs=user_interacted_with_run_cb,
        api_name=False,
        queue=False,
    )
    run_tb.input(
        fn=filter_runs,
        inputs=[project_dd, run_tb],
        outputs=run_cb,
        api_name=False,
        queue=False,
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

    x_lim = gr.State(None)
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
        api_name=False,
    )

    @gr.render(
        triggers=[
            demo.load,
            run_cb.change,
            last_steps.change,
            smoothing_slider.change,
            x_lim.change,
            x_axis_dd.change,
            log_scale_cb.change,
            metric_filter_tb.change,
        ],
        inputs=[
            project_dd,
            run_cb,
            smoothing_slider,
            metrics_subset,
            x_lim,
            x_axis_dd,
            log_scale_cb,
            metric_filter_tb,
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
        log_scale,
        metric_filter,
    ):
        dfs = []
        images_by_run = {}
        original_runs = runs.copy()

        for run in runs:
            df, images_by_key = load_run_data(
                project, run, smoothing_granularity, x_axis, log_scale
            )
            if df is not None:
                dfs.append(df)
                images_by_run[run] = images_by_key

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
            if space_id := os.environ.get("SPACE_ID"):
                gr.Markdown(INSTRUCTIONS_SPACES.format(space_id))
            else:
                gr.Markdown(INSTRUCTIONS_LOCAL)
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

        nested_metric_groups = utils.group_metrics_with_subprefixes(list(numeric_cols))
        color_map = utils.get_color_mapping(original_runs, smoothing_granularity > 0)

        metric_idx = 0
        for group_name in sorted(nested_metric_groups.keys()):
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
                            if not metric_df.empty:
                                plot = gr.LinePlot(
                                    utils.downsample(
                                        metric_df,
                                        x_column,
                                        metric_name,
                                        color,
                                        x_lim_value,
                                    ),
                                    x=x_column,
                                    y=metric_name,
                                    y_title=metric_name.split("/")[-1],
                                    color=color,
                                    color_map=color_map,
                                    title=metric_name,
                                    key=f"plot-{metric_idx}",
                                    preserved_by_key=None,
                                    x_lim=x_lim_value,
                                    show_fullscreen_button=True,
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
                            with gr.Draggable(key=f"row-{group_name}-{subgroup_name}"):
                                for metric_name in subgroup_metrics:
                                    metric_df = master_df.dropna(subset=[metric_name])
                                    color = (
                                        "run" if "run" in metric_df.columns else None
                                    )
                                    if not metric_df.empty:
                                        plot = gr.LinePlot(
                                            utils.downsample(
                                                metric_df,
                                                x_column,
                                                metric_name,
                                                color,
                                                x_lim_value,
                                            ),
                                            x=x_column,
                                            y=metric_name,
                                            y_title=metric_name.split("/")[-1],
                                            color=color,
                                            color_map=color_map,
                                            title=metric_name,
                                            key=f"plot-{metric_idx}",
                                            preserved_by_key=None,
                                            x_lim=x_lim_value,
                                            show_fullscreen_button=True,
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
        if images_by_run and any(any(images) for images in images_by_run.values()):
            create_media_section(images_by_run)

        table_cols = master_df.select_dtypes(include="object").columns
        table_cols = [c for c in table_cols if c not in utils.RESERVED_KEYS]
        if metrics_subset:
            table_cols = [c for c in table_cols if c in metrics_subset]
        if metric_filter and metric_filter.strip():
            table_cols = filter_metrics_by_regex(list(table_cols), metric_filter)

        actual_table_count = sum(
            1
            for metric_name in table_cols
            if not (metric_df := master_df.dropna(subset=[metric_name])).empty
            and isinstance(value := metric_df[metric_name].iloc[-1], dict)
            and value.get("_type") == Table.TYPE
        )

        if actual_table_count > 0:
            with gr.Accordion(f"tables ({actual_table_count})", open=True):
                with gr.Row(key="row"):
                    for metric_idx, metric_name in enumerate(table_cols):
                        metric_df = master_df.dropna(subset=[metric_name])
                        if not metric_df.empty:
                            value = metric_df[metric_name].iloc[-1]
                            if (
                                isinstance(value, dict)
                                and "_type" in value
                                and value["_type"] == Table.TYPE
                            ):
                                try:
                                    df = pd.DataFrame(value["_value"])
                                    gr.DataFrame(
                                        df,
                                        label=f"{metric_name} (latest)",
                                        key=f"table-{metric_idx}",
                                        wrap=True,
                                    )
                                except Exception as e:
                                    gr.Warning(
                                        f"Column {metric_name} failed to render as a table: {e}"
                                    )


with demo.route("Runs", show_in_navbar=False):
    run_page.render()
with demo.route("Run", show_in_navbar=False):
    run_detail_page.render()

write_token = secrets.token_urlsafe(32)
demo.write_token = write_token
run_page.write_token = write_token
run_detail_page.write_token = write_token

if __name__ == "__main__":
    demo.launch(allowed_paths=[utils.TRACKIO_LOGO_DIR], show_api=False, show_error=True)
