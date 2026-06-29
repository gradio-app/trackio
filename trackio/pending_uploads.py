from collections.abc import Callable
from pathlib import Path
from typing import Any

from gradio_client import handle_file

from trackio.sqlite_storage import SQLiteStorage

MEDIA_UPLOAD_KIND = "media"
ARTIFACT_BLOB_UPLOAD_KIND = "artifact_blob"


def classify_pending_uploads(buffered: dict) -> dict:
    """Partition `buffered` (`{"uploads": [...], "ids": [...]}` from
    `SQLiteStorage.get_pending_uploads`) by kind.
    """
    media: list[tuple[dict, int]] = []
    artifact_blobs: list[tuple[dict, int]] = []
    missing: dict = {"paths": [], "ids": []}
    for upload, upload_id in zip(buffered["uploads"], buffered["ids"]):
        fp = upload["file_path"]
        if not Path(fp).exists():
            missing["paths"].append(fp)
            missing["ids"].append(upload_id)
        elif upload.get("kind") == ARTIFACT_BLOB_UPLOAD_KIND:
            artifact_blobs.append((upload, upload_id))
        else:
            media.append((upload, upload_id))
    return {"media": media, "artifact_blobs": artifact_blobs, "missing": missing}


def _media_upload_entry(upload: dict) -> dict:
    return {
        "project": upload["project"],
        "run": upload["run"],
        "run_id": upload.get("run_id"),
        "step": upload["step"],
        "relative_path": upload["relative_path"],
        "uploaded_file": handle_file(upload["file_path"]),
    }


def _artifact_blob_upload_entry(upload: dict) -> dict:
    return {
        "project": upload["project"],
        "digest": upload["digest"],
        "uploaded_file": handle_file(upload["file_path"]),
    }


def _append_grouped_entry(
    grouped: dict,
    group_key: str,
    upload: dict,
    upload_id: int,
    entry_builder: Callable[[dict], dict],
) -> None:
    group = grouped.setdefault(group_key, {"entries": [], "ids": []})
    group["entries"].append(entry_builder(upload))
    group["ids"].append(upload_id)


def group_pending_uploads(buffered: dict) -> dict:
    """Shape classified rows for the gradio `predict` endpoints."""
    classified = classify_pending_uploads(buffered)
    media_groups: dict[str, dict] = {}
    for upload, upload_id in classified["media"]:
        _append_grouped_entry(
            media_groups,
            MEDIA_UPLOAD_KIND,
            upload,
            upload_id,
            _media_upload_entry,
        )
    artifact_blobs: dict[str, dict] = {}
    for upload, upload_id in classified["artifact_blobs"]:
        _append_grouped_entry(
            artifact_blobs,
            upload["project"],
            upload,
            upload_id,
            _artifact_blob_upload_entry,
        )
    return {
        "media": media_groups.get(MEDIA_UPLOAD_KIND, {"entries": [], "ids": []}),
        "artifact_blobs": artifact_blobs,
        "missing": classified["missing"],
    }


def replay_pending_uploads(
    buffered: dict,
    project: str,
    *,
    predict: Callable[..., Any],
    hf_token: str | None,
    warn_missing: Callable[[int, str], None],
    verbose: bool = False,
) -> None:
    """Route grouped `pending_uploads` rows to their endpoints, clearing each
    group's rows as soon as it is sent.
    """
    grouped = group_pending_uploads(buffered)
    missing = grouped["missing"]
    if missing["ids"]:
        warn_missing(len(missing["ids"]), missing["paths"][0])
        SQLiteStorage.clear_pending_uploads(project, missing["ids"])
    media = grouped["media"]
    if media["entries"]:
        if verbose:
            print(f"  Syncing {len(media['entries'])} media files...")
        predict(
            api_name="/bulk_upload_media",
            uploads=media["entries"],
            hf_token=hf_token,
        )
        SQLiteStorage.clear_pending_uploads(project, media["ids"])
    for proj, group in grouped["artifact_blobs"].items():
        if verbose:
            print(
                f"  Syncing {len(group['entries'])} artifact blobs for project '{proj}'..."
            )
        predict(
            api_name="/bulk_upload_artifact_blob",
            project=proj,
            uploads=group["entries"],
            hf_token=hf_token,
        )
        SQLiteStorage.clear_pending_uploads(project, group["ids"])
