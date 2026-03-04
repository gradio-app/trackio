"""The Reports & Alerts page for the Trackio UI."""

from dataclasses import dataclass

import gradio as gr
import pandas as pd

import trackio.utils as utils
from trackio.markdown import Markdown
from trackio.sqlite_storage import SQLiteStorage
from trackio.ui import fns
from trackio.ui.components.colored_dropdown import ColoredDropdown

LEVEL_BADGES = {
    "info": "🔵",
    "warn": "🟡",
    "error": "🔴",
}


def load_alerts(
    project: str | None,
    run_name: str | None = None,
    level_filter: list[str] | None = None,
) -> pd.DataFrame:
    if not project:
        return pd.DataFrame()

    selected_levels = set(level_filter or [])
    alerts = SQLiteStorage.get_alerts(project, run_name=run_name, level=None)
    if level_filter is not None:
        alerts = [a for a in alerts if a["level"] in selected_levels]
    if not alerts:
        return pd.DataFrame()

    df = pd.DataFrame(alerts)
    df["timestamp"] = df["timestamp"].map(utils.format_timestamp)
    df["level"] = df["level"].map(
        lambda lvl: f"{LEVEL_BADGES.get(lvl, '')} {lvl.upper()}"
    )
    df["text"] = df["text"].fillna("")
    df = df[["timestamp", "level", "title", "text", "step"]]
    df.columns = ["Timestamp", "Level", "Title", "Text", "Step"]
    return df


@dataclass
class ReportEntry:
    key: str
    step: int | None
    timestamp: str
    content: str


def refresh_runs_dropdown(project: str | None):
    if project is None:
        runs: list[str] = []
    else:
        runs = fns.get_runs(project)

    color_palette = utils.get_color_palette()
    colors = [color_palette[i % len(color_palette)] for i in range(len(runs))]

    return ColoredDropdown(
        choices=runs,
        colors=colors,
        value=runs[0] if runs else None,
        placeholder=f"Select a run ({len(runs)})",
    )


def extract_reports(logs: list[dict]) -> list[ReportEntry]:
    reports: list[ReportEntry] = []
    for log in logs:
        step = log.get("step")
        timestamp = log.get("timestamp")
        if not isinstance(timestamp, str):
            continue
        for key, value in log.items():
            if key in utils.RESERVED_KEYS:
                continue
            if isinstance(value, dict) and value.get("_type") == Markdown.TYPE:
                content = value.get("_value")
                if isinstance(content, str):
                    reports.append(
                        ReportEntry(
                            key=key,
                            step=step,
                            timestamp=timestamp,
                            content=content,
                        )
                    )
    return sorted(
        reports,
        key=lambda r: (r.step if r.step is not None else -1, r.timestamp),
        reverse=True,
    )


with gr.Blocks() as reports_page:
    with gr.Sidebar() as sidebar:
        logo = fns.create_logo()
        project_dd = fns.create_project_dropdown()
        runs_dropdown = ColoredDropdown(choices=[], colors=[], label="Run")

        gr.HTML("<hr>")
        level_filter_cb = gr.CheckboxGroup(
            label="Alert Levels",
            choices=["info", "warn", "error"],
            value=["info", "warn", "error"],
            interactive=True,
        )

    navbar = fns.create_navbar()
    timer = gr.Timer(value=1)
    fns.setup_alert_notifications(timer, project_dd)

    @gr.render(
        triggers=[reports_page.load, runs_dropdown.change, project_dd.change],
        inputs=[project_dd, runs_dropdown],
        show_progress="hidden",
        queue=False,
    )
    def display_reports(project: str | None, selected_run: str | None):
        if not project or not selected_run:
            gr.Markdown("*Select a project and run to view reports*")
            return

        logs = SQLiteStorage.get_logs(project, selected_run)
        if not logs:
            gr.Markdown("*No data found for this run*")
            return

        reports = extract_reports(logs)
        if not reports:
            gr.Markdown(
                """
## No Reports Available

Reports will appear here once logged. To log a markdown report:

```python
import trackio

run = trackio.init(project="my-project")

# Log metrics as usual
trackio.log({"loss": 0.5, "accuracy": 0.9})

# Log a markdown report
report = \"\"\"# Training Report
- Final loss: 0.05
- Best accuracy: 0.98
\"\"\"
trackio.log({"training_report": trackio.Markdown(report)})
```
"""
            )
            return

        for index, report in enumerate(reports):
            formatted_timestamp = utils.format_timestamp(report.timestamp)
            label = (
                f"{report.key} | step {report.step if report.step is not None else 'N/A'} | "
                f"{formatted_timestamp}"
            )
            with gr.Accordion(label=label, open=index == 0):
                gr.Markdown(
                    f"**Time:** {formatted_timestamp}  \n"
                    f"**Step:** `{report.step if report.step is not None else 'N/A'}`  \n"
                    f"**Report key:** `{report.key}`"
                )
                gr.Markdown(report.content)

    gr.Markdown("## Alerts")
    alerts_df = gr.Dataframe(
        value=pd.DataFrame(),
        label="Alerts",
        interactive=False,
        wrap=True,
    )

    def refresh_alerts(project, selected_run, level_filter):
        df = load_alerts(project, run_name=selected_run, level_filter=level_filter)
        return gr.Dataframe(value=df, label=f"Alerts ({len(df)})")

    gr.on(
        [timer.tick, reports_page.load, runs_dropdown.change, level_filter_cb.change],
        fn=refresh_alerts,
        inputs=[project_dd, runs_dropdown, level_filter_cb],
        outputs=alerts_df,
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
        [reports_page.load],
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
        [project_dd.change],
        fn=refresh_runs_dropdown,
        inputs=[project_dd],
        outputs=[runs_dropdown],
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
