"""External artifact references, and the per-scheme handlers that resolve and
fetch them without staging any bytes at log time.

Each supported scheme is a `ReferenceHandler`: `matches` claims a URI, `resolve`
probes it for size + a checksum (expanding a directory or object prefix into one
entry per object), and `fetch` downloads a single object. `_select` returns the
first handler whose `matches` is true, raising for a scheme no handler claims.
The built-in handlers cover `file://`, `http(s)://`, and `hf://` — all served
by trackio's existing dependencies. Any other scheme (`s3://`, `gs://`, Azure
blob URLs, ...) is supported by registering a custom `ReferenceHandler` via
`register_reference_handler`; the artifacts documentation includes complete,
copy-pasteable handlers for the major cloud object stores.

Object keys are carried through URIs percent-encoded (object-store keys may
contain spaces, which `validate_reference_uri` rejects): `resolve` encodes the
keys it discovers when synthesizing per-object ref URIs, and `fetch` decodes the
key back before reading the source, so a manifest ref always round-trips.

This module also defines the dependency-light reference primitives —
`validate_reference_uri`, `local_path_from_file_uri`, `default_reference_name`,
the `looks_signed` credential heuristic, and the `is_reference_entry` manifest
discriminator — shared by the artifact, storage, server, and CLI layers.
"""

import importlib
import shutil
from abc import ABC, abstractmethod
from pathlib import Path
from typing import NamedTuple
from urllib.parse import parse_qsl, quote, unquote, urlsplit
from urllib.request import url2pathname

import httpx

from trackio import cas
from trackio.typehints import ETag, Sha256Digest

DEFAULT_MAX_OBJECTS = 10_000


def validate_reference_uri(uri: str) -> tuple[str, str]:
    """Validate an external reference URI and return `(scheme, uri)`.

    The URI must be a non-empty string carrying a scheme and free of NUL and
    whitespace (spaces and other special characters must be percent-encoded).
    The scheme is not restricted here — this validates only the URI's shape;
    whether a scheme can actually be resolved and fetched is decided by the
    registered `ReferenceHandler`s. The URI is returned unchanged. Use
    `local_path_from_file_uri` to resolve a `file://` URI to a local
    filesystem path.
    """
    if not isinstance(uri, str) or not uri:
        raise ValueError(f"Invalid reference URI: {uri!r} (must be non-empty)")
    if "\x00" in uri:
        raise ValueError(f"Invalid reference URI {uri!r}: NUL is not allowed")
    if any(char.isspace() for char in uri):
        raise ValueError(
            f"Invalid reference URI {uri!r}: whitespace is not allowed "
            "(percent-encode spaces and special characters)"
        )
    scheme = urlsplit(uri).scheme.lower()
    if not scheme:
        raise ValueError(
            f"Invalid reference URI {uri!r}: a scheme is required "
            "(e.g. file://, s3://, https://); use add_file for local paths."
        )
    return scheme, uri


def local_path_from_file_uri(uri: str) -> Path:
    """Best-effort resolution of a `file://` URI to a local `Path`.

    The returned path is not guaranteed to exist; callers should check
    `.is_file()` before reading it.
    """
    parts = urlsplit(uri)
    local = url2pathname(parts.path)
    host = parts.netloc
    if host and host.lower() != "localhost":
        return Path(f"//{host}{local}")
    return Path(local)


def default_reference_name(uri: str) -> str:
    """Derive a default logical name for a reference from its URI: the last
    non-empty path segment, falling back to the host."""
    parts = urlsplit(uri)
    tail = parts.path.rstrip("/").rsplit("/", 1)[-1]
    return tail or parts.netloc


def is_reference_entry(entry: dict) -> bool:
    """True if a manifest entry is an external reference (carries a `ref` URI)
    rather than a blob staged into content-addressed storage."""
    return "ref" in entry


_SIGNED_QUERY_KEYS = frozenset(
    {"x-amz-signature", "x-goog-signature", "sig", "token", "signature"}
)


def looks_signed(uri: str) -> bool:
    """Heuristic: True when a URI's query string appears to embed a credential —
    a presigned S3/GCS URL (`X-Amz-Signature`, `X-Goog-Signature`), a CloudFront
    or S3 v2 `Signature`, an Azure SAS token (`sig`), or a bearer-style `token`
    parameter. Bare `s3://`/`gs://` URIs carry no query and never match."""
    query = urlsplit(uri).query
    if not query:
        return False
    return any(
        key.lower() in _SIGNED_QUERY_KEYS
        for key, _ in parse_qsl(query, keep_blank_values=True)
    )


class ResolvedReference(NamedTuple):
    """One object a reference URI resolves to. `relkey` is None for a single
    object (the caller's `name`/basename is used) or the object's path relative
    to the expanded prefix. `digest` is the object's checksum — a content sha256
    for `file://` and LFS `hf://`, or the provider's opaque ETag for HTTP and
    object-store references; None when unavailable (the caller then falls back
    to the URI)."""

    relkey: str | None
    uri: str
    size: int | None = None
    digest: Sha256Digest | ETag | None = None


class ReferenceHandler(ABC):
    """Resolves and fetches references for one family of URI schemes.

    This is the extension point for schemes trackio does not handle natively:
    subclass it and register an instance with `register_reference_handler`.
    Concrete handlers are stateless; the built-ins are instantiated once in
    `_HANDLERS`.
    """

    @abstractmethod
    def matches(self, scheme: str, uri: str) -> bool:
        """Whether this handler owns `uri`. `_select` tries handlers in order and
        takes the first match; handlers registered via
        `register_reference_handler` are consulted before the built-ins, so a
        specialization (e.g. an object store addressed by `https://` URLs) wins
        over the generic HTTP handler."""

    @abstractmethod
    def resolve(
        self, uri: str, checksum: bool, max_objects: int
    ) -> list[ResolvedReference]:
        """Probe `uri` for its size and a checksum, expanding a directory or
        prefix into one entry per object. Returns a single un-checksummed entry
        (`size`/`digest` None) when the source cannot be probed, so the caller
        can fall back to the URI as the digest. `checksum` False skips only the
        per-object checksum: a prefix still expands (one entry per object,
        `digest` None) while a single object stays an un-probed pointer."""

    @abstractmethod
    def fetch(self, uri: str, dest: Path) -> None:
        """Download the single object at `uri` to `dest`."""

    @abstractmethod
    def hint(self) -> str:
        """Actionable hint for enabling content-based versioning when `resolve`
        could not produce a checksum."""


def resolve_reference(
    uri: str, scheme: str, checksum: bool, max_objects: int
) -> list[ResolvedReference]:
    """Resolve `uri` to one or more objects. Never raises for an unreachable
    remote (those resolve un-checksummed); raises for a scheme no registered
    handler claims, a missing local `file://` path, or an expansion exceeding
    `max_objects`."""
    return _select(scheme, uri).resolve(uri, checksum, max_objects)


def fetch_reference(uri: str, scheme: str, dest: Path) -> None:
    """Download the single object at `uri` to `dest`. Raises if no registered
    handler claims the scheme or the source cannot be read."""
    _select(scheme, uri).fetch(uri, dest)


def checksum_hint(scheme: str, uri: str) -> str:
    """A short, actionable hint for checksumming a reference trackio could not."""
    return _select(scheme, uri).hint()


class FileHandler(ReferenceHandler):
    """Local files (`file://`).

    A file is stream-hashed to a content sha256 with its size read from disk; a
    directory is expanded into one entry per file (symlinks skipped). Unlike the
    remote handlers, a path that exists as neither a file nor a directory raises
    rather than being recorded — a missing local file is almost always a typo."""

    def matches(self, scheme, uri):
        """Owns `file://` URIs."""
        return scheme == "file"

    def resolve(self, uri, checksum, max_objects):
        """Hash a single file, or walk a directory into one entry per file; raise
        if the path is neither."""
        local = local_path_from_file_uri(uri)
        if local.is_dir():
            entries: list[ResolvedReference] = []
            for path in local.rglob("*"):
                if path.is_symlink() or not path.is_file():
                    continue
                digest, size = self._digest_and_size(path, checksum)
                entries.append(
                    ResolvedReference(
                        relkey=path.relative_to(local).as_posix(),
                        uri=path.resolve().as_uri(),
                        size=size,
                        digest=digest,
                    )
                )
                _within_max(len(entries), max_objects, uri)
            return entries
        if local.is_file():
            digest, size = self._digest_and_size(local, checksum)
            return [ResolvedReference(None, uri, size=size, digest=digest)]
        raise ValueError(
            f"Local reference {uri!r} is not an existing file or directory; check "
            "the path, or use add_file to copy a local file into the artifact."
        )

    def fetch(self, uri, dest):
        """Copy the local file's bytes into `dest`."""
        local = local_path_from_file_uri(uri)
        if not local.is_file():
            raise FileNotFoundError(f"Reference source not found locally: {uri}")
        shutil.copyfile(local, dest)

    def hint(self):
        """Shown when a `file://` object was recorded without a content hash."""
        return "Ensure the file exists locally so it can be checksummed by content."

    @staticmethod
    def _digest_and_size(path: Path, checksum: bool) -> tuple[Sha256Digest | None, int]:
        """The file's content sha256 and size when `checksum`, else None and the
        size read from disk. `cas.hash_file` stats the file while hashing, so its
        returned size is reused instead of a second `stat`."""
        if checksum:
            return cas.hash_file(path)
        return None, path.stat().st_size


class HttpHandler(ReferenceHandler):
    """Arbitrary HTTP(S) URLs (`http://`, `https://`).

    Size and a checksum come from the `Content-Length` and `ETag` headers of a
    `HEAD` request; both are optional, so a server that omits them (or is
    unreachable) resolves the reference un-checksummed. A custom handler
    registered via `register_reference_handler` can claim specific `https://`
    hosts (e.g. an object store's blob endpoints) ahead of this one."""

    def matches(self, scheme, uri):
        """Owns `http(s)://` URLs not claimed by a more specific handler."""
        return scheme in ("http", "https")

    def resolve(self, uri, checksum, max_objects):
        """HEAD the URL for `Content-Length` and `ETag`; degrade to an
        un-checksummed entry if the request fails."""
        return _http_resolve(uri, checksum)

    def fetch(self, uri, dest):
        """Stream the URL body into `dest`."""
        _http_fetch(uri, dest)

    def hint(self):
        """Shown when the server exposed no usable ETag."""
        return "Check that the URL is reachable and that its server exposes an ETag header."


class HfHandler(ReferenceHandler):
    """Hugging Face Hub files (`hf://...`), via `huggingface_hub`'s filesystem.

    huggingface_hub is a core dependency, so no extra install is needed. The
    checksum is the LFS sha256 when present, else the git blob id or xet hash; a
    directory is expanded into one entry per file."""

    def matches(self, scheme, uri):
        """Owns `hf://` URIs."""
        return scheme == "hf"

    def resolve(self, uri, checksum, max_objects):
        """Read file info for a single object, or expand a directory into one
        entry per file. Degrades to an un-checksummed pointer when
        huggingface_hub is unavailable or the path cannot be read (a private or
        nonexistent repo)."""
        if not checksum:
            return [ResolvedReference(None, uri)]
        fs = self._fs()
        if fs is None:
            return [ResolvedReference(None, uri)]
        path = self._path(uri)
        try:
            info = fs.info(path)
        except Exception:
            return [ResolvedReference(None, uri)]
        if info.get("type") == "directory":
            prefix = path if path.endswith("/") else f"{path}/"
            try:
                children = sorted(fs.find(path, detail=True).items())
            except Exception:
                return [ResolvedReference(None, uri)]
            entries: list[ResolvedReference] = []
            for child_path, child in children:
                if child.get("type") != "file":
                    continue
                entries.append(
                    ResolvedReference(
                        relkey=_relative_key(child_path, prefix),
                        uri=f"hf://{quote(child_path, safe='/')}",
                        size=child.get("size"),
                        digest=self._checksum(child),
                    )
                )
                _within_max(len(entries), max_objects, uri)
            return entries
        return [
            ResolvedReference(
                None, uri, size=info.get("size"), digest=self._checksum(info)
            )
        ]

    def fetch(self, uri, dest):
        """Download the Hub file into `dest`; raise if huggingface_hub is
        unavailable."""
        fs = self._fs()
        if fs is None:
            raise RuntimeError(
                "Downloading an hf:// reference needs huggingface_hub with fsspec."
            )
        fs.get_file(self._path(uri), str(dest))

    def hint(self):
        """Shown when the Hub file exposed no LFS sha256, blob id, or xet hash."""
        return "Check that the hf:// path exists and is readable (log in for a private repo)."

    def _fs(self):
        """An `HfFileSystem`, or None if huggingface_hub lacks fsspec support."""
        hub = _import("huggingface_hub")
        if hub is None:
            return None
        try:
            return hub.HfFileSystem()
        except AttributeError:
            return None

    @staticmethod
    def _path(uri: str) -> str:
        """Strip the `hf://` scheme and percent-decode the remainder to the
        repo-relative path HfFileSystem uses."""
        raw = uri[len("hf://") :] if uri.startswith("hf://") else uri
        return unquote(raw)

    @staticmethod
    def _checksum(info: dict) -> Sha256Digest | ETag | None:
        """Pick a stable checksum from an HfFileSystem info dict: the LFS sha256
        if present, else the git blob id or xet hash (opaque provider tokens,
        typed like an ETag)."""
        lfs = info.get("lfs")
        if isinstance(lfs, dict) and lfs.get("sha256"):
            return Sha256Digest(lfs["sha256"])
        for key in ("blob_id", "xet_hash"):
            if info.get(key):
                return ETag(str(info[key]))
        return None


def _import(module: str):
    """Import an optional module by name, returning None if it is not installed."""
    try:
        return importlib.import_module(module)
    except ImportError:
        return None


def _http_resolve(uri: str, checksum: bool) -> list[ResolvedReference]:
    """Resolve an HTTP(S) URL to a single entry via a `HEAD` request, taking its
    size from `Content-Length` and checksum from `ETag`. Returns an
    un-checksummed entry when `checksum` is False or the request fails."""
    if not checksum:
        return [ResolvedReference(None, uri)]
    try:
        response = httpx.head(uri, follow_redirects=True, timeout=httpx.Timeout(10.0))
        response.raise_for_status()
    except httpx.HTTPError:
        return [ResolvedReference(None, uri)]
    return [
        ResolvedReference(
            None,
            uri,
            size=_parse_size(response.headers.get("content-length")),
            digest=_etag_digest(response.headers.get("etag")),
        )
    ]


def _http_fetch(uri: str, dest: Path) -> None:
    """Stream an HTTP(S) URL's body into `dest`."""
    with httpx.stream(
        "GET",
        uri,
        follow_redirects=True,
        timeout=httpx.Timeout(connect=10.0, read=300.0, write=10.0, pool=10.0),
    ) as response:
        response.raise_for_status()
        _write_chunks(response.iter_bytes(), dest)


def _etag_digest(raw: str | None) -> ETag | None:
    """Normalize a provider ETag (stripping its surrounding quotes) into a
    reference digest, or None when there is no usable value."""
    cleaned = raw.strip('"') if raw else None
    return ETag(cleaned) if cleaned else None


def _within_max(count: int, max_objects: int, uri: str) -> None:
    """Raise once a prefix/directory expansion exceeds `max_objects` entries."""
    if count > max_objects:
        raise ValueError(
            f"Reference {uri!r} expands to more than {max_objects} objects; "
            "pass max_objects= to add_reference to raise the limit."
        )


def _parse_size(raw: str | None) -> int | None:
    """Parse a `Content-Length`-style header into a non-negative int, or None."""
    if raw is None:
        return None
    try:
        size = int(raw)
    except ValueError:
        return None
    return size if size >= 0 else None


def _relative_key(key: str, prefix: str) -> str:
    """The logical name of an object within an expanded prefix.

    The prefix's *directory* portion — everything up to and including its last
    "/" — is stripped from `key`, preserving any remaining subdirectory
    structure. A prefix with no "/" (a whole-bucket listing, or a leading
    filename fragment such as `logs` that also matches `logs.txt`) has no
    directory portion, so the key is kept in full. Thus a bucket-root reference
    preserves `train/data.csv`, prefix `logs` maps object `logs.txt` to
    `logs.txt` (never `.txt`), and prefix `data/` maps `data/sub/b.csv` to
    `sub/b.csv`. Falls back to the last path segment for a key that does not lie
    under the prefix's directory."""
    base = prefix[: prefix.rfind("/") + 1]
    if key.startswith(base):
        return key[len(base) :]
    return key.rsplit("/", 1)[-1]


def _write_chunks(chunks, dest: Path) -> None:
    """Write an iterable of byte chunks to `dest`."""
    with dest.open("wb") as f:
        for chunk in chunks:
            if chunk:
                f.write(chunk)


_HANDLERS: list[ReferenceHandler] = [
    FileHandler(),
    HttpHandler(),
    HfHandler(),
]


def register_reference_handler(handler: ReferenceHandler) -> None:
    """Register a custom `ReferenceHandler` for `Artifact.add_reference` URIs.

    The handler is consulted before the built-in `file://`/`http(s)://`/`hf://`
    handlers, so it can own a scheme trackio does not handle natively (`s3://`,
    `gs://`, `dvc://`, ...) or specialize a built-in one (e.g. claim an object
    store's `https://` blob endpoints ahead of the generic HTTP handler). The
    artifacts documentation includes complete handlers for the major cloud
    object stores.
    """
    if not isinstance(handler, ReferenceHandler):
        raise TypeError(
            "register_reference_handler expects a ReferenceHandler instance, "
            f"got {handler!r}."
        )
    _HANDLERS.insert(0, handler)


def _select(scheme: str, uri: str) -> ReferenceHandler:
    """Return the first registered handler that claims `uri`, raising when
    none do."""
    for handler in _HANDLERS:
        if handler.matches(scheme, uri):
            return handler
    raise ValueError(
        f"No reference handler for URI {uri!r} (scheme {scheme!r}). Built-in "
        "handlers cover file://, http(s)://, and hf://; for other schemes, "
        "register a custom ReferenceHandler with "
        "trackio.register_reference_handler() (see the artifacts documentation "
        "for S3/GCS/Azure examples)."
    )
