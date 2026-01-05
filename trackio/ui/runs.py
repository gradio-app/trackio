"""The Runs page for the Trackio UI."""

import gradio as gr

import trackio.utils as utils
from trackio.sqlite_storage import SQLiteStorage
from trackio.ui import fns
from trackio.ui.components.runs_table import RunsTable


def get_runs_data(project):
    """Get the runs data as headers, rows, and run names list."""
    if not project:
        return [], [], []
    configs = SQLiteStorage.get_all_run_configs(project)
    if not configs:
        return [], [], []

    run_names = list(configs.keys())

    headers = set()
    for config in configs.values():
        headers.update(config.keys())
    headers = list(headers)

    header_mapping = {v: k for k, v in fns.CONFIG_COLUMN_MAPPINGS.items()}
    headers = [fns.CONFIG_COLUMN_MAPPINGS.get(h, h) for h in headers]

    if "Name" not in headers:
        headers.append("Name")

    priority_order = ["Name", "Group", "Username", "Created"]
    ordered_headers = []
    for col in priority_order:
        if col in headers:
            ordered_headers.append(col)
            headers.remove(col)
    ordered_headers.extend(sorted(headers))
    headers = ordered_headers

    rows = []
    for run_name, config in configs.items():
        row = []
        for header in headers:
            original_key = header_mapping.get(header, header)
            cell_value = config.get(original_key, config.get(header, ""))
            if cell_value is None:
                cell_value = ""

            if header == "Name":
                cell_value = f"<a href='/run?selected_project={project}&selected_run={run_name}'>{run_name}</a>"
            elif header == "Username" and cell_value and cell_value != "None":
                cell_value = f"<a href='https://huggingface.co/{cell_value}' target='_blank' rel='noopener noreferrer'>{cell_value}</a>"
            elif header == "Created" and cell_value:
                cell_value = utils.format_timestamp(cell_value)
            else:
                cell_value = str(cell_value)

            row.append(cell_value)
        rows.append(row)

    return headers, rows, run_names


def get_runs_table(project, interactive=True):
    headers, rows, run_names = get_runs_data(project)
    if not rows:
        return RunsTable(headers=[], rows=[], value=[], interactive=False), []

    return RunsTable(
        headers=headers,
        rows=rows,
        value=[],
        interactive=interactive,
    ), run_names


def check_write_access_runs(request: gr.Request, write_token: str) -> bool:
    """
    Check if the user has write access to the Trackio dashboard based on token validation.
    The token is retrieved from the cookie in the request headers or, as fallback, from the
    `write_token` query parameter.
    """
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


def set_deletion_allowed(
    project, request: gr.Request, oauth_token: gr.OAuthToken | None
):
    """Update the delete button value and interactivity based on the runs data and user write access."""
    if oauth_token:
        try:
            fns.check_oauth_token_has_write_access(oauth_token.token)
        except PermissionError:
            table, run_names = get_runs_table(project, interactive=False)
            return (
                gr.Button("⚠️ Need write access to delete runs", interactive=False),
                table,
                run_names,
                False,
            )
    elif not check_write_access_runs(request, run_page.write_token):
        table, run_names = get_runs_table(project, interactive=False)
        return (
            gr.Button("⚠️ Need write access to delete runs", interactive=False),
            table,
            run_names,
            False,
        )
    table, run_names = get_runs_table(project, interactive=True)
    return (
        gr.Button("Select runs to delete", interactive=False),
        table,
        run_names,
        True,
    )


def update_delete_button(deletion_allowed, selected_indices):
    """Update the delete button value and interactivity based on the selected runs."""
    if not deletion_allowed:
        return gr.Button(interactive=False)

    num_selected = len(selected_indices) if selected_indices else 0

    if num_selected:
        return gr.Button(f"Delete {num_selected} selected run(s)", interactive=True)
    else:
        return gr.Button("Select runs to delete", interactive=False)


def delete_selected_runs(deletion_allowed, selected_indices, run_names_list, project):
    """Delete the selected runs and refresh the table."""
    if not deletion_allowed or not selected_indices:
        return get_runs_table(project, interactive=True)

    for idx in selected_indices:
        if 0 <= idx < len(run_names_list):
            run_name = run_names_list[idx]
            SQLiteStorage.delete_run(project, run_name)

    return get_runs_table(project, interactive=True)


with gr.Blocks() as run_page:
    with gr.Sidebar() as sidebar:
        logo = fns.create_logo()
        project_dd = fns.create_project_dropdown()

    navbar = fns.create_navbar()
    timer = gr.Timer(value=1)
    allow_deleting_runs = gr.State(False)
    run_names_state = gr.State([])

    with gr.Row():
        with gr.Column():
            if utils.get_space():
                gr.LoginButton("Login to delete runs", size="md")
        with gr.Column():
            with gr.Row():
                delete_run_btn = gr.Button(
                    "⚠️ Need write access to delete runs",
                    interactive=False,
                    variant="stop",
                    size="md",
                )
                confirm_btn = gr.Button(
                    "Confirm delete", variant="stop", size="md", visible=False
                )
                cancel_btn = gr.Button("Cancel", size="md", visible=False)

    runs_table = RunsTable(headers=[], rows=[], value=[])

    gr.on(
        [run_page.load],
        fn=fns.get_projects,
        outputs=project_dd,
        show_progress="hidden",
        queue=False,
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
        [project_dd.change],
        fn=get_runs_table,
        inputs=[project_dd],
        outputs=[runs_table, run_names_state],
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
    )

    gr.on(
        [run_page.load],
        fn=set_deletion_allowed,
        inputs=[project_dd],
        outputs=[delete_run_btn, runs_table, run_names_state, allow_deleting_runs],
        show_progress="hidden",
        api_visibility="private",
        queue=False,
    )
    gr.on(
        [runs_table.input],
        fn=update_delete_button,
        inputs=[allow_deleting_runs, runs_table],
        outputs=[delete_run_btn],
        show_progress="hidden",
        api_visibility="private",
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
        api_visibility="private",
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
        api_visibility="private",
        queue=False,
    )
    gr.on(
        [confirm_btn.click],
        fn=delete_selected_runs,
        inputs=[allow_deleting_runs, runs_table, run_names_state, project_dd],
        outputs=[runs_table, run_names_state],
        show_progress="hidden",
        api_visibility="private",
        queue=False,
    )
