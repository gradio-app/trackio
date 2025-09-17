"""The Runs page for the Trackio UI."""

import re

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


def get_runs_data(project):
    """Get the runs data as a pandas DataFrame."""
    configs = SQLiteStorage.get_all_run_configs(project)
    if not configs:
        return pd.DataFrame()

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
            lambda x: f"<a href='https://huggingface.co/{x}' style='text-decoration-style: dotted;'>{x}</a>"
            if x and x != "None"
            else x
        )

    if "Name" in df.columns:
        df["Name"] = df["Name"].apply(
            lambda x: f"<a href='/run?selected_project={project}&selected_run={x}'>{x}</a>"
            if x and x != "None"
            else x
        )

    df.insert(0, " ", False)

    columns = list(df.columns)
    if "Username" in columns and "Created" in columns:
        columns.remove("Username")
        columns.remove("Created")
        columns.insert(2, "Username")
        columns.insert(3, "Created")
        df = df[columns]

    return df


def get_runs_table(project):
    df = get_runs_data(project)
    if df.empty:
        return gr.DataFrame(pd.DataFrame(), visible=False)

    datatype = ["bool"] + ["markdown"] * (len(df.columns) - 1)

    return gr.DataFrame(
        df,
        visible=True,
        pinned_columns=2,
        datatype=datatype,
        wrap=True,
        column_widths=["40px", "150px"],
        interactive=True,
        static_columns=list(range(1, len(df.columns))),
        row_count=(len(df), "fixed"),
        col_count=(len(df.columns), "fixed"),
    )


def check_write_access_runs(request: gr.Request, write_token: str) -> bool:
    """Check if the user has write access based on token validation."""
    cookies = request.headers.get("cookie", "")
    if cookies:
        for cookie in cookies.split(";"):
            parts = cookie.strip().split("=")
            if len(parts) == 2 and parts[0] == "trackio_write_token":
                return parts[1] == write_token
    if hasattr(request, "query_params") and request.query_params:
        token = request.query_params.get("write_token")
        return token == write_token
    return False


def update_delete_button(runs_data, request: gr.Request):
    """Update the delete button value and interactivity based on the runs data and user write access."""
    if not check_write_access_runs(request, run_page.write_token):
        return gr.Button("⚠️ Need write access to delete runs", interactive=False)

    num_selected = 0
    if runs_data is not None and len(runs_data) > 0:
        first_column_values = runs_data.iloc[:, 0].tolist()
        num_selected = sum(1 for x in first_column_values if x)

    if num_selected:
        return gr.Button(f"Delete {num_selected} selected run(s)", interactive=True)
    else:
        return gr.Button("Select runs to delete", interactive=False)


def delete_selected_runs(runs_data, project, request: gr.Request):
    """Delete the selected runs and refresh the table."""
    if not check_write_access_runs(request, run_page.write_token):
        return runs_data

    first_column_values = runs_data.iloc[:, 0].tolist()
    for i, selected in enumerate(first_column_values):
        if selected:
            run_name_raw = runs_data.iloc[i, 1]
            match = re.search(r">([^<]+)<", run_name_raw)
            run_name = match.group(1) if match else run_name_raw
            SQLiteStorage.delete_run(project, run_name)

    updated_data = get_runs_data(project)
    return updated_data


with gr.Blocks() as run_page:
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
        with gr.Column():
            pass
        with gr.Column():
            with gr.Row():
                delete_run_btn = gr.Button(
                    "⚠️ Need write access to delete runs",
                    interactive=False,
                    variant="stop",
                    size="sm",
                )
                confirm_btn = gr.Button(
                    "Confirm delete", variant="stop", size="sm", visible=False
                )
                cancel_btn = gr.Button("Cancel", size="sm", visible=False)

    runs_table = gr.DataFrame()

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
        [run_page.load, runs_table.change],
        fn=update_delete_button,
        inputs=[runs_table],
        outputs=[delete_run_btn],
        show_progress="hidden",
        api_name=False,
        queue=False,
    )

    gr.on(
        [delete_run_btn.click],
        fn=lambda: [
            gr.Button(visible=False),
            gr.Button(visible=True),
            gr.Button(visible=True),
        ],
        inputs=None,
        outputs=[delete_run_btn, confirm_btn, cancel_btn],
        show_progress="hidden",
        api_name=False,
        queue=False,
    )
    gr.on(
        [confirm_btn.click, cancel_btn.click],
        fn=lambda: [
            gr.Button(visible=True),
            gr.Button(visible=False),
            gr.Button(visible=False),
        ],
        inputs=None,
        outputs=[delete_run_btn, confirm_btn, cancel_btn],
        show_progress="hidden",
        api_name=False,
        queue=False,
    )
    gr.on(
        [confirm_btn.click],
        fn=delete_selected_runs,
        inputs=[runs_table, project_dd],
        outputs=[runs_table],
        show_progress="hidden",
        api_name=False,
        queue=False,
    )
