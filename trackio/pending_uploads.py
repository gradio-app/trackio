"""Shared routing for buffered `pending_uploads` rows.

`classify_pending_uploads` splits the queue by kind (media vs artifact blob)
and sets aside rows whose local file has vanished. Every sender consumes it so
the kind taxonomy and missing-file handling cannot drift:

- the gradio `predict` senders (`Run._send_pending_uploads_to_server` and the
  out-of-run `deploy._replay_pending_uploads`) shape rows via
  `group_pending_uploads` and POST to `/bulk_upload_media` /
  `/bulk_upload_artifact_blob` (grouped by project, since that endpoint takes
  one project per call);
- the bucket spill (`Run._flush_pending_uploads_to_bucket`) hands raw rows to
  the bucket helpers.

Each group carries its own row ids so callers clear rows per successfully-sent
group instead of all-or-nothing.
"""

from collections.abc import Callable
from pathlib import Path
from typing import Any

from gradio_client import handle_file

from trackio.sqlite_storage import SQLiteStorage


def classify_pending_uploads(buffered: dict) -> dict:
    """Partition `buffered` (`{"uploads": [...], "ids": [...]}` from
    `SQLiteStorage.get_pending_uploads`) by kind, without shaping rows for any
    particular destination.

    Returns:
        {
            "media": [(upload, id), ...],
            "artifact_blobs": [(upload, id), ...],
            "missing": {"paths": [str], "ids": [int]},
        }

    Rows whose `file_path` no longer exists land in `"missing"` — callers
    should clear them and surface a warning.
    """
    media: list[tuple[dict, int]] = []
    artifact_blobs: list[tuple[dict, int]] = []
    missing: dict = {"paths": [], "ids": []}
    for upload, upload_id in zip(buffered["uploads"], buffered["ids"]):
        fp = upload["file_path"]
        if not Path(fp).exists():
            missing["paths"].append(fp)
            missing["ids"].append(upload_id)
        elif upload.get("kind") == "artifact_blob":
            artifact_blobs.append((upload, upload_id))
        else:
            media.append((upload, upload_id))
    return {"media": media, "artifact_blobs": artifact_blobs, "missing": missing}


def group_pending_uploads(buffered: dict) -> dict:
    """Shape classified rows for the gradio `predict` endpoints.

    Returns:
        {
            "media": {"entries": [UploadEntry], "ids": [int]},
            "artifact_blobs": {project: {"entries": [...], "ids": [int]}},
            "missing": {"paths": [str], "ids": [int]},
        }
    """
    classified = classify_pending_uploads(buffered)
    media: dict = {"entries": [], "ids": []}
    for upload, upload_id in classified["media"]:
        media["entries"].append(
            {
                "project": upload["project"],
                "run": upload["run"],
                "run_id": upload.get("run_id"),
                "step": upload["step"],
                "relative_path": upload["relative_path"],
                "uploaded_file": handle_file(upload["file_path"]),
            }
        )
        media["ids"].append(upload_id)
    artifact_blobs: dict[str, dict] = {}
    for upload, upload_id in classified["artifact_blobs"]:
        group = artifact_blobs.setdefault(upload["project"], {"entries": [], "ids": []})
        group["entries"].append(
            {
                "project": upload["project"],
                "digest": upload["digest"],
                "uploaded_file": handle_file(upload["file_path"]),
            }
        )
        group["ids"].append(upload_id)
    return {
        "media": media,
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
