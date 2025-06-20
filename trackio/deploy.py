import io
import os
import time
from importlib.resources import files
from pathlib import Path

import gradio
import huggingface_hub
from httpx import ReadTimeout
from huggingface_hub.errors import RepositoryNotFoundError

SPACE_URL = "https://huggingface.co/spaces/{space_id}"


def deploy_as_space(
    title: str,
    dataset_id: str | None = None,
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
    if dataset_id is not None:
        huggingface_hub.add_space_variable(space_id, "TRACKIO_DATASET_ID", dataset_id)
        # So that the dataset id is available to the sqlite_storage.py file
        # if running locally as well.
        os.environ["TRACKIO_DATASET_ID"] = dataset_id


def create_space_if_not_exists(
    space_id: str,
    dataset_id: str | None = None,
) -> None:
    """
    Creates a new Hugging Face Space if it does not exist.

    Args:
        space_id: The ID of the Space to create.
        dataset_id: The ID of the Dataset to create.
    """
    if "/" not in space_id:
        raise ValueError(
            f"Invalid space ID: {space_id}. Must be in the format: username/reponame."
        )
    if dataset_id is not None and "/" not in dataset_id:
        raise ValueError(
            f"Invalid dataset ID: {dataset_id}. Must be in the format: username/datasetname."
        )
    try:
        huggingface_hub.repo_info(space_id, repo_type="space")
        print(f"* Found existing space: {SPACE_URL.format(space_id=space_id)}")
        return
    except RepositoryNotFoundError:
        pass

    print(f"* Creating new space: {SPACE_URL.format(space_id=space_id)}")
    deploy_as_space(space_id, dataset_id)

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
