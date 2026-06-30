from pathlib import Path

from trackio import bucket_storage
from trackio.sqlite_storage import SQLiteStorage


def _captured(monkeypatch):
    """Replace `batch_bucket_files` with a capture; return a dict that gets the kwargs."""
    captured: dict = {}

    def _fake_batch(bucket_id, add=None, **kwargs):
        captured["bucket_id"] = bucket_id
        captured["add"] = list(add or [])

    monkeypatch.setattr(
        bucket_storage.huggingface_hub, "batch_bucket_files", _fake_batch
    )
    return captured


def test_upload_project_to_bucket_skips_partial_files(
    temp_dir, monkeypatch, stage_blob
):
    SQLiteStorage.init_db("p")
    digest, blob = stage_blob("p", b"complete")
    partial = blob.parent / f"{blob.name}.partial.deadbeef"
    partial.write_bytes(b"in-flight")

    captured = _captured(monkeypatch)
    bucket_storage.upload_project_to_bucket("p", "user/bucket")

    remote_paths = {remote for _, remote in captured["add"]}
    assert f"trackio/artifacts/p/blobs/sha256/{digest[:2]}/{digest}" in remote_paths
    assert not any(".partial." in p for p in remote_paths)


def test_upload_project_to_bucket_without_artifacts_dir_is_no_op_for_artifacts(
    temp_dir, monkeypatch
):
    SQLiteStorage.init_db("no-artifacts")
    captured = _captured(monkeypatch)
    bucket_storage.upload_project_to_bucket("no-artifacts", "user/bucket")
    remote_paths = {remote for _, remote in captured["add"]}
    assert not any("artifacts/" in p for p in remote_paths)


def test_upload_project_to_bucket_ships_media_and_artifacts_together(
    temp_dir, monkeypatch, stage_blob
):
    SQLiteStorage.init_db("p")
    digest_a, _ = stage_blob("p", b"alpha")
    digest_b, _ = stage_blob("p", b"beta")
    media_path = Path(temp_dir) / "media" / "p" / "run-0" / "0" / "img.png"
    media_path.parent.mkdir(parents=True, exist_ok=True)
    media_path.write_bytes(b"png-bytes")

    captured = _captured(monkeypatch)
    bucket_storage.upload_project_to_bucket("p", "user/bucket")

    remote_paths = {remote for _, remote in captured["add"]}
    assert "trackio/media/p/run-0/0/img.png" in remote_paths
    assert f"trackio/artifacts/p/blobs/sha256/{digest_a[:2]}/{digest_a}" in remote_paths
    assert f"trackio/artifacts/p/blobs/sha256/{digest_b[:2]}/{digest_b}" in remote_paths
    assert any(p.endswith(".db") and "trackio/" in p for p in remote_paths)


def test_replay_pending_uploads_routes_both_kinds(temp_dir, tmp_path):
    from unittest.mock import MagicMock

    from trackio import deploy

    media_path = tmp_path / "img.png"
    media_path.write_bytes(b"png-bytes")
    blob_path = tmp_path / "blob.bin"
    blob_path.write_bytes(b"weights")

    SQLiteStorage.add_pending_upload(
        project="p",
        space_id="user/space",
        run_id="rid",
        run_name="r",
        step=0,
        file_path=str(media_path),
        relative_path="img.png",
    )
    SQLiteStorage.enqueue_artifact_blob_uploads(
        project="p",
        space_id="user/space",
        blobs=[("a" * 64, str(blob_path))],
        run_name="r",
        run_id="rid",
    )

    client = MagicMock()
    deploy._replay_pending_uploads("p", client, hf_token=None)

    api_calls = [c.kwargs.get("api_name") for c in client.predict.call_args_list]
    assert "/bulk_upload_media" in api_calls
    assert "/bulk_upload_artifact_blob" in api_calls

    assert SQLiteStorage.get_pending_uploads("p") is None


def test_replay_pending_uploads_skips_missing_files(temp_dir):
    from unittest.mock import MagicMock

    from trackio import deploy

    SQLiteStorage.enqueue_artifact_blob_uploads(
        project="p",
        space_id="user/space",
        blobs=[("a" * 64, "/nonexistent/path")],
        run_name="r",
        run_id="rid",
    )
    client = MagicMock()
    deploy._replay_pending_uploads("p", client, hf_token=None)
    client.predict.assert_not_called()
