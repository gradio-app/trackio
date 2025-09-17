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


def update_delete_button_access(request: gr.Request):
    """Update the delete button text based on write access."""
    has_access = check_write_access_runs(request)
    if has_access:
        return gr.Button(
            "Select and delete run(s)", interactive=False, variant="stop", size="sm"
        )
    else:
        return gr.Button(
            "⚠️ Need write access to delete runs",
            interactive=False,
            variant="secondary",
            size="sm",
        )


def update_delete_button_interactivity(runs_data, request: gr.Request):
    if not check_write_access_runs(request):
        return

    has_selection = False
    print("runs_data", runs_data)
    if runs_data is not None and len(runs_data) > 0:
        first_column = [row[0] if len(row) > 0 else False for row in runs_data]
        print("first_column", first_column)
        has_selection = any(first_column)

    if has_selection:
        return gr.Button("Delete selected run(s)", interactive=True)
    else:
        return gr.Button("Select runs to delete", interactive=False)


with gr.Blocks() as run_page:

    def check_write_access_runs(request: gr.Request):
        """Check if the user has write access based on token validation."""

        if not hasattr(run_page, "write_token"):
            return False

        # Check cookie first
        cookies = request.headers.get("cookie", "")
        if cookies:
            for cookie in cookies.split(";"):
                parts = cookie.strip().split("=")
                if len(parts) == 2 and parts[0] == "trackio_write_token":
                    if parts[1] == run_page.write_token:
                        return True

        # Check query parameter as fallback
        if hasattr(request, "query_params") and request.query_params:
            token = request.query_params.get("write_token")
            if token == run_page.write_token:
                return True

        return False

    with gr.Sidebar() as sidebar:
        logo = gr.Markdown(
            f"""
                <img src='/gradio_api/file={utils.TRACKIO_LOGO_DIR}/trackio_logo_type_light_transparent.png' width='80%' class='logo-light'>
                <img src='/gradio_api/file={utils.TRACKIO_LOGO_DIR}/trackio_logo_type_dark_transparent.png' width='80%' class='logo-dark'>            
            """
        )
        project_dd = gr.Dropdown(label="Project", allow_custom_value=True)

    navbar = gr.Navbar(value=[("Metrics", ""), ("Runs", "/runs")], main_page_name=False)
    timer = gr.Timer(value=1)
    with gr.Row():
        gr.Markdown("")
        delete_run_btn = gr.Button(
            "⚠️ Need write access to delete runs",
            interactive=False,
            variant="stop",
            size="sm",
        )
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

        # Add a column of False values as the first column
        df.insert(0, " ", False)

        columns = list(df.columns)
        if "Username" in columns and "Created" in columns:
            columns.remove("Username")
            columns.remove("Created")
            columns.insert(2, "Username")  # Shift right due to new Select column
            columns.insert(3, "Created")  # Shift right due to new Select column
            df = df[columns]

        # Create datatype list: first column is bool, rest are markdown
        datatype = ["bool"] + ["markdown"] * (len(df.columns) - 1)

        return gr.DataFrame(
            df,
            visible=True,
            pinned_columns=2,
            datatype=datatype,
            wrap=True,
            column_widths=["40px", "100px"],
            interactive=True,
            static_columns=list(range(1, len(df.columns))),
            row_count=(len(df), "fixed"),
            col_count=(len(df.columns), "fixed"),
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

    gr.on(
        [runs_table.change],
        fn=update_delete_button_interactivity,
        inputs=[runs_table],
        outputs=[delete_run_btn],
        show_progress="hidden",
        api_name=False,
        queue=False,
    )
