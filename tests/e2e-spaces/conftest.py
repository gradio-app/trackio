import os
import time

import pytest
from gradio_client import Client

from trackio import deploy, utils


@pytest.fixture(scope="session")
def test_space_id():
    space_id = os.environ.get("TEST_SPACE_ID")
    if not space_id:
        pytest.skip("TEST_SPACE_ID environment variable not set")
    return space_id


@pytest.fixture(scope="session", autouse=True)
def _ensure_space_ready(test_space_id):
    space_id, dataset_id, bucket_id = utils.preprocess_space_and_dataset_ids(
        test_space_id, None
    )
    deploy.create_space_if_not_exists(space_id, None, dataset_id, bucket_id, None)

    deadline = time.time() + 240
    while time.time() < deadline:
        try:
            Client(test_space_id, verbose=False)
            return
        except Exception:
            time.sleep(5)
    pytest.fail(f"Space {test_space_id} not ready after 4 minutes")


@pytest.fixture
def wait_for_client():
    def _wait(run, timeout=60):
        deadline = time.time() + timeout
        while run._client is None:
            if time.time() > deadline:
                raise TimeoutError("Client did not connect within timeout")
            time.sleep(0.1)

    return _wait
