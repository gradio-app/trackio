"""Shared routing for buffered `pending_uploads` rows.

Both the in-`Run` sender (`Run._send_pending_uploads_to_server`) and the
out-of-run sync path (`deploy._replay_pending_uploads`) replay the same
queue: media files go to `/bulk_upload_media`, artifact blobs go to
`/bulk_upload_artifact_blob` grouped by project. Grouping lives here so the
two senders cannot drift; each group carries its own row ids so callers can
clear rows per successfully-sent group instead of all-or-nothing.
"""

from pathlib import Path

from gradio_client import handle_file


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
