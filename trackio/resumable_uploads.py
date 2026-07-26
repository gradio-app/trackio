"""Durable, bounded-memory upload sessions for artifact blobs."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from collections.abc import AsyncIterable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from trackio import cas, utils

DEFAULT_CHUNK_SIZE = 8 * 1024 * 1024
COMPATIBILITY_MAX_BYTES = 32 * 1024 * 1024
DEFAULT_SESSION_TTL = timedelta(hours=24)
UPLOAD_ID_RE = re.compile(r"^[0-9a-f]{64}$")
IDEMPOTENCY_KEY_RE = re.compile(r"^[A-Za-z0-9_-]{16,128}$")


class UploadSessionError(ValueError):
    """An invalid or conflicting resumable upload operation."""


def _uploads_root(project: str) -> Path:
    return utils.project_artifacts_dir(project) / "uploads"


def _session_dir(project: str, upload_id: str) -> Path:
    if not UPLOAD_ID_RE.fullmatch(upload_id):
        raise UploadSessionError("Invalid upload id.")
    return _uploads_root(project) / upload_id


def _metadata_path(project: str, upload_id: str) -> Path:
    return _session_dir(project, upload_id) / "session.json"


def _part_path(project: str, upload_id: str, index: int) -> Path:
    return _session_dir(project, upload_id) / "parts" / f"{index:08d}.part"


def _now() -> datetime:
    return datetime.now(UTC)


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        json.dump(payload, handle, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    os.replace(temporary, path)


def _read_session(project: str, upload_id: str) -> dict[str, Any]:
    path = _metadata_path(project, upload_id)
    if not path.is_file():
        raise FileNotFoundError("Upload session does not exist.")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise UploadSessionError("Upload session metadata is invalid.") from error
    if payload.get("project") != utils.canonical_project_name(project):
        raise UploadSessionError("Upload session project does not match.")
    return payload


def _upload_id(project: str, idempotency_key: str) -> str:
    if not IDEMPOTENCY_KEY_RE.fullmatch(idempotency_key):
        raise UploadSessionError(
            "Idempotency key must be 16-128 URL-safe alphanumeric characters."
        )
    identity = f"{utils.canonical_project_name(project)}\0{idempotency_key}".encode()
    return hashlib.sha256(identity).hexdigest()


def _expected_chunks(size_bytes: int, chunk_size_bytes: int) -> int:
    if size_bytes == 0:
        return 0
    return (size_bytes + chunk_size_bytes - 1) // chunk_size_bytes


def _expected_chunk_size(session: dict[str, Any], index: int) -> int:
    count = int(session["chunk_count"])
    if index < 0 or index >= count:
        raise UploadSessionError(f"Chunk index {index} is outside 0..{count - 1}.")
    chunk_size = int(session["chunk_size_bytes"])
    if index < count - 1:
        return chunk_size
    return int(session["size_bytes"]) - (index * chunk_size)


def _public_session(session: dict[str, Any]) -> dict[str, Any]:
    return {
        "upload_id": session["upload_id"],
        "digest": session["digest"],
        "size_bytes": session["size_bytes"],
        "chunk_size_bytes": session["chunk_size_bytes"],
        "chunk_count": session["chunk_count"],
        "acknowledged_chunks": sorted(int(index) for index in session["chunks"]),
        "state": session["state"],
        "expires_at": session["expires_at"],
    }


def create_or_resume_session(
    *,
    project: str,
    digest: str,
    size_bytes: int,
    idempotency_key: str,
    chunk_size_bytes: int = DEFAULT_CHUNK_SIZE,
) -> dict[str, Any]:
    """Create an idempotent upload session or return its current state."""

    project = utils.canonical_project_name(project)
    digest = str(cas.validate_digest(digest))
    if not isinstance(size_bytes, int) or size_bytes < 0:
        raise UploadSessionError("Upload size must be a non-negative integer.")
    if chunk_size_bytes <= 0:
        raise UploadSessionError("Chunk size must be positive.")
    upload_id = _upload_id(project, idempotency_key)
    metadata = _metadata_path(project, upload_id)
    if metadata.is_file():
        session = _read_session(project, upload_id)
        if session["digest"] != digest or session["size_bytes"] != size_bytes:
            raise UploadSessionError(
                "Idempotency key is already bound to a different artifact blob."
            )
        return _public_session(session)

    now = _now()
    session = {
        "schema_version": 1,
        "upload_id": upload_id,
        "project": project,
        "digest": digest,
        "size_bytes": size_bytes,
        "chunk_size_bytes": chunk_size_bytes,
        "chunk_count": _expected_chunks(size_bytes, chunk_size_bytes),
        "chunks": {},
        "state": "uploading",
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
        "expires_at": (now + DEFAULT_SESSION_TTL).isoformat(),
    }
    _write_json_atomic(metadata, session)
    return _public_session(session)


def get_session(project: str, upload_id: str) -> dict[str, Any]:
    return _public_session(_read_session(project, upload_id))


async def store_chunk(
    *,
    project: str,
    upload_id: str,
    index: int,
    claimed_digest: str,
    chunks: AsyncIterable[bytes],
) -> dict[str, Any]:
    """Stream one chunk to durable staging and acknowledge it idempotently."""

    claimed_digest = str(cas.validate_digest(claimed_digest))
    session = _read_session(project, upload_id)
    if session["state"] == "completed":
        raise UploadSessionError("Upload session is already completed.")
    expected_size = _expected_chunk_size(session, index)
    existing = session["chunks"].get(str(index))
    if existing is not None:
        if existing["digest"] != claimed_digest:
            raise UploadSessionError("Chunk index is already bound to a different digest.")
        return {"index": index, **existing, "already_present": True}

    destination = _part_path(project, upload_id, index)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.parent / cas.partial_blob_name(destination.name)
    sha = hashlib.sha256()
    received = 0
    try:
        with temporary.open("wb") as handle:
            async for chunk in chunks:
                if not chunk:
                    continue
                received += len(chunk)
                if received > expected_size:
                    raise UploadSessionError(
                        f"Chunk {index} exceeds expected size {expected_size}."
                    )
                sha.update(chunk)
                handle.write(chunk)
            handle.flush()
            os.fsync(handle.fileno())
        if received != expected_size:
            raise UploadSessionError(
                f"Chunk {index} has size {received}; expected {expected_size}."
            )
        actual = sha.hexdigest()
        if actual != claimed_digest:
            raise UploadSessionError(
                f"Chunk digest mismatch: claimed {claimed_digest}, computed {actual}."
            )
        os.replace(temporary, destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise

    session = _read_session(project, upload_id)
    existing = session["chunks"].get(str(index))
    if existing is None:
        session["chunks"][str(index)] = {"digest": claimed_digest, "size_bytes": received}
        now = _now()
        session["updated_at"] = now.isoformat()
        session["expires_at"] = (now + DEFAULT_SESSION_TTL).isoformat()
        _write_json_atomic(_metadata_path(project, upload_id), session)
        already_present = False
    else:
        already_present = True
    return {
        "index": index,
        "digest": claimed_digest,
        "size_bytes": received,
        "already_present": already_present,
    }


def _part_chunks(project: str, upload_id: str, count: int) -> Iterator[bytes]:
    for index in range(count):
        path = _part_path(project, upload_id, index)
        with path.open("rb") as handle:
            while chunk := handle.read(cas.HASH_CHUNK_SIZE):
                yield chunk


def complete_session(project: str, upload_id: str) -> dict[str, Any]:
    """Verify and atomically expose a fully acknowledged artifact blob."""

    session = _read_session(project, upload_id)
    target = cas.blob_path(project, session["digest"])
    if session["state"] == "completed":
        return {
            "digest": session["digest"],
            "size_bytes": session["size_bytes"],
            "already_present": True,
        }
    expected = set(range(int(session["chunk_count"])))
    acknowledged = {int(index) for index in session["chunks"]}
    missing = sorted(expected - acknowledged)
    if missing:
        raise UploadSessionError(f"Upload session is missing chunks: {missing[:20]}.")

    already_present = target.is_file()
    cas.stage_blob_from_chunks(
        _part_chunks(project, upload_id, int(session["chunk_count"])),
        claimed_digest=session["digest"],
        target_path=target,
    )
    if target.stat().st_size != session["size_bytes"]:
        raise UploadSessionError("Completed artifact blob size does not match session.")

    session["state"] = "completed"
    session["completed_at"] = _now().isoformat()
    session["updated_at"] = session["completed_at"]
    _write_json_atomic(_metadata_path(project, upload_id), session)
    shutil.rmtree(_session_dir(project, upload_id) / "parts", ignore_errors=True)
    return {
        "digest": session["digest"],
        "size_bytes": session["size_bytes"],
        "already_present": already_present,
    }


def abort_session(project: str, upload_id: str) -> bool:
    session = _read_session(project, upload_id)
    if session["state"] == "completed":
        raise UploadSessionError("Completed upload sessions cannot be aborted.")
    shutil.rmtree(_session_dir(project, upload_id))
    return True


def expire_sessions(
    *,
    project: str,
    older_than: datetime,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Report or remove incomplete sessions older than a timezone-aware cutoff."""

    if older_than.tzinfo is None:
        raise UploadSessionError("Expiry cutoff must be timezone-aware.")
    root = _uploads_root(project)
    expired: list[dict[str, Any]] = []
    if root.is_dir():
        for metadata in root.glob("*/session.json"):
            try:
                session = json.loads(metadata.read_text(encoding="utf-8"))
                updated = datetime.fromisoformat(session["updated_at"])
            except (OSError, KeyError, ValueError, json.JSONDecodeError):
                continue
            if session.get("state") == "completed" or updated >= older_than:
                continue
            session_dir = metadata.parent
            bytes_used = sum(
                path.stat().st_size for path in session_dir.rglob("*") if path.is_file()
            )
            expired.append(
                {
                    "upload_id": session["upload_id"],
                    "updated_at": session["updated_at"],
                    "bytes": bytes_used,
                }
            )
            if not dry_run:
                shutil.rmtree(session_dir)
    return {
        "project": utils.canonical_project_name(project),
        "dry_run": dry_run,
        "sessions": expired,
        "session_count": len(expired),
        "reclaimable_bytes": sum(item["bytes"] for item in expired),
    }


__all__ = [
    "COMPATIBILITY_MAX_BYTES",
    "DEFAULT_CHUNK_SIZE",
    "UploadSessionError",
    "abort_session",
    "complete_session",
    "create_or_resume_session",
    "expire_sessions",
    "get_session",
    "store_chunk",
]
