"""Content-addressed storage (CAS) helpers shared by the artifact client,
server, and storage layers.

Blobs live at `ARTIFACTS_DIR/<project>/blobs/sha256/<digest[:2]>/<digest>`.
All writes go through a `.partial.<uuid>` temp file in the destination
directory followed by an atomic rename, so concurrent writers and crashed
processes never leave a torn blob at the final path.
"""

import hashlib
import os
import re
import uuid
from collections.abc import Iterable, Iterator
from pathlib import Path

from trackio import utils
from trackio.typehints import Sha256Digest

SHA256_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
ARTIFACT_VERSION_SPEC_RE = re.compile(r"^v(\d+)$")
ARTIFACT_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")
HASH_CHUNK_SIZE = 1024 * 1024


def validate_artifact_name(name: str) -> str:
    if not isinstance(name, str) or not ARTIFACT_NAME_RE.match(name):
        raise ValueError(
            f"Artifact name {name!r} must match ^[A-Za-z0-9._-]+$ "
            "(letters, digits, dot, underscore, hyphen)."
        )
    return name


def blob_path(project: str, digest: Sha256Digest) -> Path:
    return utils.ARTIFACTS_DIR / project / "blobs" / "sha256" / digest[:2] / digest


def hash_file(path: Path) -> tuple[Sha256Digest, int]:
    size = path.stat().st_size
    file_digest = getattr(hashlib, "file_digest", None)
    if file_digest is not None:
        with path.open("rb") as f:
            sha = file_digest(f, "sha256")
    else:
        sha = hashlib.sha256()
        with path.open("rb") as f:
            while chunk := f.read(HASH_CHUNK_SIZE):
                sha.update(chunk)
    return Sha256Digest(sha.hexdigest()), size


def validate_logical_path(logical: str) -> str:
    """Validate a manifest logical path: relative, no `.`/`..` segments, no
    backslashes, no drive letters, non-empty. Returns the path unchanged.
    """
    if not isinstance(logical, str) or not logical:
        raise ValueError(f"Invalid artifact path: {logical!r} (must be non-empty)")
    if "\\" in logical or "\x00" in logical:
        raise ValueError(
            f"Invalid artifact path {logical!r}: backslashes and NUL are not allowed"
        )
    if logical.startswith("/") or re.match(r"^[A-Za-z]:", logical):
        raise ValueError(f"Invalid artifact path {logical!r}: must be relative")
    parts = logical.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise ValueError(
            f"Invalid artifact path {logical!r}: "
            "'.', '..', and empty segments are not allowed"
        )
    return logical


def validate_digest(digest: str) -> Sha256Digest:
    """Validate that `digest` is a 64-char lowercase sha256 hex string and
    return it unchanged.
    """
    if not isinstance(digest, str) or not SHA256_DIGEST_RE.match(digest):
        raise ValueError(f"Invalid artifact blob digest: {digest!r}")
    return Sha256Digest(digest)


def stage_blob_from_chunks(
    chunks: Iterable[bytes],
    claimed_digest: Sha256Digest,
    target_path: Path,
) -> None:
    """Stream `chunks` into a `.partial.<uuid>` file in the CAS dir, rehashing
    as we go. On match, atomic-rename to `target_path`. On failure, clean up the
    partial. If `target_path.is_file()` already, returns without consuming
    `chunks`.
    """
    if target_path.is_file():
        return
    target_path.parent.mkdir(parents=True, exist_ok=True)
    partial = target_path.parent / f"{target_path.name}.partial.{uuid.uuid4().hex}"
    sha = hashlib.sha256()
    try:
        with partial.open("wb") as dst:
            for chunk in chunks:
                if not chunk:
                    continue
                sha.update(chunk)
                dst.write(chunk)
        actual = sha.hexdigest()
        if actual != claimed_digest:
            raise ValueError(
                f"Digest mismatch: claimed {claimed_digest}, computed {actual}"
            )
        os.replace(partial, target_path)
    except Exception:
        partial.unlink(missing_ok=True)
        raise


def stage_blob_from_file(
    src_path: Path,
    claimed_digest: Sha256Digest,
    target_path: Path,
) -> None:
    """Copy `src_path` into the CAS via a partial file + atomic rename,
    verifying the content hashes to `claimed_digest`.
    """
    if target_path.is_file():
        return

    def _file_chunks() -> Iterator[bytes]:
        with src_path.open("rb") as src:
            while chunk := src.read(HASH_CHUNK_SIZE):
                yield chunk

    stage_blob_from_chunks(_file_chunks(), claimed_digest, target_path)


def stage_blob_into_project(src_path: Path, project: str) -> tuple[Sha256Digest, int]:
    """Copy `src_path` into the project's CAS in a single pass, computing its
    sha256 and size while writing. Returns `(digest, size)`. The blob is staged
    to a `.partial.<uuid>` file and atomically renamed to the digest-derived
    path; if that path already holds the blob, the partial is discarded.
    """
    blobs_root = utils.ARTIFACTS_DIR / project / "blobs" / "sha256"
    blobs_root.mkdir(parents=True, exist_ok=True)
    partial = blobs_root / f".partial.{uuid.uuid4().hex}"
    sha = hashlib.sha256()
    size = 0
    try:
        with src_path.open("rb") as src, partial.open("wb") as dst:
            while chunk := src.read(HASH_CHUNK_SIZE):
                sha.update(chunk)
                dst.write(chunk)
                size += len(chunk)
        digest = Sha256Digest(sha.hexdigest())
        target = blob_path(project, digest)
        if target.is_file():
            partial.unlink(missing_ok=True)
            return digest, size
        target.parent.mkdir(parents=True, exist_ok=True)
        os.replace(partial, target)
        return digest, size
    except Exception:
        partial.unlink(missing_ok=True)
        raise
