import os
import time

import pytest
import huggingface_hub
from gradio_client import Client
from huggingface_hub.errors import HfHubHTTPError, RepositoryNotFoundError

from trackio import deploy, utils


@pytest.fixture(scope="session")
def test_space_id():
    space_id = os.environ.get("TEST_SPACE_ID")
    if not space_id:
        pytest.skip("TEST_SPACE_ID environment variable not set")
    space_id, _, _ = utils.preprocess_space_and_dataset_ids(space_id, None)
    return space_id


@pytest.fixture(scope="session", autouse=True)
def _ensure_space_ready(test_space_id):
    space_id, dataset_id, bucket_id = utils.preprocess_space_and_dataset_ids(
        test_space_id, None
    )

    _reset_test_space(space_id)
    deploy.create_space_if_not_exists(space_id, None, dataset_id, bucket_id, None)
    _wait_for_space_ready(space_id)


def _reset_test_space(space_id):
    try:
        huggingface_hub.delete_repo(space_id, repo_type="space")
    except RepositoryNotFoundError:
        return
    except HfHubHTTPError as e:
        if e.response is not None and e.response.status_code in (401, 403):
            raise RuntimeError(
                f"Cannot delete test Space {space_id}: check Hugging Face auth and write access."
            ) from e
        raise


def _wait_for_space_ready(space_id, timeout=300):
    hf_api = huggingface_hub.HfApi()
    deadline = time.time() + timeout
    delay = 2
    last_error = None
    last_stage = None

    terminal_stages = {"NO_APP_FILE", "CONFIG_ERROR", "BUILD_ERROR", "RUNTIME_ERROR"}

    while time.time() < deadline:
        try:
            info = hf_api.space_info(space_id, timeout=30)
            runtime = getattr(info, "runtime", None)
            if runtime is not None:
                last_stage = str(runtime.stage)
                if last_stage in terminal_stages:
                    raise RuntimeError(
                        f"Space {space_id} entered terminal stage {last_stage}. "
                        "Check the Hugging Face build logs."
                    )
                if last_stage == "RUNNING":
                    Client(space_id, verbose=False, httpx_kwargs={"timeout": 30})
                    return
        except HfHubHTTPError as e:
            last_error = e
            if e.response is not None and e.response.status_code in (401, 403):
                raise RuntimeError(
                    f"Cannot access test Space {space_id}: check Hugging Face auth and permissions."
                ) from e
        except Exception as e:
            last_error = e

        time.sleep(delay)
        delay = min(delay * 1.5, 15)

    pytest.fail(
        f"Space {space_id} not ready after {timeout}s. "
        f"Last observed stage={last_stage!r}, last error={last_error!r}"
    )


@pytest.fixture
def wait_for_client():
    def _wait(run, timeout=60):
        deadline = time.time() + timeout
        while run._client is None:
            if time.time() > deadline:
                raise TimeoutError("Client did not connect within timeout")
            time.sleep(0.1)

    return _wait
