import importlib.metadata
import io
import os
import sys
import threading
import time
from importlib.resources import files
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

import gradio
import huggingface_hub
from gradio_client import Client, handle_file
from httpx import ReadTimeout
from huggingface_hub.errors import HfHubHTTPError, RepositoryNotFoundError

import trackio
from trackio.sqlite_storage import SQLiteStorage
from trackio.utils import get_or_create_project_hash, preprocess_space_and_dataset_ids

SPACE_HOST_URL = "https://{user_name}-{space_name}.hf.space/"
SPACE_URL = "https://huggingface.co/spaces/{space_id}"


def _get_source_install_dependencies() -> str:
    """Get trackio dependencies from pyproject.toml for source installs."""
    trackio_path = files("trackio")
    pyproject_path = Path(trackio_path).parent / "pyproject.toml"
    with open(pyproject_path, "rb") as f:
        pyproject = tomllib.load(f)
    deps = pyproject["project"]["dependencies"]
    spaces_deps = (
        pyproject["project"].get("optional-dependencies", {}).get("spaces", [])
    )
    return "\n".join(deps + spaces_deps)


def _is_trackio_installed_from_source() -> bool:
    """Check if trackio is installed from source/editable install vs PyPI."""
    try:
        trackio_file = trackio.__file__
        if "site-packages" not in trackio_file and "dist-packages" not in trackio_file:
            return True

        dist = importlib.metadata.distribution("trackio")
        if dist.files:
            files = list(dist.files)
            has_pth = any(".pth" in str(f) for f in files)
            if has_pth:
                return True

        return False
    except (
        AttributeError,
        importlib.metadata.PackageNotFoundError,
        importlib.metadata.MetadataError,
        ValueError,
        TypeError,
    ):
        return True


def deploy_as_space(
    space_id: str,
    space_storage: huggingface_hub.SpaceStorage | None = None,
    dataset_id: str | None = None,
    private: bool | None = None,
):
    if (
        os.getenv("SYSTEM") == "spaces"
    ):  # in case a repo with this function is uploaded to spaces
        return

    trackio_path = files("trackio")

    hf_api = huggingface_hub.HfApi()

    try:
        huggingface_hub.create_repo(
            space_id,
            private=private,
            space_sdk="gradio",
            space_storage=space_storage,
            repo_type="space",
            exist_ok=True,
        )
    except HfHubHTTPError as e:
        if e.response.status_code in [401, 403]:  # unauthorized or forbidden
            print("Need 'write' access token to create a Spaces repo.")
            huggingface_hub.login(add_to_git_credential=False)
            huggingface_hub.create_repo(
                space_id,
                private=private,
                space_sdk="gradio",
                space_storage=space_storage,
                repo_type="space",
                exist_ok=True,
            )
        else:
            raise ValueError(f"Failed to create Space: {e}")

    # We can assume pandas, gradio, and huggingface-hub are already installed in a Gradio Space.
    # Make sure necessary dependencies are installed by creating a requirements.txt.
    is_source_install = _is_trackio_installed_from_source()

    with open(Path(trackio_path, "README.md"), "r") as f:
        readme_content = f.read()
        readme_content = readme_content.replace("{GRADIO_VERSION}", gradio.__version__)
        if is_source_install:
            readme_content = readme_content.replace("{APP_FILE}", "trackio/ui/main.py")
        else:
            readme_content = readme_content.replace("{APP_FILE}", "app.py")
        readme_buffer = io.BytesIO(readme_content.encode("utf-8"))
        hf_api.upload_file(
            path_or_fileobj=readme_buffer,
            path_in_repo="README.md",
            repo_id=space_id,
            repo_type="space",
        )

    if is_source_install:
        requirements_content = _get_source_install_dependencies()
    else:
        requirements_content = f"trackio[spaces]=={trackio.__version__}"

    requirements_buffer = io.BytesIO(requirements_content.encode("utf-8"))
    hf_api.upload_file(
        path_or_fileobj=requirements_buffer,
        path_in_repo="requirements.txt",
        repo_id=space_id,
        repo_type="space",
    )

    huggingface_hub.utils.disable_progress_bars()

    if is_source_install:
        hf_api.upload_folder(
            repo_id=space_id,
            repo_type="space",
            folder_path=trackio_path,
            path_in_repo="trackio",
            ignore_patterns=["README.md"],
        )

    app_file_content = """import trackio
trackio.show()"""
    app_file_buffer = io.BytesIO(app_file_content.encode("utf-8"))
    hf_api.upload_file(
        path_or_fileobj=app_file_buffer,
        path_in_repo="app.py",
        repo_id=space_id,
        repo_type="space",
    )

    if hf_token := huggingface_hub.utils.get_token():
        huggingface_hub.add_space_secret(space_id, "HF_TOKEN", hf_token)
    if dataset_id is not None:
        huggingface_hub.add_space_variable(space_id, "TRACKIO_DATASET_ID", dataset_id)
    if logo_light_url := os.environ.get("TRACKIO_LOGO_LIGHT_URL"):
        huggingface_hub.add_space_variable(
            space_id, "TRACKIO_LOGO_LIGHT_URL", logo_light_url
        )
    if logo_dark_url := os.environ.get("TRACKIO_LOGO_DARK_URL"):
        huggingface_hub.add_space_variable(
            space_id, "TRACKIO_LOGO_DARK_URL", logo_dark_url
        )
    if plot_order := os.environ.get("TRACKIO_PLOT_ORDER"):
        huggingface_hub.add_space_variable(space_id, "TRACKIO_PLOT_ORDER", plot_order)
    if theme := os.environ.get("TRACKIO_THEME"):
        huggingface_hub.add_space_variable(space_id, "TRACKIO_THEME", theme)
    huggingface_hub.add_space_variable(space_id, "GRADIO_MCP_SERVER", "True")


def create_space_if_not_exists(
    space_id: str,
    space_storage: huggingface_hub.SpaceStorage | None = None,
    dataset_id: str | None = None,
    private: bool | None = None,
) -> None:
    """
    Creates a new Hugging Face Space if it does not exist.

    Args:
        space_id (`str`):
            The ID of the Space to create.
        space_storage ([`~huggingface_hub.SpaceStorage`], *optional*):
            Choice of persistent storage tier for the Space.
        dataset_id (`str`, *optional*):
            The ID of the Dataset to add to the Space as a space variable.
        private (`bool`, *optional*):
            Whether to make the Space private. If `None` (default), the repo will be
            public unless the organization's default is private. This value is ignored
            if the repo already exists.
    """
    if "/" not in space_id:
        raise ValueError(
            f"Invalid space ID: {space_id}. Must be in the format: username/reponame or orgname/reponame."
        )
    if dataset_id is not None and "/" not in dataset_id:
        raise ValueError(
            f"Invalid dataset ID: {dataset_id}. Must be in the format: username/datasetname or orgname/datasetname."
        )
    try:
        huggingface_hub.repo_info(space_id, repo_type="space")
        print(f"* Found existing space: {SPACE_URL.format(space_id=space_id)}")
        return
    except RepositoryNotFoundError:
        pass
    except HfHubHTTPError as e:
        if e.response.status_code in [401, 403]:  # unauthorized or forbidden
            print("Need 'write' access token to create a Spaces repo.")
            huggingface_hub.login(add_to_git_credential=False)
        else:
            raise ValueError(f"Failed to create Space: {e}")

    print(f"* Creating new space: {SPACE_URL.format(space_id=space_id)}")
    deploy_as_space(space_id, space_storage, dataset_id, private)


def wait_until_space_exists(
    space_id: str,
) -> None:
    """
    Blocks the current thread until the Space exists.

    Args:
        space_id (`str`):
            The ID of the Space to wait for.

    Raises:
        `TimeoutError`: If waiting for the Space takes longer than expected.
    """
    hf_api = huggingface_hub.HfApi()
    delay = 1
    for _ in range(30):
        try:
            hf_api.space_info(space_id)
            return
        except (huggingface_hub.utils.HfHubHTTPError, ReadTimeout):
            time.sleep(delay)
            delay = min(delay * 2, 60)
    raise TimeoutError("Waiting for space to exist took longer than expected")


def upload_db_to_space(project: str, space_id: str, force: bool = False) -> None:
    """
    Uploads the database of a local Trackio project to a Hugging Face Space.

    This uses the Gradio Client to upload since we do not want to trigger a new build of
    the Space, which would happen if we used `huggingface_hub.upload_file`.

    Args:
        project (`str`):
            The name of the project to upload.
        space_id (`str`):
            The ID of the Space to upload to.
        force (`bool`, *optional*, defaults to `False`):
            If `True`, overwrites the existing database without prompting. If `False`,
            prompts for confirmation.
    """
    db_path = SQLiteStorage.get_project_db_path(project)
    client = Client(space_id, verbose=False, httpx_kwargs={"timeout": 90})

    if not force:
        try:
            existing_projects = client.predict(api_name="/get_all_projects")
            if project in existing_projects:
                response = input(
                    f"Database for project '{project}' already exists on Space '{space_id}'. "
                    f"Overwrite it? (y/N): "
                )
                if response.lower() not in ["y", "yes"]:
                    print("* Upload cancelled.")
                    return
        except Exception as e:
            print(f"* Warning: Could not check if project exists on Space: {e}")
            print("* Proceeding with upload...")

    client.predict(
        api_name="/upload_db_to_space",
        project=project,
        uploaded_db=handle_file(db_path),
        hf_token=huggingface_hub.utils.get_token(),
    )


SYNC_BATCH_SIZE = 500


def sync_incremental(
    project: str,
    space_id: str,
    private: bool | None = None,
    pending_only: bool = False,
) -> None:
    """
    Syncs a local Trackio project to a Space via the bulk_log API endpoints
    instead of uploading the entire DB file. Supports incremental sync.

    Args:
        project: The name of the project to sync.
        space_id: The HF Space ID to sync to.
        private: Whether to make the Space private if creating.
        pending_only: If True, only sync rows tagged with space_id (pending data).
    """
    from gradio_client import handle_file as _handle_file

    print(
        f"* Syncing project '{project}' to: {SPACE_URL.format(space_id=space_id)} (please wait...)"
    )
    create_space_if_not_exists(space_id, private=private)
    wait_until_space_exists(space_id)

    client = Client(space_id, verbose=False, httpx_kwargs={"timeout": 90})
    hf_token = huggingface_hub.utils.get_token()

    if pending_only:
        pending_logs = SQLiteStorage.get_pending_logs(project)
        if pending_logs:
            logs = pending_logs["logs"]
            for i in range(0, len(logs), SYNC_BATCH_SIZE):
                batch = logs[i : i + SYNC_BATCH_SIZE]
                print(
                    f"  Syncing metrics: {min(i + SYNC_BATCH_SIZE, len(logs))}/{len(logs)}..."
                )
                client.predict(api_name="/bulk_log", logs=batch, hf_token=hf_token)
            SQLiteStorage.clear_pending_logs(project, pending_logs["ids"])

        pending_sys = SQLiteStorage.get_pending_system_logs(project)
        if pending_sys:
            logs = pending_sys["logs"]
            for i in range(0, len(logs), SYNC_BATCH_SIZE):
                batch = logs[i : i + SYNC_BATCH_SIZE]
                print(
                    f"  Syncing system metrics: {min(i + SYNC_BATCH_SIZE, len(logs))}/{len(logs)}..."
                )
                client.predict(
                    api_name="/bulk_log_system", logs=batch, hf_token=hf_token
                )
            SQLiteStorage.clear_pending_system_logs(project, pending_sys["ids"])

        pending_uploads = SQLiteStorage.get_pending_uploads(project)
        if pending_uploads:
            upload_entries = []
            for u in pending_uploads["uploads"]:
                fp = u["file_path"]
                if os.path.exists(fp):
                    upload_entries.append(
                        {
                            "project": u["project"],
                            "run": u["run"],
                            "step": u["step"],
                            "relative_path": u["relative_path"],
                            "uploaded_file": _handle_file(fp),
                        }
                    )
            if upload_entries:
                print(f"  Syncing {len(upload_entries)} media files...")
                client.predict(
                    api_name="/bulk_upload_media",
                    uploads=upload_entries,
                    hf_token=hf_token,
                )
            SQLiteStorage.clear_pending_uploads(project, pending_uploads["ids"])
    else:
        all_logs = SQLiteStorage.get_all_logs_for_sync(project)
        if all_logs:
            for i in range(0, len(all_logs), SYNC_BATCH_SIZE):
                batch = all_logs[i : i + SYNC_BATCH_SIZE]
                print(
                    f"  Syncing metrics: {min(i + SYNC_BATCH_SIZE, len(all_logs))}/{len(all_logs)}..."
                )
                client.predict(api_name="/bulk_log", logs=batch, hf_token=hf_token)

        all_sys_logs = SQLiteStorage.get_all_system_logs_for_sync(project)
        if all_sys_logs:
            for i in range(0, len(all_sys_logs), SYNC_BATCH_SIZE):
                batch = all_sys_logs[i : i + SYNC_BATCH_SIZE]
                print(
                    f"  Syncing system metrics: {min(i + SYNC_BATCH_SIZE, len(all_sys_logs))}/{len(all_sys_logs)}..."
                )
                client.predict(
                    api_name="/bulk_log_system", logs=batch, hf_token=hf_token
                )

        configs = SQLiteStorage.get_all_configs_for_sync(project)
        if configs:
            for run_name, config_dict in configs.items():
                SQLiteStorage.store_config(project, run_name, config_dict)

    SQLiteStorage.set_project_metadata(project, "space_id", space_id)
    print(f"* Synced successfully to space: {SPACE_URL.format(space_id=space_id)}")


def sync(
    project: str,
    space_id: str | None = None,
    private: bool | None = None,
    force: bool = False,
    run_in_background: bool = False,
) -> str:
    """
    Syncs a local Trackio project's database to a Hugging Face Space.
    If the Space does not exist, it will be created.

    Args:
        project (`str`): The name of the project to upload.
        space_id (`str`, *optional*): The ID of the Space to upload to (e.g., `"username/space_id"`).
            If not provided, checks project metadata first, then generates a random space_id.
        private (`bool`, *optional*):
            Whether to make the Space private. If None (default), the repo will be
            public unless the organization's default is private. This value is ignored
            if the repo already exists.
        force (`bool`, *optional*, defaults to `False`):
            If `True`, overwrite the existing database without prompting for confirmation.
            If `False`, prompt the user before overwriting an existing database.
        run_in_background (`bool`, *optional*, defaults to `False`):
            If `True`, the Space creation and database upload will be run in a background thread.
            If `False`, all the steps will be run synchronously.
    Returns:
        `str`: The Space ID of the synced project.
    """
    if space_id is None:
        space_id = SQLiteStorage.get_space_id(project)
    if space_id is None:
        space_id = f"{project}-{get_or_create_project_hash(project)}"
    space_id, _ = preprocess_space_and_dataset_ids(space_id, None)

    def _do_sync(space_id: str, private: bool | None = None, force: bool = False):
        sync_incremental(project, space_id, private=private, pending_only=False)

    if run_in_background:
        threading.Thread(target=_do_sync, args=(space_id, private, force)).start()
    else:
        _do_sync(space_id, private, force)
    return space_id
