import time

import pytest


@pytest.fixture
def wait_for_client():
    def _wait(run, timeout=60):
        deadline = time.time() + timeout
        while run._client is None:
            if time.time() > deadline:
                raise TimeoutError("Client did not connect within timeout")
            time.sleep(0.1)

    return _wait
