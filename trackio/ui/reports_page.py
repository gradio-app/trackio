"""The Reports page for the Trackio UI."""

from dataclasses import dataclass

import gradio as gr

import trackio.utils as utils
from trackio.markdown import Markdown
from trackio.sqlite_storage import SQLiteStorage
from trackio.ui import fns
from trackio.ui.components.colored_dropdown import ColoredDropdown


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

    navbar = fns.create_navbar()
    timer = gr.Timer(value=1)

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
            gr.Markdown("*No reports found for this run*")
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
