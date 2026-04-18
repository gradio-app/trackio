import httpx

from trackio.remote_client import FORCE_SYNC_TIMEOUT, _request_timeout_for_api


def test_force_sync_timeout_extends_short_default_timeout():
    timeout = _request_timeout_for_api(60, "force_sync")

    assert isinstance(timeout, httpx.Timeout)
    assert timeout.connect == 60
    assert timeout.read == FORCE_SYNC_TIMEOUT
    assert timeout.write == 60
    assert timeout.pool == 60


def test_force_sync_timeout_preserves_longer_timeout():
    timeout = _request_timeout_for_api(240, "force_sync")

    assert timeout == 240


def test_non_force_sync_timeout_is_unchanged():
    timeout = _request_timeout_for_api(60, "get_run_summary")

    assert timeout == 60
