import os
import time

import pytest
from gradio_client import Client
from huggingface_hub import HfApi, delete_repo
from huggingface_hub.errors import RepositoryNotFoundError

import trackio

HF_TOKEN = os.environ.get("HF_TOKEN")
pytestmark = pytest.mark.skipif(not HF_TOKEN, reason="HF_TOKEN not set in environment")

hf_api = HfApi(token=HF_TOKEN)


def cleanup_space(space_id: str):
    """Delete the Hugging Face Space if it exists."""
    try:
        delete_repo(repo_id=space_id, repo_type="space", token=hf_api.token)
    except RepositoryNotFoundError:
        pass
    except Exception as e:
        print(f"Error deleting space {space_id}: {e}")


def test_push_to_new_space():
    """
    If space doesn't exist, it gets created and synced.
    """
    space_id = f"{hf_api.whoami()['name']}/trackio-test-new-{int(time.time())}"
    project = "new_project"
    name = "my_awesome_new_project"

    try:
        cleanup_space(space_id)
        try:
            trackio.delete_project(project, force=True)
            run = trackio.init(project=project, name=name)
            run.log({"accuracy": 0.99}, step=1)
            run.finish()

            trackio.push(project=project, space_id=space_id, private=True)

            repo_info = hf_api.repo_info(repo_id=space_id, repo_type="space")
            assert repo_info.id == space_id

            client = Client(space_id, hf_token=HF_TOKEN, verbose=False)
            runs = client.predict(project=project, api_name="/get_runs_for_project")
            assert name in runs

        finally:
            trackio.delete_project(project, force=True)

    finally:
        cleanup_space(space_id)


def test_push_to_existing_space():
    """
    If space already exists, we should just sync to it.
    """
    space_id = f"{hf_api.whoami()['name']}/trackio-test-existing-{int(time.time())}"
    project = "existing_project"
    name = "my_awesome_existing_project"

    try:
        trackio.deploy.create_space_if_not_exists(space_id=space_id)
        trackio.deploy.wait_until_space_exists(space_id)
        try:
            trackio.delete_project(project, force=True)
            run = trackio.init(project=project, name=name)
            run.log({"accuracy": 0.98}, step=1)
            run.finish()

            client = Client(space_id, hf_token=HF_TOKEN, verbose=False)
            runs = client.predict(project=project, api_name="/get_runs_for_project")
            assert name not in runs

            trackio.push(project=project, space_id=space_id, private=True)

            client.hf_token = HF_TOKEN
            runs = client.predict(project=project, api_name="/get_runs_for_project")
            assert name in runs

        finally:
            trackio.delete_project(project, force=True)

    finally:
        cleanup_space(space_id)
