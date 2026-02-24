"""The Alerts page for the Trackio UI."""

import gradio as gr
import pandas as pd

import trackio.utils as utils
from trackio.sqlite_storage import SQLiteStorage
from trackio.ui import fns
from trackio.ui.components.colored_checkbox import ColoredCheckboxGroup
from trackio.ui.helpers.run_selection import RunSelection

LEVEL_BADGES = {
    "info": "🔵",
    "warn": "🟡",
    "error": "🔴",
}


def load_alerts(
    project: str | None,
    run_filter: list[str] | None = None,
    level_filter: list[str] | None = None,
) -> pd.DataFrame:
    if not project:
        return pd.DataFrame()

    selected_levels = set(level_filter or [])
    selected_runs = set(run_filter or [])
    alerts = SQLiteStorage.get_alerts(project, run_name=None, level=None)
    if run_filter:
        alerts = [a for a in alerts if a["run"] in selected_runs]
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
    df = df[["timestamp", "run", "level", "title", "text", "step"]]
    df.columns = ["Timestamp", "Run", "Level", "Title", "Text", "Step"]
    return df


with gr.Blocks() as alerts_page:
    with gr.Sidebar() as sidebar:
        logo = fns.create_logo()
        project_dd = fns.create_project_dropdown()

        with gr.Group():
            run_tb = gr.Textbox(label="Runs", placeholder="Type to filter...")
        run_cb = ColoredCheckboxGroup(choices=[], colors=[], label="Runs")
        level_filter_dd = gr.CheckboxGroup(
            label="Filter by Level",
            choices=["info", "warn", "error"],
            value=["info", "warn", "error"],
            interactive=True,
        )

        gr.HTML("<hr>")
        realtime_cb = gr.Checkbox(label="Refresh alerts realtime", value=True)

    navbar = fns.create_navbar()
    timer = gr.Timer(value=2)
    last_alert_snapshot = gr.State({})
    run_selection_state = gr.State(RunSelection())

    def toggle_timer(cb_value):
        if cb_value:
            return gr.Timer(active=True)
        else:
            return gr.Timer(active=False)

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

    def check_alert_snapshot(project):
        if not project:
            return {}
        count = SQLiteStorage.get_alert_count(project)
        runs = SQLiteStorage.get_runs(project)
        return {"count": count, "runs_len": len(runs)}

    @gr.render(
        triggers=[
            alerts_page.load,
            run_cb.change,
            level_filter_dd.change,
            last_alert_snapshot.change,
        ],
        inputs=[project_dd, run_cb, level_filter_dd],
        show_progress="hidden",
        queue=False,
    )
    def render_alerts(project, run_filter, level_filter):
        df = load_alerts(project, run_filter, level_filter)
        if df.empty:
            gr.Markdown(
                """
## No Alerts

Alerts will appear here when triggered. You can fire alerts from your training code:

```python
import trackio

trackio.init(project="my-project")

trackio.alert(
    title="Low margin",
    text="Margin dropped below threshold",
    level=trackio.AlertLevel.WARN,
)
```
"""
            )
            return

        gr.Dataframe(
            value=df,
            label=f"Alerts ({len(df)})",
            interactive=False,
            wrap=True,
        )

    gr.on(
        [timer.tick],
        fn=lambda: gr.Dropdown(info=fns.get_project_info()),
        outputs=[project_dd],
        show_progress="hidden",
        api_visibility="private",
    )

    gr.on(
        [timer.tick],
        fn=check_alert_snapshot,
        inputs=[project_dd],
        outputs=last_alert_snapshot,
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
        [alerts_page.load],
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
        [alerts_page.load, project_dd.change],
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
