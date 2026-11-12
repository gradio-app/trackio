from unittest.mock import MagicMock

import pytest

from trackio import fragments, utils
from trackio.run import Run
from trackio.sqlite_storage import SQLiteStorage


@pytest.mark.parametrize(
    "other_name,new_name", [("beta", "beta"), ("alpha", "beta"), ("beta", "alpha")]
)
def test_rename_preserves_other_runs_media(temp_dir, other_name, new_name):
    paths = {}
    for run_id, name in [("a", "alpha"), ("b", other_name)]:
        path = utils.project_media_dir("project") / name / "0" / f"{run_id}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(run_id.encode())
        paths[run_id] = path
        SQLiteStorage.bulk_log(
            "project",
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
    SQLiteStorage.rename_run("project", "alpha", new_name, run_id="a")
    for run_id, name in [("a", new_name), ("b", other_name)]:
        row = SQLiteStorage.get_logs("project", name, run_id=run_id)[0]
        assert (
            utils.MEDIA_DIR / row["image"]["file_path"]
        ).read_bytes() == run_id.encode()
    assert paths["b"].read_bytes() == b"b"


def seed_pending(project, destination, run_id, tmp_path):
    SQLiteStorage.bulk_log(
        project,
        run_id,
        [
            {
                "loss": 1,
                "trace": {
                    "_type": "trackio.trace",
                    "messages": [{"role": "user", "content": run_id}],
                    "metadata": {},
                },
            }
        ],
        run_id=run_id,
        log_ids=[f"log-{run_id}"],
        space_id=destination,
    )
    SQLiteStorage.bulk_log_system(
        project, run_id, [{"cpu": 1}], run_id=run_id, space_id=destination
    )
    path = tmp_path / f"{run_id}.png"
    path.write_bytes(run_id.encode())
    SQLiteStorage.add_pending_upload(
        project, destination, run_id, run_id, 0, str(path), None
    )
    SQLiteStorage.enqueue_artifact_blob_uploads(
        project,
        destination,
        [("a" * 64 if run_id == "a" else "b" * 64, str(path))],
        run_name=run_id,
        run_id=run_id,
    )


@pytest.mark.parametrize("delivery", ["server", "bucket", "spill"])
@pytest.mark.parametrize("destination", ["user/space-b", "https://server-b.example"])
def test_replay_only_delivers_current_destination(
    temp_dir, tmp_path, monkeypatch, delivery, destination
):
    seed_pending("project", "user/space-a", "a", tmp_path)
    seed_pending("project", destination, "b", tmp_path)
    run = Run.__new__(Run)
    run.project = "project"
    run.name = "b"
    run.id = "b"
    run.config = {}
    run._remote_storage_key = destination
    run._space_id = None
    run._client = MagicMock()
    run._bucket_id = "user/bucket-b"
    run._has_local_buffer = True
    run._spilled_metric_ids = set()
    run._spilled_system_ids = set()
    run._spilled_trace_ids = set()
    run._fragment_writer = MagicMock()
    run._warn_once = MagicMock()
    media_upload = MagicMock()
    blob_upload = MagicMock()
    monkeypatch.setattr(fragments, "upload_media_files_to_bucket", media_upload)
    monkeypatch.setattr(fragments, "upload_artifact_blobs_to_bucket", blob_upload)
    if delivery == "server":
        assert run._flush_local_buffer()
        calls = run._client.predict.call_args_list
        assert {c.kwargs["api_name"] for c in calls} == {
            "/bulk_log",
            "/bulk_log_system",
            "/bulk_upload_media",
            "/bulk_upload_artifact_blob",
        }
        for call in calls:
            entries = call.kwargs.get("logs", call.kwargs.get("uploads"))
            if call.kwargs["api_name"] == "/bulk_upload_artifact_blob":
                assert [e["digest"] for e in entries] == ["b" * 64]
            else:
                assert {e["run_id"] for e in entries} == {"b"}
        logs = next(
            c.kwargs["logs"] for c in calls if c.kwargs["api_name"] == "/bulk_log"
        )
        assert logs[0]["metrics"]["trace"]["messages"][0]["content"] == "b"
    else:
        if delivery == "bucket":
            run._drain_pending_to_bucket()
        else:
            run._spill_pending_to_bucket()
        assert run._fragment_writer.write_to_bucket.call_count == 2
        for call in run._fragment_writer.write_to_bucket.call_args_list:
            assert {r["run_id"] for r in call.args[0]} == {"b"}
        assert {u["run_id"] for u in media_upload.call_args.args[1]} == {"b"}
        assert {u["run_id"] for u in blob_upload.call_args.args[1]} == {"b"}
    for getter, key in [
        (SQLiteStorage.get_pending_logs, "logs"),
        (SQLiteStorage.get_pending_system_logs, "logs"),
        (SQLiteStorage.get_pending_traces, "traces"),
        (SQLiteStorage.get_pending_uploads, "uploads"),
    ]:
        remaining = getter("project")[key]
        expected = {"a", "b"} if delivery == "spill" and key != "uploads" else {"a"}
        assert {entry["run_id"] for entry in remaining} == expected
    run._warn_once.assert_not_called()


def test_pending_sync_keeps_other_destinations(temp_dir, tmp_path, monkeypatch):
    from trackio import deploy

    seed_pending("project", "user/space-a", "a", tmp_path)
    seed_pending("project", "user/space-b", "b", tmp_path)
    client = MagicMock()
    monkeypatch.setattr(deploy, "RemoteClient", lambda *args, **kwargs: client)
    monkeypatch.setattr(deploy, "create_space_if_not_exists", MagicMock())
    monkeypatch.setattr(deploy, "wait_until_space_exists", MagicMock())
    monkeypatch.setattr(deploy, "_wait_for_remote_sync", MagicMock())
    deploy.sync_incremental("project", "user/space-b", pending_only=True)
    for getter, key in [
        (SQLiteStorage.get_pending_logs, "logs"),
        (SQLiteStorage.get_pending_system_logs, "logs"),
        (SQLiteStorage.get_pending_uploads, "uploads"),
    ]:
        assert {r["run_id"] for r in getter("project")[key]} == {"a"}
    assert SQLiteStorage.has_pending_data("project", space_id="user/space-a")
    assert SQLiteStorage.get_pending_logs("project", space_id="user/space-b") is None


def test_failed_replay_keeps_pending_records(temp_dir, tmp_path):
    seed_pending("project", "user/space-a", "a", tmp_path)
    seed_pending("project", "user/space-b", "b", tmp_path)
    run = Run.__new__(Run)
    run.project = "project"
    run.name = "b"
    run._space_id = None
    run._remote_storage_key = "user/space-b"
    run._client = MagicMock()
    run._client.predict.side_effect = ConnectionError("offline")
    run._warn_once = MagicMock()
    assert not run._flush_local_buffer()
    assert {r["run_id"] for r in SQLiteStorage.get_pending_logs("project")["logs"]} == {
        "a",
        "b",
    }
    assert {r["run_id"] for r in run._client.predict.call_args.kwargs["logs"]} == {"b"}
