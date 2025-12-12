"""Shared functions for the Trackio UI."""

import os
from functools import lru_cache

import gradio as gr
import huggingface_hub as hf

try:
    import trackio.utils as utils
    from trackio.sqlite_storage import SQLiteStorage
    from trackio.ui.components.colored_checkbox import ColoredCheckboxGroup
    from trackio.ui.helpers.run_selection import RunSelection
except ImportError:
    import utils
    from sqlite_storage import SQLiteStorage
    from ui.components.colored_checkbox import ColoredCheckboxGroup
    from ui.helpers.run_selection import RunSelection

CONFIG_COLUMN_MAPPINGS = {
    "_Username": "Username",
    "_Created": "Created",
    "_Group": "Group",
}
CONFIG_COLUMN_MAPPINGS_REVERSE = {v: k for k, v in CONFIG_COLUMN_MAPPINGS.items()}


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


def update_navbar_value(project_dd, request: gr.Request):
    write_token = None
    if hasattr(request, "query_params") and request.query_params:
        write_token = request.query_params.get("write_token")

    metrics_url = f"?selected_project={project_dd}"
    media_url = f"media?selected_project={project_dd}"
    runs_url = f"runs?selected_project={project_dd}"
    files_url = f"files?selected_project={project_dd}"

    if write_token:
        metrics_url += f"&write_token={write_token}"
        media_url += f"&write_token={write_token}"
        runs_url += f"&write_token={write_token}"
        files_url += f"&write_token={write_token}"

    return gr.Navbar(
        value=[
            ("Metrics", metrics_url),
            ("Media & Tables", media_url),
            ("Runs", runs_url),
            ("Files", files_url),
        ]
    )


@lru_cache(maxsize=32)
def check_hf_token_has_write_access(hf_token: str | None) -> None:
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
        access_token = who["auth"]["accessToken"]
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


@lru_cache(maxsize=32)
def check_oauth_token_has_write_access(oauth_token: str | None) -> None:
    """
    Checks to see if the oauth token provided via Gradio's OAuth is valid and has write access
    to the Space that Trackio is running in. If the oauth token is valid or if Trackio is not running
    on a Space, this function does nothing. Otherwise, it raises a PermissionError.
    """
    if not os.getenv("SYSTEM") == "spaces":
        return
    if oauth_token is None:
        raise PermissionError(
            "Expected an oauth to be provided when logging to a Space"
        )
    who = HfApi.whoami(oauth_token)
    user_name = who["name"]
    owner_name = os.getenv("SPACE_AUTHOR_NAME")
    if user_name == owner_name:
        return
    # check if user is a member of an org that owns the space with write permissions
    for org in who["orgs"]:
        if org["name"] == owner_name and org["roleInOrg"] == "write":
            return
    raise PermissionError(
        "Expected the oauth token to be the user owner of the space, or be a member of the org owner of the space"
    )


def get_group_by_fields(project: str):
    configs = SQLiteStorage.get_all_run_configs(project) if project else {}
    keys = set()
    for config in configs.values():
        keys.update(config.keys())
    keys.discard("_Created")
    keys = [CONFIG_COLUMN_MAPPINGS.get(key, key) for key in keys]
    choices = [None] + sorted(keys)
    return gr.Dropdown(
        choices=choices,
        value=None,
        interactive=True,
    )


def group_runs_by_config(
    project: str, config_key: str, filter_text: str | None = None
) -> dict[str, list[str]]:
    if not project or not config_key:
        return {}
    display_key = config_key
    config_key = CONFIG_COLUMN_MAPPINGS_REVERSE.get(config_key, config_key)
    configs = SQLiteStorage.get_all_run_configs(project)
    groups: dict[str, list[str]] = {}
    for run_name, config in configs.items():
        if filter_text and filter_text not in run_name:
            continue
        group_name = config.get(config_key, "None")
        label = f"{display_key}: {group_name}"
        groups.setdefault(label, []).append(run_name)
    for label in groups:
        groups[label].sort()
    sorted_groups = dict(sorted(groups.items(), key=lambda kv: kv[0].lower()))
    return sorted_groups


def run_checkbox_update(selection: RunSelection, **kwargs) -> gr.CheckboxGroup:
    color_palette = utils.get_color_palette()
    return ColoredCheckboxGroup(
        choices=selection.choices,
        value=selection.selected,
        colors=[
            color_palette[i % len(color_palette)] for i in range(len(selection.choices))
        ],
        label=f"Runs ({len(selection.choices)})",
        **kwargs,
    )


def handle_run_checkbox_change(
    selected_runs: list[str] | None, selection: RunSelection
) -> RunSelection:
    selection.select(selected_runs or [])
    return selection


def group_checkbox_update(
    group_runs: list[str], selection: RunSelection
) -> ColoredCheckboxGroup:
    color_palette = utils.get_color_palette()
    choice_indices = {run: i for i, run in enumerate(selection.choices)}
    colors = [
        color_palette[choice_indices.get(run, 0) % len(color_palette)]
        for run in group_runs
    ]
    subset = utils.ordered_subset(group_runs, selection.selected)
    return ColoredCheckboxGroup(
        choices=group_runs,
        value=subset,
        colors=colors,
        label=f"Runs ({len(group_runs)})",
    )


def handle_group_checkbox_change(
    group_selected: list[str] | None,
    selection: RunSelection,
    group_runs: list[str] | None,
):
    selection.replace_group(group_runs or [], group_selected or [])
    return (
        selection,
        group_checkbox_update(group_runs or [], selection),
        run_checkbox_update(selection),
    )


def handle_group_toggle(
    select_all: bool,
    selection: RunSelection,
    group_runs: list[str] | None,
):
    target = list(group_runs or []) if select_all else []
    selection.replace_group(group_runs or [], target)
    return (
        selection,
        group_checkbox_update(group_runs or [], selection),
        run_checkbox_update(selection),
    )
