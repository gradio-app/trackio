import pytest
from starlette.testclient import TestClient

from trackio import server
from trackio.sqlite_storage import SQLiteStorage

OWNER_COOKIE = {"Cookie": "trackio_hf_access_token=owner-oauth"}


class _Scheduler:
    def trigger(self):
        class _Done:
            def result(self):
                return None

        return _Done()


@pytest.fixture
def space_client(monkeypatch, temp_dir):
    monkeypatch.setenv("SYSTEM", "spaces")
    monkeypatch.setenv("SPACE_AUTHOR_NAME", "owner")
    monkeypatch.setenv("SPACE_REPO_NAME", "demo")
    monkeypatch.delenv("TRACKIO_BUCKET_ID", raising=False)
    monkeypatch.delenv("TRACKIO_DATASET_ID", raising=False)
    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.setattr(
        server.HfApi, "whoami", lambda *a, **k: {"name": "owner", "orgs": []}
    )
    monkeypatch.setattr(server, "_oauth_write_cache", {})
    monkeypatch.setattr(server, "import_inbox_once", lambda: 0)
    monkeypatch.setattr(server, "start_inbox_poller", lambda: None)
    syncs = []
    monkeypatch.setattr(
        SQLiteStorage, "export_to_parquet", staticmethod(lambda: syncs.append(1))
    )
    monkeypatch.setattr(
        SQLiteStorage, "get_scheduler", staticmethod(lambda: _Scheduler())
    )
    app, _ = server.build_starlette_app_only()
    client = TestClient(app)
    client.syncs = syncs
    return client


@pytest.mark.parametrize(
    "content_type",
    ["text/plain", "application/x-www-form-urlencoded", "multipart/form-data", None],
)
@pytest.mark.parametrize("route", ["/api/delete_run", "/gradio_api/call/delete_run"])
def test_cookie_write_without_json_content_type_is_rejected(
    space_client, content_type, route
):
    SQLiteStorage.bulk_log("proj", "victim", [{"loss": 1.0}], steps=[0])
    headers = dict(OWNER_COOKIE)
    if content_type is not None:
        headers["Content-Type"] = content_type

    response = space_client.post(
        route,
        content='{"project": "proj", "run": "victim"}',
        headers=headers,
    )

    assert response.status_code == 415
    assert SQLiteStorage.get_runs("proj") == ["victim"]


def test_cookie_write_with_json_content_type_still_works(space_client):
    SQLiteStorage.bulk_log("proj", "old", [{"loss": 1.0}], steps=[0])

    renamed = space_client.post(
        "/api/rename_run",
        json={"project": "proj", "old_name": "old", "new_name": "new"},
        headers={**OWNER_COOKIE, "Content-Type": "application/json; charset=utf-8"},
    )
    assert renamed.status_code == 200
    assert SQLiteStorage.get_runs("proj") == ["new"]

    deleted = space_client.post(
        "/api/delete_run",
        json={"project": "proj", "run": "new"},
        headers=OWNER_COOKIE,
    )
    assert deleted.status_code == 200
    assert SQLiteStorage.get_runs("proj") == []


def test_reads_and_cookieless_writes_do_not_need_json_content_type(
    space_client, monkeypatch
):
    SQLiteStorage.bulk_log("proj", "run", [{"loss": 1.0}], steps=[0])
    monkeypatch.setattr(server, "check_hf_token_has_write_access", lambda token: None)

    read = space_client.post(
        "/api/get_runs_for_project",
        content='{"project": "proj"}',
        headers={**OWNER_COOKIE, "Content-Type": "text/plain"},
    )
    assert read.status_code == 200

    synced = space_client.post(
        "/api/force_sync", headers={"Authorization": "Bearer hf_write"}
    )
    assert synced.status_code == 200


def test_force_sync_requires_write_access_on_spaces(space_client, monkeypatch):
    anonymous = space_client.post("/api/force_sync", json={})
    assert anonymous.status_code == 400
    assert "Write access" in anonymous.json()["error"]
    assert space_client.syncs == []

    def deny(token):
        raise PermissionError("no write access")

    monkeypatch.setattr(server, "check_hf_token_has_write_access", deny)
    denied = space_client.post(
        "/api/force_sync", json={}, headers={"Authorization": "Bearer hf_read"}
    )
    assert denied.status_code == 400
    assert space_client.syncs == []


def test_force_sync_allowed_for_writers_on_spaces(space_client, monkeypatch):
    seen = []
    monkeypatch.setattr(server, "check_hf_token_has_write_access", seen.append)

    bearer = space_client.post(
        "/api/force_sync", json={}, headers={"Authorization": "Bearer hf_write"}
    )
    assert bearer.status_code == 200
    assert seen == ["hf_write"]

    oauth = space_client.post("/api/force_sync", json={}, headers=OWNER_COOKIE)
    assert oauth.status_code == 200
    assert len(space_client.syncs) == 2


def test_force_sync_requires_write_token_locally(space_client, monkeypatch):
    monkeypatch.delenv("SYSTEM")

    anonymous = space_client.post("/api/force_sync", json={})
    assert anonymous.status_code == 400
    assert space_client.syncs == []

    authorized = space_client.post(
        "/api/force_sync",
        json={},
        headers={"X-Trackio-Write-Token": server.write_token},
    )
    assert authorized.status_code == 200
    assert space_client.syncs == [1]


def test_force_sync_does_not_skip_the_dataset_import(space_client, monkeypatch):
    monkeypatch.setattr(server, "check_hf_token_has_write_access", lambda token: None)
    monkeypatch.setattr(SQLiteStorage, "_dataset_import_attempted", False)
    loads = []
    monkeypatch.setattr(
        SQLiteStorage, "load_from_dataset", staticmethod(lambda: loads.append(1))
    )

    response = space_client.post(
        "/api/force_sync", json={}, headers={"Authorization": "Bearer hf_write"}
    )

    assert response.status_code == 200
    assert loads == [1]
    assert SQLiteStorage._dataset_import_attempted is False
