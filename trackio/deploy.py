import importlib.metadata
import io
import os
import threading
import time
from importlib.resources import files
from pathlib import Path

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


def _is_trackio_installed_from_source() -> bool:
    """Check if trackio is installed from source/editable install vs PyPI."""
    try:
        trackio_file = trackio.__file__
        if "site-packages" not in trackio_file:
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

    with open(Path(trackio_path, "README.md"), "r") as f:
        readme_content = f.read()
        readme_content = readme_content.replace("{GRADIO_VERSION}", gradio.__version__)
        readme_buffer = io.BytesIO(readme_content.encode("utf-8"))
        hf_api.upload_file(
            path_or_fileobj=readme_buffer,
            path_in_repo="README.md",
            repo_id=space_id,
            repo_type="space",
        )

    # We can assume pandas, gradio, and huggingface-hub are already installed in a Gradio Space.
    # Make sure necessary dependencies are installed by creating a requirements.txt.
    is_source_install = _is_trackio_installed_from_source()

    if is_source_install:
        requirements_content = """pyarrow>=21.0
plotly>=6.0.0,<7.0.0"""
    else:
        requirements_content = f"""pyarrow>=21.0
trackio=={trackio.__version__}
plotly>=6.0.0,<7.0.0"""

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
            ignore_patterns=["README.md"],
        )
    else:
        app_file_content = """import trackio
trackio.show()"""
        app_file_buffer = io.BytesIO(app_file_content.encode("utf-8"))
        hf_api.upload_file(
            path_or_fileobj=app_file_buffer,
            path_in_repo="ui/main.py",
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
        if dataset_id is not None:
            huggingface_hub.add_space_variable(
                space_id, "TRACKIO_DATASET_ID", dataset_id
            )
        if logo_light_url := os.environ.get("TRACKIO_LOGO_LIGHT_URL"):
            huggingface_hub.add_space_variable(
                space_id, "TRACKIO_LOGO_LIGHT_URL", logo_light_url
            )
        if logo_dark_url := os.environ.get("TRACKIO_LOGO_DARK_URL"):
            huggingface_hub.add_space_variable(
                space_id, "TRACKIO_LOGO_DARK_URL", logo_dark_url
            )

        if plot_order := os.environ.get("TRACKIO_PLOT_ORDER"):
            huggingface_hub.add_space_variable(
                space_id, "TRACKIO_PLOT_ORDER", plot_order
            )

        if theme := os.environ.get("TRACKIO_THEME"):
            huggingface_hub.add_space_variable(space_id, "TRACKIO_THEME", theme)
        return
    except RepositoryNotFoundError:
        pass
    except HfHubHTTPError as e:
        if e.response.status_code in [401, 403]:  # unauthorized or forbidden
            print("Need 'write' access token to create a Spaces repo.")
            huggingface_hub.login(add_to_git_credential=False)
            huggingface_hub.add_space_variable(
                space_id, "TRACKIO_DATASET_ID", dataset_id
            )
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
            If not provided, a random space_id (e.g. "username/project-2ac3z2aA") will be used.
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
        space_id = f"{project}-{get_or_create_project_hash(project)}"
    space_id, _ = preprocess_space_and_dataset_ids(space_id, None)

    def space_creation_and_upload(
        space_id: str, private: bool | None = None, force: bool = False
    ):
        print(
            f"* Syncing local Trackio project to: {SPACE_URL.format(space_id=space_id)} (please wait...)"
        )
        create_space_if_not_exists(space_id, private=private)
        wait_until_space_exists(space_id)
        upload_db_to_space(project, space_id, force=force)
        print(f"* Synced successfully to space: {SPACE_URL.format(space_id=space_id)}")

    if run_in_background:
        threading.Thread(
            target=space_creation_and_upload, args=(space_id, private, force)
        ).start()
    else:
        space_creation_and_upload(space_id, private, force)
    return space_id
