"""The Runs page for the Trackio UI."""

import gradio as gr

import trackio.utils as utils
from trackio.sqlite_storage import SQLiteStorage
from trackio.ui import fns
from trackio.ui.components.runs_table import RunsTable


def get_runs_data(project: str) -> tuple[list[str], list[list[str]], list[str]]:
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


def get_runs_table(
    project: str, interactive: bool = True
) -> tuple[RunsTable, list[str]]:
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
    project: str, request: gr.Request, oauth_token: gr.OAuthToken | None
) -> tuple[gr.Button, gr.Button, RunsTable, list[str], bool]:
    """Update the delete and rename buttons based on the runs data and user write access."""
    if oauth_token:
        try:
            fns.check_oauth_token_has_write_access(oauth_token.token)
        except PermissionError:
            table, run_names = get_runs_table(project, interactive=False)
            return (
                gr.Button("⚠️ Need write access to rename runs", interactive=False),
                gr.Button("⚠️ Need write access to delete runs", interactive=False),
                table,
                run_names,
                False,
            )
    elif not check_write_access_runs(request, run_page.write_token):
        table, run_names = get_runs_table(project, interactive=False)
        return (
            gr.Button("⚠️ Need write access to rename runs", interactive=False),
            gr.Button("⚠️ Need write access to delete runs", interactive=False),
            table,
            run_names,
            False,
        )
    table, run_names = get_runs_table(project, interactive=True)
    return (
        gr.Button("Rename", interactive=False),
        gr.Button("Delete", interactive=False),
        table,
        run_names,
        True,
    )


def update_delete_button(
    deletion_allowed: bool, selected_indices: list[int]
) -> gr.Button:
    """Update the delete button value and interactivity based on the selected runs."""
    if not deletion_allowed:
        return gr.Button(interactive=False)

    num_selected = len(selected_indices) if selected_indices else 0

    if num_selected:
        return gr.Button(f"Delete ({num_selected})", interactive=True)
    else:
        return gr.Button("Delete", interactive=False)


def update_rename_button(
    deletion_allowed: bool, selected_indices: list[int]
) -> gr.Button:
    """Update the rename button value and interactivity based on the selected runs."""
    if not deletion_allowed:
        return gr.Button(interactive=False)

    num_selected = len(selected_indices) if selected_indices else 0

    if num_selected == 1:
        return gr.Button("Rename", interactive=True)
    else:
        return gr.Button("Rename", interactive=False)


def delete_selected_runs(
    deletion_allowed: bool,
    selected_indices: list[int],
    run_names_list: list[str],
    project: str,
) -> tuple[RunsTable, list[str]]:
    """Delete the selected runs and refresh the table."""
    if not deletion_allowed or not selected_indices:
        return get_runs_table(project, interactive=True)

    for idx in selected_indices:
        if 0 <= idx < len(run_names_list):
            run_name = run_names_list[idx]
            SQLiteStorage.delete_run(project, run_name)

    return get_runs_table(project, interactive=True)


def rename_selected_run(
    deletion_allowed: bool,
    selected_indices: list[int],
    run_names_list: list[str],
    project: str,
    new_name: str,
) -> tuple[RunsTable, list[str]]:
    """Rename the selected run and refresh the table."""
    if not deletion_allowed or not selected_indices or len(selected_indices) != 1:
        gr.Info("Please select exactly one run to rename")
        return get_runs_table(project, interactive=True)

    if not new_name or not new_name.strip():
        gr.Info("New name cannot be empty")
        return get_runs_table(project, interactive=True)

    new_name = new_name.strip()
    idx = selected_indices[0]

    if 0 <= idx < len(run_names_list):
        old_name = run_names_list[idx]

        if old_name == new_name:
            gr.Info("New name must be different from the current name")
            return get_runs_table(project, interactive=True)

        if new_name in run_names_list:
            gr.Info(f"A run named '{new_name}' already exists")
            return get_runs_table(project, interactive=True)

        success = SQLiteStorage.rename_run(project, old_name, new_name)
        if success:
            gr.Info(f"Successfully renamed '{old_name}' to '{new_name}'")
            return get_runs_table(project, interactive=True)
        else:
            gr.Info("Failed to rename run")
            return get_runs_table(project, interactive=True)

    gr.Info("Invalid run selection")
    return get_runs_table(project, interactive=True)


def show_delete_confirmation(
    selected_indices: list[int], run_names_list: list[str], project: str
) -> tuple[gr.Button, gr.Button, gr.Button, gr.Button, gr.Column, gr.Markdown, dict]:
    """Show delete confirmation with warning message."""
    if not selected_indices or not run_names_list:
        return (
            gr.Button(visible=False),
            gr.Button(visible=True),
            gr.Button(visible=True),
            gr.Button(visible=False),
            gr.Column(visible=False),
            gr.Markdown("", visible=False),
            gr.update(interactive=False),
        )

    selected_runs = [
        run_names_list[idx]
        for idx in selected_indices
        if 0 <= idx < len(run_names_list)
    ]

    if len(selected_runs) > 1:
        runs_list = "<br/>".join([f"- `{run}`" for run in selected_runs])
        warning_msg = f"**Warning**<br/> Are you sure you want to delete the following runs ({len(selected_runs)})?<br/> {runs_list}"
    else:
        warning_msg = f"**Warning**<br/> Are you sure you want to delete the following run?<br/> - `{selected_runs[0]}`"

    return (
        gr.Button(visible=False),
        gr.Button(visible=True),
        gr.Button(visible=True),
        gr.Button(visible=False),
        gr.Column(visible=False),
        gr.Markdown(warning_msg, visible=True),
        gr.update(interactive=False),
    )


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
                gr.LoginButton("Login to delete or rename runs", size="md")
        with gr.Column(scale=2):
            gr.Markdown("")
        with gr.Column():
            with gr.Row():
                rename_run_btn = gr.Button(
                    "⚠️ Need write access to rename runs",
                    interactive=False,
                    size="sm",
                )
                delete_run_btn = gr.Button(
                    "⚠️ Need write access to delete runs",
                    interactive=False,
                    variant="stop",
                    size="sm",
                )
            delete_warning = gr.Markdown("", visible=False)
            with gr.Row():
                cancel_delete_btn = gr.Button("Cancel", size="sm", visible=False)
                confirm_delete_btn = gr.Button(
                    "Delete", variant="stop", size="sm", visible=False
                )
            with gr.Column(visible=False) as rename_controls:
                rename_input = gr.Textbox(
                    label="New Name",
                    placeholder="New name",
                )
                rename_info = gr.Markdown(
                    "**Warning**: Ensure the run is complete before renaming.",
                    visible=False,
                )
                with gr.Row():
                    cancel_rename_btn = gr.Button(
                        "Cancel", size="sm", variant="secondary"
                    )
                    confirm_rename_btn = gr.Button(
                        "Rename", size="sm", variant="primary"
                    )

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
        outputs=[
            rename_run_btn,
            delete_run_btn,
            runs_table,
            run_names_state,
            allow_deleting_runs,
        ],
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
        [runs_table.input],
        fn=update_rename_button,
        inputs=[allow_deleting_runs, runs_table],
        outputs=[rename_run_btn],
        show_progress="hidden",
        api_visibility="private",
        queue=False,
    )
    gr.on(
        [delete_run_btn.click],
        fn=show_delete_confirmation,
        inputs=[runs_table, run_names_state, project_dd],
        outputs=[
            delete_run_btn,
            confirm_delete_btn,
            cancel_delete_btn,
            rename_run_btn,
            rename_controls,
            delete_warning,
            runs_table,
        ],
        show_progress="hidden",
        api_visibility="private",
        queue=False,
    )

    def hide_delete_confirmation() -> tuple[
        gr.Button, gr.Button, gr.Button, gr.Button, gr.Column, gr.Markdown, dict
    ]:
        """Hide delete confirmation and restore interactive table."""
        return (
            gr.Button(visible=True),
            gr.Button(visible=False),
            gr.Button(visible=False),
            gr.Button(visible=True),
            gr.Column(visible=False),
            gr.Markdown("", visible=False),
            gr.update(interactive=True),
        )

    gr.on(
        [confirm_delete_btn.click, cancel_delete_btn.click],
        fn=hide_delete_confirmation,
        inputs=None,
        outputs=[
            delete_run_btn,
            confirm_delete_btn,
            cancel_delete_btn,
            rename_run_btn,
            rename_controls,
            delete_warning,
            runs_table,
        ],
        show_progress="hidden",
        api_visibility="private",
        queue=False,
    )
    gr.on(
        [confirm_delete_btn.click],
        fn=delete_selected_runs,
        inputs=[allow_deleting_runs, runs_table, run_names_state, project_dd],
        outputs=[runs_table, run_names_state],
        show_progress="hidden",
        api_visibility="private",
        queue=False,
    ).then(
        fn=update_delete_button,
        inputs=[allow_deleting_runs, runs_table],
        outputs=[delete_run_btn],
        show_progress="hidden",
        api_visibility="private",
        queue=False,
    )

    def show_rename_controls(
        selected_indices: list[int], run_names_list: list[str], project: str
    ) -> tuple[
        gr.Button,
        gr.Row,
        gr.Markdown,
        gr.Textbox,
        gr.Button,
        gr.Button,
        gr.Button,
        dict,
    ]:
        """Show rename controls and prefill with current run name."""
        if selected_indices and len(selected_indices) == 1:
            idx = selected_indices[0]
            if 0 <= idx < len(run_names_list):
                current_name = run_names_list[idx]
                return (
                    gr.Button(visible=False),
                    gr.Row(visible=True),
                    gr.Markdown(visible=True),
                    gr.Textbox(value=current_name),
                    gr.Button(visible=False),
                    gr.Button(visible=False),
                    gr.Button(visible=False),
                    gr.update(interactive=False),
                )
        return (
            gr.Button(visible=False),
            gr.Row(visible=True),
            gr.Markdown(visible=True),
            gr.Textbox(value=""),
            gr.Button(visible=False),
            gr.Button(visible=False),
            gr.Button(visible=False),
            gr.update(interactive=False),
        )

    def hide_rename_controls() -> tuple[
        gr.Button,
        gr.Row,
        gr.Markdown,
        gr.Textbox,
        gr.Button,
        gr.Button,
        gr.Button,
        dict,
    ]:
        """Hide rename controls and show main rename button."""
        return (
            gr.Button(visible=True),
            gr.Row(visible=False),
            gr.Markdown(visible=False),
            gr.Textbox(value=""),
            gr.Button(visible=True),
            gr.Button(visible=False),
            gr.Button(visible=False),
            gr.update(interactive=True),
        )

    gr.on(
        [rename_run_btn.click],
        fn=show_rename_controls,
        inputs=[runs_table, run_names_state, project_dd],
        outputs=[
            rename_run_btn,
            rename_controls,
            rename_info,
            rename_input,
            delete_run_btn,
            confirm_delete_btn,
            cancel_delete_btn,
            runs_table,
        ],
        show_progress="hidden",
        api_visibility="private",
        queue=False,
    )
    gr.on(
        [cancel_rename_btn.click],
        fn=hide_rename_controls,
        inputs=None,
        outputs=[
            rename_run_btn,
            rename_controls,
            rename_info,
            rename_input,
            delete_run_btn,
            confirm_delete_btn,
            cancel_delete_btn,
            runs_table,
        ],
        show_progress="hidden",
        api_visibility="private",
        queue=False,
    )
    gr.on(
        [confirm_rename_btn.click],
        fn=rename_selected_run,
        inputs=[
            allow_deleting_runs,
            runs_table,
            run_names_state,
            project_dd,
            rename_input,
        ],
        outputs=[runs_table, run_names_state],
        show_progress="hidden",
        api_visibility="private",
        queue=False,
    ).then(
        fn=hide_rename_controls,
        inputs=None,
        outputs=[
            rename_run_btn,
            rename_controls,
            rename_info,
            rename_input,
            delete_run_btn,
            confirm_delete_btn,
            cancel_delete_btn,
            runs_table,
        ],
        show_progress="hidden",
        api_visibility="private",
        queue=False,
    ).then(
        fn=update_rename_button,
        inputs=[allow_deleting_runs, runs_table],
        outputs=[rename_run_btn],
        show_progress="hidden",
        api_visibility="private",
        queue=False,
    )

    gr.api(fn=get_runs_data, api_name="get_runs_data")
