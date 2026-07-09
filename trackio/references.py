"""External artifact references, and the per-scheme handlers that resolve and
fetch them without staging any bytes at log time.

Each supported scheme is a `ReferenceHandler`: `matches` claims a URI, `resolve`
probes it for size + a checksum (expanding a directory or object prefix into one
entry per object), and `fetch` downloads a single object. `_select` returns the
first handler whose `matches` is true, falling back to `TrackingHandler` (which
records an opaque pointer and refuses to download). Cloud SDKs are optional and
imported lazily inside the handler that needs them, so trackio's core dependency
set is unchanged: a reference whose client is unavailable resolves without a
checksum and only raises if you try to `fetch` it. An Azure blob whose SDK or
credentials are absent is the exception — because blob URLs are also valid
HTTPS URLs, a single blob falls back to a plain HTTP probe and download.

Object keys are carried through URIs percent-encoded (cloud keys may contain
spaces, which `validate_reference_uri` rejects): `resolve` encodes the keys it
discovers when synthesizing per-object ref URIs, and `fetch` decodes the key
back before handing it to the SDK, so a manifest ref always round-trips.

This module also defines the dependency-light reference primitives —
`validate_reference_uri`, `local_path_from_file_uri`, `default_reference_name`,
the `looks_signed` credential heuristic, and the `is_reference_entry` manifest
discriminator — shared by the artifact, storage, server, and CLI layers.

To add a scheme, write a `ReferenceHandler` subclass and register it in
`_HANDLERS` (before `HttpHandler` if it is a specialization of `https://`).
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
_AZURE_BLOB_SUFFIX = ".blob.core.windows.net"


def validate_reference_uri(uri: str) -> tuple[str, str]:
    """Validate an external reference URI and return `(scheme, uri)`.

    The URI must be a non-empty string carrying a scheme and free of NUL and
    whitespace (spaces and other special characters must be percent-encoded).
    The scheme is not restricted: `file://`, `http(s)://`, `hf://`, `s3://`,
    `gs://`, and Azure blob URLs are resolved and fetched natively, while any
    other scheme is recorded as an opaque, un-checksummed pointer. The URI is
    returned unchanged. Use `local_path_from_file_uri` to resolve a `file://`
    URI to a local filesystem path.
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
    for `file://` and LFS `hf://`, or the provider's opaque ETag for cloud/HTTP
    references; None when unavailable (the caller then falls back to the URI)."""

    relkey: str | None
    uri: str
    size: int | None = None
    digest: Sha256Digest | ETag | None = None


class ReferenceHandler(ABC):
    """Resolves and fetches references for one family of URI schemes.

    Concrete handlers are stateless and instantiated once in `_HANDLERS`. Any
    third-party client is imported and constructed lazily (see each handler's
    private accessor), so importing this module never requires an optional SDK.
    """

    @abstractmethod
    def matches(self, scheme: str, uri: str) -> bool:
        """Whether this handler owns `uri`. `_select` tries handlers in order and
        takes the first match, so a specialization (e.g. Azure over generic HTTP)
        must be registered ahead of the handler it narrows."""

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
    """Resolve `uri` to one or more objects. Never raises for a missing optional
    client or an unreachable remote (those resolve un-checksummed); raises for a
    missing local `file://` path or an expansion exceeding `max_objects`."""
    return _select(scheme, uri).resolve(uri, checksum, max_objects)


def fetch_reference(uri: str, scheme: str, dest: Path) -> None:
    """Download the single object at `uri` to `dest`. Raises if the scheme is
    not fetchable or a required client is unavailable."""
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
            for path in sorted(local.rglob("*")):
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
    unreachable) resolves the reference un-checksummed. Registered after the more
    specific `AzureHandler`."""

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


class AzureHandler(ReferenceHandler):
    """Azure Blob Storage objects, addressed as
    `https://<account>.blob.core.windows.net/<container>/<blob>`.

    Because they are `https://` URLs, this handler is registered before
    `HttpHandler` and claims them by host suffix. Size and an ETag come from the
    blob properties (a container prefix is expanded); both use the optional
    `azure-storage-blob` + `azure-identity` packages (`trackio[azure]`). When
    those packages or credentials are unavailable, a single blob falls back to a
    plain HTTPS HEAD/GET (like `HttpHandler`), so a public blob still resolves
    with a size + ETag and downloads; a container prefix cannot be listed over
    HTTP and degrades to an un-checksummed pointer."""

    extra = "azure"

    def matches(self, scheme, uri):
        """Owns `https://` URLs whose host is an Azure Blob endpoint."""
        return scheme in ("http", "https") and urlsplit(uri).netloc.lower().endswith(
            _AZURE_BLOB_SUFFIX
        )

    def resolve(self, uri, checksum, max_objects):
        """Read blob properties for a single object, or list a container prefix
        into one entry per blob. A single blob falls back to an HTTP probe when
        the SDK/credentials are unavailable; any other failure (a container that
        cannot be listed, a missing blob, an auth error) degrades to an
        un-checksummed pointer."""
        account_url, container, blob_name = self._split(uri)
        is_object = bool(blob_name) and not blob_name.endswith("/")
        if is_object and not checksum:
            return [ResolvedReference(None, uri)]
        service = self._service(account_url)
        if is_object:
            if service is None:
                return _http_resolve(uri, checksum)
            try:
                props = service.get_blob_client(
                    container, blob_name
                ).get_blob_properties()
            except Exception:
                return [ResolvedReference(None, uri)]
            return [
                ResolvedReference(
                    None, uri, size=props.size, digest=_etag_digest(props.etag)
                )
            ]
        if service is None:
            return [ResolvedReference(None, uri)]
        entries: list[ResolvedReference] = []
        try:
            for blob in service.get_container_client(container).list_blobs(
                name_starts_with=blob_name
            ):
                if blob.name.endswith("/"):
                    continue
                entries.append(
                    ResolvedReference(
                        relkey=_relative_key(blob.name, blob_name),
                        uri=f"{account_url}/{container}/{quote(blob.name, safe='/')}",
                        size=blob.size,
                        digest=(
                            _etag_digest(getattr(blob, "etag", None))
                            if checksum
                            else None
                        ),
                    )
                )
                _within_max(len(entries), max_objects, uri)
        except ValueError:
            raise
        except Exception:
            return [ResolvedReference(None, uri)]
        return entries

    def fetch(self, uri, dest):
        """Download the blob into `dest` via the Azure SDK, or a plain HTTPS GET
        when the SDK or credentials are unavailable."""
        account_url, container, blob_name = self._split(uri)
        service = self._service(account_url)
        if service is None:
            _http_fetch(uri, dest)
            return
        downloader = service.get_blob_client(container, blob_name).download_blob()
        with dest.open("wb") as f:
            downloader.readinto(f)

    def hint(self):
        """Shown when neither the Azure SDK nor a public HTTP probe yielded an ETag."""
        return (
            f"Install trackio[{self.extra}] and configure credentials to "
            "checksum it by content."
        )

    def _service(self, account_url):
        """A `BlobServiceClient` using default credentials, or None if the Azure
        SDK is not installed or a client cannot be constructed."""
        blob = _import("azure.storage.blob")
        identity = _import("azure.identity")
        if blob is None or identity is None:
            return None
        try:
            return blob.BlobServiceClient(
                account_url, credential=identity.DefaultAzureCredential()
            )
        except Exception:
            return None

    @staticmethod
    def _split(uri: str) -> tuple[str, str, str]:
        """Split an Azure blob URL into (account_url, container, blob_name),
        decoding the percent-encoded blob name. A URL with no blob component (an
        account/container root) yields an empty blob_name, which `resolve` treats
        as a container-level prefix expansion."""
        parts = urlsplit(uri)
        segments = parts.path.lstrip("/").split("/", 1)
        container = segments[0]
        blob_name = unquote(segments[1]) if len(segments) > 1 else ""
        return f"{parts.scheme}://{parts.netloc}", container, blob_name


class S3Handler(ReferenceHandler):
    """Amazon S3 objects (`s3://bucket/key`).

    Size and an ETag come from a `head_object` call (a prefix is expanded with a
    `list_objects_v2` paginator); both need the optional `boto3` package
    (`trackio[s3]`). S3 multipart-upload ETags are not MD5s, but trackio treats
    every reference digest as an opaque token, so that is fine."""

    extra = "s3"

    def matches(self, scheme, uri):
        """Owns `s3://` URIs."""
        return scheme == "s3"

    def resolve(self, uri, checksum, max_objects):
        """HEAD a single object for size + ETag, else paginate the prefix into one
        entry per object. Degrades to an un-checksummed pointer when boto3 is
        unavailable, the object cannot be headed, or the listing fails."""
        parts = urlsplit(uri)
        bucket, key = parts.netloc, unquote(parts.path.lstrip("/"))
        is_object = bool(key) and not key.endswith("/")
        if is_object and not checksum:
            return [ResolvedReference(None, uri)]
        client = self._client()
        if client is None:
            return [ResolvedReference(None, uri)]
        if is_object:
            try:
                head = client.head_object(Bucket=bucket, Key=key)
            except Exception:
                return [ResolvedReference(None, uri)]
            return [
                ResolvedReference(
                    None,
                    uri,
                    size=int(head["ContentLength"]),
                    digest=_etag_digest(head.get("ETag")),
                )
            ]
        entries: list[ResolvedReference] = []
        try:
            for page in client.get_paginator("list_objects_v2").paginate(
                Bucket=bucket, Prefix=key
            ):
                for obj in page.get("Contents", []):
                    obj_key = obj["Key"]
                    if obj_key.endswith("/"):
                        continue
                    entries.append(
                        ResolvedReference(
                            relkey=_relative_key(obj_key, key),
                            uri=f"s3://{bucket}/{quote(obj_key, safe='/')}",
                            size=int(obj["Size"]),
                            digest=(
                                _etag_digest(obj.get("ETag")) if checksum else None
                            ),
                        )
                    )
                    _within_max(len(entries), max_objects, uri)
        except ValueError:
            raise
        except Exception:
            return [ResolvedReference(None, uri)]
        return entries

    def fetch(self, uri, dest):
        """Download the object into `dest`; raise if boto3 is unavailable."""
        client = self._client()
        if client is None:
            raise RuntimeError(
                "Downloading this reference needs the 'boto3' package; install "
                f"trackio[{self.extra}]."
            )
        parts = urlsplit(uri)
        key = unquote(parts.path.lstrip("/"))
        with dest.open("wb") as f:
            client.download_fileobj(parts.netloc, key, f)

    def hint(self):
        """Shown when boto3 is absent or the object exposed no ETag."""
        return (
            f"Install trackio[{self.extra}] and configure credentials to "
            "checksum it by content."
        )

    def _client(self):
        """An S3 client, or None if boto3 is not installed or a client cannot be
        constructed (e.g. no region configured)."""
        boto3 = _import("boto3")
        if boto3 is None:
            return None
        try:
            return boto3.client("s3")
        except Exception:
            return None


class GcsHandler(ReferenceHandler):
    """Google Cloud Storage objects (`gs://bucket/key`).

    Size and an ETag come from the blob metadata (a prefix is expanded); both
    need the optional `google-cloud-storage` package (`trackio[gcs]`)."""

    extra = "gcs"

    def matches(self, scheme, uri):
        """Owns `gs://` URIs."""
        return scheme == "gs"

    def resolve(self, uri, checksum, max_objects):
        """Read blob metadata for a single object, or list a prefix into one entry
        per blob. Degrades to an un-checksummed pointer when the SDK/credentials
        are unavailable, the object is missing, or the listing fails."""
        parts = urlsplit(uri)
        bucket, key = parts.netloc, unquote(parts.path.lstrip("/"))
        is_object = bool(key) and not key.endswith("/")
        if is_object and not checksum:
            return [ResolvedReference(None, uri)]
        client = self._client()
        if client is None:
            return [ResolvedReference(None, uri)]
        if is_object:
            try:
                blob = client.bucket(bucket).get_blob(key)
            except Exception:
                return [ResolvedReference(None, uri)]
            if blob is None:
                return [ResolvedReference(None, uri)]
            return [
                ResolvedReference(
                    None, uri, size=blob.size, digest=_etag_digest(blob.etag)
                )
            ]
        entries: list[ResolvedReference] = []
        try:
            for blob in client.list_blobs(bucket, prefix=key):
                if blob.name.endswith("/"):
                    continue
                entries.append(
                    ResolvedReference(
                        relkey=_relative_key(blob.name, key),
                        uri=f"gs://{bucket}/{quote(blob.name, safe='/')}",
                        size=blob.size,
                        digest=_etag_digest(blob.etag) if checksum else None,
                    )
                )
                _within_max(len(entries), max_objects, uri)
        except ValueError:
            raise
        except Exception:
            return [ResolvedReference(None, uri)]
        return entries

    def fetch(self, uri, dest):
        """Download the object into `dest`; raise if the SDK is unavailable."""
        client = self._client()
        if client is None:
            raise RuntimeError(
                "Downloading this reference needs the 'google-cloud-storage' package; "
                f"install trackio[{self.extra}]."
            )
        parts = urlsplit(uri)
        key = unquote(parts.path.lstrip("/"))
        client.bucket(parts.netloc).blob(key).download_to_filename(str(dest))

    def hint(self):
        """Shown when the GCS SDK is absent or the blob exposed no ETag."""
        return (
            f"Install trackio[{self.extra}] and configure credentials to "
            "checksum it by content."
        )

    def _client(self):
        """A GCS client, or None if google-cloud-storage is not installed or no
        credentials are available to construct it."""
        storage = _import("google.cloud.storage")
        if storage is None:
            return None
        try:
            return storage.Client()
        except Exception:
            return None


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


class TrackingHandler(ReferenceHandler):
    """Fallback for schemes no other handler owns: record the URI as an opaque
    pointer, and refuse to download it. Selected explicitly by `_select`, so its
    `matches` always returns False."""

    def matches(self, scheme, uri):
        """Never matches; `_select` uses this handler only as the explicit fallback."""
        return False

    def resolve(self, uri, checksum, max_objects):
        """Record the URI verbatim, with no size or checksum."""
        return [ResolvedReference(None, uri)]

    def fetch(self, uri, dest):
        """Always raise: an opaque-pointer scheme has no download mechanism."""
        raise ValueError(
            f"Cannot download reference {uri!r}: its scheme is not supported for "
            "retrieval."
        )

    def hint(self):
        """Shown for an unrecognized scheme, recordable only as an opaque pointer."""
        return (
            "This scheme cannot be downloaded; the reference is recorded as an "
            "opaque pointer."
        )


def _import(module: str):
    """Import an optional module by name, returning None if it is not installed."""
    try:
        return importlib.import_module(module)
    except ImportError:
        return None


def _http_resolve(uri: str, checksum: bool) -> list[ResolvedReference]:
    """Resolve an HTTP(S) URL to a single entry via a `HEAD` request, taking its
    size from `Content-Length` and checksum from `ETag`. Returns an
    un-checksummed entry when `checksum` is False or the request fails. Shared by
    `HttpHandler` and the `AzureHandler` public-blob fallback."""
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
    """Stream an HTTP(S) URL's body into `dest`. Shared by `HttpHandler` and the
    `AzureHandler` public-blob fallback."""
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
    AzureHandler(),
    HttpHandler(),
    S3Handler(),
    GcsHandler(),
    HfHandler(),
]
_FALLBACK: ReferenceHandler = TrackingHandler()


def _select(scheme: str, uri: str) -> ReferenceHandler:
    """Return the first registered handler that claims `uri`, or the
    `TrackingHandler` fallback when none do."""
    for handler in _HANDLERS:
        if handler.matches(scheme, uri):
            return handler
    return _FALLBACK
