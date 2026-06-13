"""Shared routing for buffered `pending_uploads` rows.

Both the in-`Run` sender (`Run._send_pending_uploads_to_server`) and the
out-of-run sync path (`deploy._replay_pending_uploads`) replay the same
queue: media files go to `/bulk_upload_media`, artifact blobs go to
`/bulk_upload_artifact_blob` grouped by project. Grouping lives here so the
two senders cannot drift; each group carries its own row ids so callers can
clear rows per successfully-sent group instead of all-or-nothing.
"""

from collections.abc import Callable
from pathlib import Path
from typing import Any

from gradio_client import handle_file

from trackio.sqlite_storage import SQLiteStorage


def group_pending_uploads(buffered: dict) -> dict:
    """Split `buffered` (`{"uploads": [...], "ids": [...]}` from
    `SQLiteStorage.get_pending_uploads`) into sendable groups.

    Returns:
        {
            "media": {"entries": [UploadEntry], "ids": [int]},
            "artifact_blobs": {project: {"entries": [...], "ids": [int]}},
            "missing": {"paths": [str], "ids": [int]},
        }

    Rows whose `file_path` no longer exists land in `"missing"` — they can
    never be sent, so callers should clear them and surface a warning rather
    than dropping them silently.
    """
    media: dict = {"entries": [], "ids": []}
    artifact_blobs: dict[str, dict] = {}
    missing: dict = {"paths": [], "ids": []}
    for upload, upload_id in zip(buffered["uploads"], buffered["ids"]):
        fp = upload["file_path"]
        if not Path(fp).exists():
            missing["paths"].append(fp)
            missing["ids"].append(upload_id)
            continue
        if upload.get("kind") == "artifact_blob":
            group = artifact_blobs.setdefault(
                upload["project"], {"entries": [], "ids": []}
            )
            group["entries"].append(
                {
                    "project": upload["project"],
                    "digest": upload["digest"],
                    "uploaded_file": handle_file(fp),
                }
            )
            group["ids"].append(upload_id)
        else:
            media["entries"].append(
                {
                    "project": upload["project"],
                    "run": upload["run"],
                    "run_id": upload.get("run_id"),
                    "step": upload["step"],
                    "relative_path": upload["relative_path"],
                    "uploaded_file": handle_file(fp),
                }
            )
            media["ids"].append(upload_id)
    return {"media": media, "artifact_blobs": artifact_blobs, "missing": missing}


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

    Single-sources the kind→endpoint routing for both the in-`Run` sender and
    the out-of-run `trackio sync` path so the two cannot drift. A failure
    partway through propagates without clearing rows that were not uploaded.
    Callers supply `predict`/`hf_token`, a `warn_missing(count, sample_path)`
    callback for vanished source files, and `verbose=True` for progress prints.
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
