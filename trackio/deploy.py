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

from trackio.sqlite_storage import SQLiteStorage

SPACE_URL = "https://huggingface.co/spaces/{space_id}"


def deploy_as_space(
    title: str,
):
    if (
        os.getenv("SYSTEM") == "spaces"
    ):  # in case a repo with this function is uploaded to spaces
        return

    trackio_path = files("trackio")

    hf_api = huggingface_hub.HfApi()
    whoami = None
    login = False
    try:
        whoami = hf_api.whoami()
        if whoami["auth"]["accessToken"]["role"] != "write":
            login = True
    except OSError:
        login = True
    if login:
        print("Need 'write' access token to create a Spaces repo.")
        huggingface_hub.login(add_to_git_credential=False)
        whoami = hf_api.whoami()

    space_id = huggingface_hub.create_repo(
        title,
        space_sdk="gradio",
        repo_type="space",
        exist_ok=True,
    ).repo_id
    assert space_id == title  # not sure why these would differ

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


def create_space_if_not_exists(
    space_id: str,
    dataset_id: str | None = None,
) -> None:
    """
    Creates a new Hugging Face Space if it does not exist.

    Args:
        space_id: The ID of the Space to create.
    """
    if "/" not in space_id:
        raise ValueError(
            f"Invalid space ID: {space_id}. Must be in the format: username/reponame."
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

    print(f"* Creating new space: {SPACE_URL.format(space_id=space_id)}")

    client = None
    for _ in range(30):
        try:
            client = Client(space_id, verbose=False)
            if client:
                break
        except ReadTimeout:
            print("* Space is not yet ready. Waiting 5 seconds...")
            time.sleep(5)
        except ValueError as e:
            print(f"* Space gave error {e}. Trying again in 5 seconds...")
            time.sleep(5)


def upload_db_to_space(project: str, space_id: str) -> None:
    """
    Uploads the database of a local Trackio project to a Hugging Face Space.

    Args:
        project: The name of the project to upload.
        space_id: The ID of the Space to upload to.
    """
    db_path = SQLiteStorage._get_project_db_path(project)
    client = Client(space_id, verbose=False)
    client.predict(
        api_name="/upload_db_to_space",
        project=project,
        db=handle_file(db_path),
        hf_token=huggingface_hub.utils.get_token(),
    )
