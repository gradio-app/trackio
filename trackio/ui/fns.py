"""Shared functions for the Trackio UI."""

import os

import gradio as gr

try:
    import trackio.utils as utils
    from trackio.sqlite_storage import SQLiteStorage
except ImportError:
    import utils
    from sqlite_storage import SQLiteStorage


def get_project_info() -> str | None:
    dataset_id = os.environ.get("TRACKIO_DATASET_ID")
    space_id = os.environ.get("SPACE_ID")
    if utils.persistent_storage_enabled():
        return "&#10024; Persistent Storage is enabled, logs are stored directly in this Space."
    if dataset_id:
        sync_status = utils.get_sync_status(SQLiteStorage.get_scheduler())
        upgrade_message = f"New changes are synced every 5 min <span class='info-container'><input type='checkbox' class='info-checkbox' id='upgrade-info'><label for='upgrade-info' class='info-icon'>&#9432;</label><span class='info-expandable'> To avoid losing data between syncs, <a href='https://huggingface.co/spaces/{space_id}/settings' class='accent-link'>click here</a> to open this Space's settings and add Persistent Storage. Make sure data is synced prior to enabling.</span></span>"
        if sync_status is not None:
            info = f"&#x21bb; Backed up {sync_status} min ago to <a href='https://huggingface.co/datasets/{dataset_id}' target='_blank' class='accent-link'>{dataset_id}</a> | {upgrade_message}"
        else:
            info = f"&#x21bb; Not backed up yet to <a href='https://huggingface.co/datasets/{dataset_id}' target='_blank' class='accent-link'>{dataset_id}</a> | {upgrade_message}"
        return info
    return None


def get_projects(request: gr.Request):
    projects = SQLiteStorage.get_projects()
    if project := request.query_params.get("project"):
        interactive = False
    else:
        interactive = True
        if selected_project := request.query_params.get("selected_project"):
            project = selected_project
        else:
            project = projects[0] if projects else None

    return gr.Dropdown(
        label="Project",
        choices=projects,
        value=project,
        allow_custom_value=True,
        interactive=interactive,
        info=get_project_info(),
    )


def update_navbar_value(project_dd):
    return gr.Navbar(
        value=[
            ("Metrics", f"?selected_project={project_dd}"),
            ("Runs", f"runs?selected_project={project_dd}"),
        ]
    )
