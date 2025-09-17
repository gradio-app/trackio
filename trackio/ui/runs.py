"""The Runs page for the Trackio UI."""

import gradio as gr
import pandas as pd

try:
    import trackio.utils as utils
    from trackio.sqlite_storage import SQLiteStorage
    from trackio.ui import fns
except ImportError:
    import utils
    from sqlite_storage import SQLiteStorage
    from ui import fns


def check_write_access_runs(request: gr.Request):
    """Check if the user has write access based on token validation."""
    # Import demo from main to access write_token
    from trackio.ui.main import demo

    if not hasattr(demo, "write_token"):
        return False

    # Check cookie first
    cookies = request.headers.get("cookie", "")
    if cookies:
        for cookie in cookies.split(";"):
            parts = cookie.strip().split("=")
            if len(parts) == 2 and parts[0] == "trackio_write_token":
                if parts[1] == demo.write_token:
                    return True

    # Check query parameter as fallback
    if hasattr(request, "query_params") and request.query_params:
        token = request.query_params.get("write_token")
        if token == demo.write_token:
            return True

    return False


def update_write_access_indicator_runs(request: gr.Request):
    """Update the write access indicator based on token validation."""
    has_access = check_write_access_runs(request)
    if has_access:
        return gr.HTML(
            '<div style="background-color: #10b981; color: white; padding: 2px 8px; border-radius: 4px; font-size: 12px; font-weight: 500; margin-bottom: 10px; display: inline-block;">✅ Write access enabled</div>',
            visible=True,
        )
    return gr.HTML(visible=False)


with gr.Blocks() as run_page:
    with gr.Sidebar() as sidebar:
        logo = gr.Markdown(
            f"""
                <img src='/gradio_api/file={utils.TRACKIO_LOGO_DIR}/trackio_logo_type_light_transparent.png' width='80%' class='logo-light'>
                <img src='/gradio_api/file={utils.TRACKIO_LOGO_DIR}/trackio_logo_type_dark_transparent.png' width='80%' class='logo-dark'>            
            """
        )
        write_access_indicator = gr.HTML(visible=False)
        project_dd = gr.Dropdown(label="Project", allow_custom_value=True)

    navbar = gr.Navbar(value=[("Metrics", ""), ("Runs", "/runs")], main_page_name=False)
    timer = gr.Timer(value=1)
    runs_table = gr.DataFrame()

    def get_runs_table(project):
        configs = SQLiteStorage.get_all_run_configs(project)
        if not configs:
            return gr.DataFrame(pd.DataFrame(), visible=False)

        df = pd.DataFrame.from_dict(configs, orient="index")
        df = df.fillna("")
        df.index.name = "Name"
        df.reset_index(inplace=True)

        column_mapping = {"_Username": "Username", "_Created": "Created"}
        df.rename(columns=column_mapping, inplace=True)

        if "Created" in df.columns:
            df["Created"] = df["Created"].apply(utils.format_timestamp)

        if "Username" in df.columns:
            df["Username"] = df["Username"].apply(
                lambda x: f"[{x}](https://huggingface.co/{x})"
                if x and x != "None"
                else x
            )

        columns = list(df.columns)
        if "Username" in columns and "Created" in columns:
            columns.remove("Username")
            columns.remove("Created")
            columns.insert(1, "Username")
            columns.insert(2, "Created")
            df = df[columns]

        return gr.DataFrame(
            df, visible=True, pinned_columns=1, datatype="markdown", wrap=True
        )

    gr.on(
        [run_page.load],
        fn=fns.get_projects,
        outputs=project_dd,
        show_progress="hidden",
        queue=False,
        api_name=False,
    )
    gr.on(
        [run_page.load],
        fn=update_write_access_indicator_runs,
        outputs=write_access_indicator,
        show_progress="hidden",
        queue=False,
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
        [project_dd.change],
        fn=get_runs_table,
        inputs=[project_dd],
        outputs=[runs_table],
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
