import io
import os
import time
from importlib.resources import files
from pathlib import Path

import gradio
import huggingface_hub
from gradio_client import Client, handle_file
from httpx import ReadTimeout
from huggingface_hub.errors import RepositoryNotFoundError
from requests import HTTPError

from trackio.sqlite_storage import SQLiteStorage

SPACE_URL = "https://huggingface.co/spaces/{space_id}"


def deploy_as_space(
    space_id: str,
    dataset_id: str | None = None,
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
            space_sdk="gradio",
            repo_type="space",
            exist_ok=True,
        )
    except HTTPError as e:
        if e.response.status_code in [401, 403]:  # unauthorized or forbidden
            print("Need 'write' access token to create a Spaces repo.")
            huggingface_hub.login(add_to_git_credential=False)
            huggingface_hub.create_repo(
                space_id,
                space_sdk="gradio",
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

    huggingface_hub.utils.disable_progress_bars()
    hf_api.upload_folder(
        repo_id=space_id,
        repo_type="space",
        folder_path=trackio_path,
        ignore_patterns=["README.md"],
    )

    hf_token = huggingface_hub.utils.get_token()
    if hf_token is not None:
        huggingface_hub.add_space_secret(space_id, "HF_TOKEN", hf_token)
    if dataset_id is not None:
        huggingface_hub.add_space_variable(space_id, "TRACKIO_DATASET_ID", dataset_id)


def create_space_if_not_exists(
    space_id: str,
    dataset_id: str | None = None,
) -> None:
    """
    Creates a new Hugging Face Space if it does not exist. If a dataset_id is provided, it will be added as a space variable.

    Args:
        space_id: The ID of the Space to create.
        dataset_id: The ID of the Dataset to add to the Space.
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
        return
    except RepositoryNotFoundError:
        pass
    except HTTPError as e:
        if e.response.status_code in [401, 403]:  # unauthorized or forbidden
            print("Need 'write' access token to create a Spaces repo.")
            huggingface_hub.login(add_to_git_credential=False)
            huggingface_hub.add_space_variable(
                space_id, "TRACKIO_DATASET_ID", dataset_id
            )
        else:
            raise ValueError(f"Failed to create Space: {e}")

    print(f"* Creating new space: {SPACE_URL.format(space_id=space_id)}")
    deploy_as_space(space_id, dataset_id)


def wait_until_space_exists(
    space_id: str,
) -> None:
    """
    Blocks the current thread until the space exists.
    May raise a TimeoutError if this takes quite a while.

    Args:
        space_id: The ID of the Space to wait for.
    """
    delay = 1
    for _ in range(10):
        try:
            Client(space_id, verbose=False)
            return
        except (ReadTimeout, ValueError):
            time.sleep(delay)
            delay = min(delay * 2, 30)
    raise TimeoutError("Waiting for space to exist took longer than expected")


def upload_db_to_space(project: str, space_id: str) -> None:
    """
    Uploads the database of a local Trackio project to a Hugging Face Space.

    Args:
        project: The name of the project to upload.
        space_id: The ID of the Space to upload to.
    """
    db_path = SQLiteStorage.get_project_db_path(project)
    client = Client(space_id, verbose=False)
    client.predict(
        api_name="/upload_db_to_space",
        project=project,
        uploaded_db=handle_file(db_path),
        hf_token=huggingface_hub.utils.get_token(),
    )
