"""The Alerts page for the Trackio UI."""

import gradio as gr
import pandas as pd

from trackio.sqlite_storage import SQLiteStorage
from trackio.ui import fns

LEVEL_BADGES = {
    "info": "🔵",
    "warn": "🟡",
    "error": "🔴",
}


def load_alerts(
    project: str | None,
    run_filter: str | None = None,
    level_filter: str | None = None,
) -> pd.DataFrame:
    if not project:
        return pd.DataFrame()

    level = level_filter if level_filter and level_filter != "all" else None
    alerts = SQLiteStorage.get_alerts(project, run_name=run_filter, level=level)
    if not alerts:
        return pd.DataFrame()

    df = pd.DataFrame(alerts)
    df["level"] = df["level"].map(lambda lvl: f"{LEVEL_BADGES.get(lvl, '')} {lvl.upper()}")
    df["text"] = df["text"].fillna("")
    df = df[["timestamp", "run", "level", "title", "text", "step"]]
    df.columns = ["Timestamp", "Run", "Level", "Title", "Text", "Step"]
    return df


with gr.Blocks() as alerts_page:
    with gr.Sidebar() as sidebar:
        logo = fns.create_logo()
        project_dd = fns.create_project_dropdown()

        run_filter_dd = gr.Dropdown(
            label="Filter by Run",
            choices=[],
            value=None,
            allow_custom_value=True,
            interactive=True,
        )
        level_filter_dd = gr.Dropdown(
            label="Filter by Level",
            choices=["all", "info", "warn", "error"],
            value="all",
            interactive=True,
        )

        gr.HTML("<hr>")
        realtime_cb = gr.Checkbox(label="Refresh alerts realtime", value=True)

    navbar = fns.create_navbar()
    timer = gr.Timer(value=2)
    last_alert_count = gr.State(0)

    def toggle_timer(cb_value):
        if cb_value:
            return gr.Timer(active=True)
        else:
            return gr.Timer(active=False)

    def update_run_choices(project):
        if not project:
            return gr.Dropdown(choices=[], value=None)
        runs = fns.get_runs(project)
        return gr.Dropdown(choices=[None] + runs, value=None)

    def check_alert_count(project):
        if not project:
            return 0
        return SQLiteStorage.get_alert_count(project)

    @gr.render(
        triggers=[
            alerts_page.load,
            project_dd.change,
            run_filter_dd.change,
            level_filter_dd.change,
            last_alert_count.change,
        ],
        inputs=[project_dd, run_filter_dd, level_filter_dd],
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

# Imperative: fire an alert immediately
trackio.alert(
    title="Low margin",
    text="Margin dropped below threshold",
    level=trackio.AlertLevel.WARN,
)

# Declarative: fire when condition transitions to True
trackio.alert_when(
    condition=lambda m: m["loss"] > 5.0,
    title="Loss spike",
    text=lambda m: f"Loss spiked to {m['loss']:.4f}",
    level=trackio.AlertLevel.ERROR,
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
        fn=check_alert_count,
        inputs=[project_dd],
        outputs=last_alert_count,
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
        fn=update_run_choices,
        inputs=[project_dd],
        outputs=[run_filter_dd],
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
