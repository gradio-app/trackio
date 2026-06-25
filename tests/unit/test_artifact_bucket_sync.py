"""Sync-path coverage for artifacts.

- `bucket_storage.upload_project_to_bucket` ships blob bytes alongside DB+media.
- `commit_scheduler` `allow_patterns` for dataset-mode sync include
  `artifacts/**/*`.
- `deploy._replay_pending_uploads` routes by `pending_uploads.kind`.

Mocks `huggingface_hub` / `CommitScheduler` / RemoteClient so we don't hit the
network.
"""

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


def test_replay_pending_uploads_with_empty_queue_is_noop(temp_dir):
    from unittest.mock import MagicMock

    from trackio import deploy

    SQLiteStorage.init_db("p")
    client = MagicMock()
    deploy._replay_pending_uploads("p", client, hf_token=None)
    client.predict.assert_not_called()


def test_upload_artifact_blobs_to_bucket_uses_cas_path(
    temp_dir, monkeypatch, stage_blob
):
    from trackio import fragments

    digest, blob = stage_blob("p", b"weights")

    captured: dict = {}

    def _fake_batch(bucket_id, add=None, **kwargs):
        captured["add"] = list(add or [])

    monkeypatch.setattr(fragments.huggingface_hub, "batch_bucket_files", _fake_batch)

    fragments.upload_artifact_blobs_to_bucket(
        "user/bucket",
        [
            {
                "file_path": str(blob),
                "project": "p",
                "digest": digest,
                "kind": "artifact_blob",
            }
        ],
    )

    remote_paths = {remote for _, remote in captured["add"]}
    assert remote_paths == {f"trackio/artifacts/p/blobs/sha256/{digest[:2]}/{digest}"}


def test_flush_pending_uploads_routes_by_kind(
    temp_dir, tmp_path, monkeypatch, stage_blob
):
    from types import SimpleNamespace

    from trackio import run as run_module
    from trackio.run import Run

    digest, blob = stage_blob("p", b"weights")
    media_path = tmp_path / "img.png"
    media_path.write_bytes(b"png-bytes")

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
        blobs=[(digest, str(blob))],
        run_name="r",
        run_id="rid",
    )

    calls: dict = {"media": [], "blob": []}
    monkeypatch.setattr(
        run_module.fragments,
        "upload_media_files_to_bucket",
        lambda bucket_id, uploads: calls["media"].append(uploads),
    )
    monkeypatch.setattr(
        run_module.fragments,
        "upload_artifact_blobs_to_bucket",
        lambda bucket_id, uploads: calls["blob"].append(uploads),
    )

    fake = SimpleNamespace(project="p", _bucket_id="user/bucket")
    Run._flush_pending_uploads_to_bucket(fake)

    assert len(calls["media"]) == 1
    assert calls["media"][0][0]["relative_path"] == "img.png"
    assert len(calls["blob"]) == 1
    assert calls["blob"][0][0]["digest"] == digest
    assert SQLiteStorage.get_pending_uploads("p") is None


def test_flush_pending_uploads_warns_and_clears_missing(
    temp_dir, tmp_path, monkeypatch, stage_blob
):
    from types import SimpleNamespace

    from trackio import run as run_module
    from trackio.run import Run

    digest, blob = stage_blob("p", b"weights")
    gone = tmp_path / "vanished.png"

    SQLiteStorage.add_pending_upload(
        project="p",
        space_id="user/space",
        run_id="rid",
        run_name="r",
        step=0,
        file_path=str(gone),
        relative_path="vanished.png",
    )
    SQLiteStorage.enqueue_artifact_blob_uploads(
        project="p",
        space_id="user/space",
        blobs=[(digest, str(blob))],
        run_name="r",
        run_id="rid",
    )

    calls: dict = {"media": [], "blob": [], "warn": []}
    monkeypatch.setattr(
        run_module.fragments,
        "upload_media_files_to_bucket",
        lambda bucket_id, uploads: calls["media"].append(uploads),
    )
    monkeypatch.setattr(
        run_module.fragments,
        "upload_artifact_blobs_to_bucket",
        lambda bucket_id, uploads: calls["blob"].append(uploads),
    )

    fake = SimpleNamespace(
        project="p",
        _bucket_id="user/bucket",
        _warn_missing_uploads=lambda count, sample: calls["warn"].append(
            (count, sample)
        ),
    )
    Run._flush_pending_uploads_to_bucket(fake)

    assert calls["warn"] == [(1, str(gone))]
    assert calls["media"] == []
    assert len(calls["blob"]) == 1
    assert calls["blob"][0][0]["digest"] == digest
    assert SQLiteStorage.get_pending_uploads("p") is None


def test_flush_pending_uploads_keeps_blobs_when_upload_fails(
    temp_dir, tmp_path, monkeypatch, stage_blob
):
    from types import SimpleNamespace

    import pytest

    from trackio import run as run_module
    from trackio.run import Run

    digest, blob = stage_blob("p", b"weights")
    media_path = tmp_path / "img.png"
    media_path.write_bytes(b"png-bytes")

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
        blobs=[(digest, str(blob))],
        run_name="r",
        run_id="rid",
    )

    monkeypatch.setattr(
        run_module.fragments,
        "upload_media_files_to_bucket",
        lambda bucket_id, uploads: None,
    )

    def _boom(bucket_id, uploads):
        raise RuntimeError("bucket unreachable")

    monkeypatch.setattr(run_module.fragments, "upload_artifact_blobs_to_bucket", _boom)

    fake = SimpleNamespace(project="p", _bucket_id="user/bucket")
    with pytest.raises(RuntimeError):
        Run._flush_pending_uploads_to_bucket(fake)

    remaining = SQLiteStorage.get_pending_uploads("p")
    assert remaining is not None
    assert {u["kind"] for u in remaining["uploads"]} == {"artifact_blob"}


def test_dataset_mode_allow_patterns_includes_artifacts(monkeypatch):
    """commit_scheduler picks up artifact blobs when configured for dataset sync."""
    from trackio import sqlite_storage as _ss

    captured: dict = {}

    class _CapturingScheduler:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(_ss, "_current_scheduler", None, raising=False)
    monkeypatch.setattr(_ss.SQLiteStorage, "_current_scheduler", None)
    monkeypatch.setattr(_ss, "CommitScheduler", _CapturingScheduler)
    monkeypatch.setenv("TRACKIO_DATASET_ID", "user/ds")
    monkeypatch.setenv("SPACE_REPO_NAME", "user/space")

    _ss.SQLiteStorage.get_scheduler()
    assert "artifacts/**/*" in captured["allow_patterns"]
    for pattern in (
        "*.parquet",
        "media/**/*",
        "*_traces.parquet",
    ):
        assert pattern in captured["allow_patterns"]
