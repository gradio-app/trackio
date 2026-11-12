from pathlib import Path

import pytest
from starlette.testclient import TestClient

from trackio import server, utils
from trackio.asgi_app import create_trackio_starlette_app
from trackio.media.utils import get_project_media_path
from trackio.sqlite_storage import SQLiteStorage


def test_upload_rejects_escaping_paths_and_accepts_nested_media(temp_dir):
    app = create_trackio_starlette_app(
        [],
        {"bulk_upload_media": server.bulk_upload_media},
        upload_authorizer=server.assert_can_stage_upload,
    )
    client = TestClient(app, headers={"X-Trackio-Write-Token": server.write_token})
    outside = utils.MEDIA_DIR / "outside"
    outside.mkdir(parents=True)
    sentinel = outside / "marker.txt"
    sentinel.write_bytes(b"unchanged")

    def upload(**kwargs):
        staged = client.post(
            "/api/upload", files={"files": ("marker.txt", b"uploaded")}
        )
        path = staged.json()["paths"][0]
        entry = {
            "project": "project",
            "run": "run",
            "step": 0,
            "relative_path": None,
            "uploaded_file": {"path": path, "orig_name": "marker.txt"},
            **kwargs,
        }
        response = client.post(
            "/api/bulk_upload_media", json={"uploads": [entry], "hf_token": None}
        )
        assert not Path(path).exists()
        return response

    for fields in [
        {"run": "../outside", "step": None},
        {"run": str(outside), "step": None},
        {"run": "C:\\outside", "step": None},
        {"step": "../../outside"},
        {"run": None, "step": None, "relative_path": "../../outside"},
    ]:
        assert upload(**fields).status_code == 400
        assert sentinel.read_bytes() == b"unchanged"
    assert upload(run="nested/训练 run").status_code == 200
    assert (
        utils.project_media_dir("project") / "nested/训练 run/0/marker.txt"
    ).read_bytes() == b"uploaded"
    assert upload(run=None, step=None, relative_path=".").status_code == 200


def test_media_rejects_symlinked_directory_and_destination(temp_dir, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "marker.txt"
    sentinel.write_bytes(b"unchanged")
    media = utils.project_media_dir("project")
    media.mkdir(parents=True)
    try:
        (media / "escape").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("Symlinks require privileges on this platform")
    with pytest.raises(ValueError):
        get_project_media_path("project", run="escape")
    directory = get_project_media_path("project", run="run", step=0)
    (directory / "marker.txt").symlink_to(sentinel)
    app = create_trackio_starlette_app(
        [],
        {"bulk_upload_media": server.bulk_upload_media},
        upload_authorizer=server.assert_can_stage_upload,
    )
    client = TestClient(app, headers={"X-Trackio-Write-Token": server.write_token})
    path = client.post(
        "/api/upload", files={"files": ("marker.txt", b"uploaded")}
    ).json()["paths"][0]
    response = client.post(
        "/api/bulk_upload_media",
        json={
            "uploads": [
                {
                    "project": "project",
                    "run": "run",
                    "step": 0,
                    "relative_path": None,
                    "uploaded_file": {"path": path, "orig_name": "marker.txt"},
                }
            ],
            "hf_token": None,
        },
    )
    assert response.status_code == 400
    assert sentinel.read_bytes() == b"unchanged"

    (directory / "marker.txt").unlink()
    (directory / "marker.txt").mkdir()
    path = client.post(
        "/api/upload", files={"files": ("marker.txt", b"uploaded")}
    ).json()["paths"][0]
    (directory / "marker.txt" / Path(path).name).symlink_to(sentinel)
    response = client.post(
        "/api/bulk_upload_media",
        json={
            "uploads": [
                {
                    "project": "project",
                    "run": "run",
                    "step": 0,
                    "relative_path": None,
                    "uploaded_file": {"path": path, "orig_name": "marker.txt"},
                }
            ],
            "hf_token": None,
        },
    )
    assert response.status_code == 400
    assert sentinel.read_bytes() == b"unchanged"


def test_rename_and_move_reject_unsafe_names_before_mutation(temp_dir):
    SQLiteStorage.bulk_log("project", "run", [{"loss": 1}], run_id="id")
    media = get_project_media_path("project", run="run")
    (media / "marker.txt").write_bytes(b"unchanged")
    for name in [
        "..",
        "../outside",
        str(utils.MEDIA_DIR),
        "C:\\outside",
        "nested/../../outside",
    ]:
        with pytest.raises(ValueError):
            SQLiteStorage.rename_run("project", "run", name, run_id="id")
        with pytest.raises(ValueError):
            SQLiteStorage.rename_run("project", name, "safe", run_id="id")
        with pytest.raises(ValueError):
            SQLiteStorage.move_run("project", name, "target", run_id="id")
        assert SQLiteStorage.get_run_records("project")[0]["name"] == "run"
        assert (media / "marker.txt").read_bytes() == b"unchanged"
    assert not SQLiteStorage.get_project_db_path("target").exists()
