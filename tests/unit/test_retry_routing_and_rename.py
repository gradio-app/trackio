import shutil
from unittest.mock import MagicMock

import pytest

from trackio import utils
from trackio.run import Run
from trackio.sqlite_storage import SQLiteStorage


def log_image(project, name, run_id):
    path = utils.project_media_dir(project) / name / "0" / f"{run_id}.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(run_id.encode())
    SQLiteStorage.bulk_log(
        project,
        name,
        [
            {
                "image": {
                    "_type": "trackio.image",
                    "file_path": str(path.relative_to(utils.MEDIA_DIR)),
                }
            }
        ],
        run_id=run_id,
    )
    return path


def read_image(project, name, run_id):
    row = SQLiteStorage.get_logs(project, name, run_id=run_id)[0]
    return (utils.MEDIA_DIR / row["image"]["file_path"]).read_bytes()


@pytest.mark.parametrize("other_name,new_name", [("beta", "beta"), ("alpha", "beta")])
def test_rename_preserves_other_runs_media(temp_dir, other_name, new_name):
    paths = {}
    for run_id, name in [("a", "alpha"), ("b", other_name)]:
        paths[run_id] = log_image("project", name, run_id)
    SQLiteStorage.rename_run("project", "alpha", new_name, run_id="a")
    for run_id, name in [("a", new_name), ("b", other_name)]:
        row = SQLiteStorage.get_logs("project", name, run_id=run_id)[0]
        assert (
            utils.MEDIA_DIR / row["image"]["file_path"]
        ).read_bytes() == run_id.encode()
    assert paths["b"].read_bytes() == b"b"


def test_replay_only_delivers_current_destination(temp_dir):
    destination = "https://server-b.example"
    client = MagicMock()
    run = Run(
        url=destination,
        project="project",
        client=client,
        name="b",
        server_base_url=destination,
        existing_runs=[],
        initial_last_step=-1,
    )
    try:
        for run_id, remote in [("a", "https://server-a.example"), ("b", destination)]:
            SQLiteStorage.bulk_log(
                "project", run_id, [{"loss": 1}], run_id=run_id, space_id=remote
            )
        assert run._flush_local_buffer()
        client.predict.assert_called_once()
        call = client.predict.call_args.kwargs
        assert call["api_name"] == "/bulk_log"
        assert [entry["run_id"] for entry in call["logs"]] == ["b"]
        pending = SQLiteStorage.get_pending_logs("project")
        assert [entry["run_id"] for entry in pending["logs"]] == ["a"]
    finally:
        run.finish()


def test_move_preserves_same_named_run_media_in_target(temp_dir):
    log_image("source", "shared", "a")
    kept = log_image("target", "shared", "b")
    assert SQLiteStorage.move_run("source", "shared", "target", run_id="a")
    assert read_image("target", "shared", "a") == b"a"
    assert read_image("target", "shared", "b") == b"b"
    assert kept.read_bytes() == b"b"


@pytest.mark.parametrize("new_name", ["..", "alpha/../../other", "alpha/v2"])
def test_failed_rename_leaves_run_and_media_untouched(temp_dir, new_name):
    path = log_image("project", "alpha", "a")
    with pytest.raises((ValueError, shutil.Error)):
        SQLiteStorage.rename_run("project", "alpha", new_name, run_id="a")
    assert read_image("project", "alpha", "a") == b"a"
    assert path.read_bytes() == b"a"
