"""Shared functions for the Trackio UI."""

import os

import gradio as gr
import huggingface_hub as hf

try:
    import trackio.utils as utils
    from trackio.sqlite_storage import SQLiteStorage
except ImportError:
    import utils
    from sqlite_storage import SQLiteStorage


HfApi = hf.HfApi()


def get_project_info() -> str | None:
    dataset_id = os.environ.get("TRACKIO_DATASET_ID")
    space_id = utils.get_space()
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


def check_token_has_write_access(hf_token: str | None) -> None:
    """
    Checks to see if the provided hf_token is valid and has write access to the Space
    that Trackio is running in. If the hf_token is valid or if Trackio is not running
    on a Space, this function does nothing. Otherwise, it raises a PermissionError.
    """
    if os.getenv("SYSTEM") == "spaces":  # if we are running in Spaces
        # check auth token passed in
        if hf_token is None:
            raise PermissionError(
                "Expected a HF_TOKEN to be provided when logging to a Space"
            )
        who = HfApi.whoami(hf_token)
        access_token = who["auth"]["accessToken"]
        owner_name = os.getenv("SPACE_AUTHOR_NAME")
        repo_name = os.getenv("SPACE_REPO_NAME")
        # make sure the token user is either the author of the space,
        # or is a member of an org that is the author.
        orgs = [o["name"] for o in who["orgs"]]
        if owner_name != who["name"] and owner_name not in orgs:
            raise PermissionError(
                "Expected the provided hf_token to be the user owner of the space, or be a member of the org owner of the space"
            )
        # reject fine-grained tokens without specific repo access
        if access_token["role"] == "fineGrained":
            matched = False
            for item in access_token["fineGrained"]["scoped"]:
                if (
                    item["entity"]["type"] == "space"
                    and item["entity"]["name"] == f"{owner_name}/{repo_name}"
                    and "repo.write" in item["permissions"]
                ):
                    matched = True
                    break
                if (
                    (
                        item["entity"]["type"] == "user"
                        or item["entity"]["type"] == "org"
                    )
                    and item["entity"]["name"] == owner_name
                    and "repo.write" in item["permissions"]
                ):
                    matched = True
                    break
            if not matched:
                raise PermissionError(
                    "Expected the provided hf_token with fine grained permissions to provide write access to the space"
                )
        # reject read-only tokens
        elif access_token["role"] != "write":
            raise PermissionError(
                "Expected the provided hf_token to provide write permissions"
            )


def check_oauth_token_has_write_access(oauth_token: str | None) -> None:
    """
    Checks to see if the provided oauth_token is valid and has write access to the Space
    that Trackio is running in. If the oauth_token is valid or if Trackio is not running
    on a Space, this function does nothing. Otherwise, it raises a PermissionError.
    """
    if os.getenv("SYSTEM") == "spaces":  # if we are running in Spaces
        # check auth token passed in
        if oauth_token is None:
            raise PermissionError(
                "Expected an oauth to be provided when logging to a Space"
            )
