import os
import shutil
from pathlib import Path

import httpx
from huggingface_hub.utils import get_token

from trackio import cas, references, utils
from trackio.registry_storage import (
    RegistryStorage,
    parse_collection_target,
    registry_project_name,
)
from trackio.remote_client import _merge_client_headers, _resolve_src_url
from trackio.typehints import ETag, Manifest, ManifestEntry, Sha256Digest, URIStr


def _materialize(blob: Path, dst: Path, size: int) -> None:
    """Copy `blob` to `dst` unless `dst` already matches the blob's size and
    mtime.
    """
    dst.parent.mkdir(parents=True, exist_ok=True)
    blob_stat = blob.stat()
    if dst.is_file():
        dst_stat = dst.stat()
        if dst_stat.st_size == size and dst_stat.st_mtime_ns == blob_stat.st_mtime_ns:
            return
    partial = dst.parent / cas.partial_blob_name(dst.name)
    try:
        shutil.copyfile(blob, partial)
        os.utime(partial, ns=(blob_stat.st_atime_ns, blob_stat.st_mtime_ns))
        os.replace(partial, dst)
    except Exception:
        partial.unlink(missing_ok=True)
        raise


def _fetch_blob_from_remote(
    remote_source: dict,
    project: str,
    digest: Sha256Digest,
    target_path: Path,
) -> None:
    space_id = remote_source.get("space_id")
    src = space_id or remote_source.get("server_base_url")
    if not src:
        raise RuntimeError(
            "Artifact has _remote_source set but neither space_id nor "
            "server_base_url is populated."
        )
    base_url = _resolve_src_url(src).rstrip("/")
    url = f"{base_url}/artifact_blob/{utils.canonical_project_name(project)}/{digest}"
    headers = _merge_client_headers(
        get_token() if space_id else None,
        remote_source.get("write_token"),
    )
    with httpx.stream(
        "GET",
        url,
        headers=headers,
        timeout=httpx.Timeout(connect=10.0, read=300.0, write=10.0, pool=10.0),
    ) as response:
        if response.status_code == 404:
            raise FileNotFoundError(
                f"Artifact blob {digest} not available on remote at {url}"
            )
        response.raise_for_status()
        cas.stage_blob_from_chunks(
            response.iter_bytes(),
            claimed_digest=digest,
            target_path=target_path,
        )


def _materialize_reference(
    uri: str, scheme: str, dest: Path, digest: Sha256Digest | ETag | URIStr
) -> None:
    """Fetch the object at `uri` into `dest`, idempotently and atomically.

    If `dest` already exists it is left untouched and nothing is fetched:
    reference digests are opaque, so a file already present is assumed current
    (mirroring the size/mtime idempotence of `_materialize`), letting a repeated
    `download()` skip references already on disk.

    Otherwise, when a real checksum was recorded, the source is re-probed and
    compared. When the digest doesn't exist, or when it cannot be re-probed,
    the comparison is skipped and the artifact is still materialized.
    """
    if dest.is_file():
        return
    if len(digest) > 0 and digest != uri:
        try:
            resolved = references.resolve_reference(
                uri, scheme, checksum=True, max_objects=1
            )[0]
        except Exception:
            resolved = None
        current_digest = resolved.digest if resolved is not None else None
        if current_digest is not None and current_digest != digest:
            utils._emit_nonfatal_warning(
                f"Reference {uri!r} may have changed since it was logged "
                f"(recorded digest {digest}, current {current_digest})."
            )
    dest.parent.mkdir(parents=True, exist_ok=True)
    partial = dest.parent / cas.partial_blob_name(dest.name)
    try:
        references.fetch_reference(uri, scheme, partial)
        os.replace(partial, dest)
    except Exception:
        partial.unlink(missing_ok=True)
        raise


class Artifact:
    """
    A versioned, named bundle of files and references attached to a project.

    Construct an `Artifact`, add files to it with `add_file` / `add_dir`
    (bytes staged into content-addressed storage) or `add_reference` (an
    external URI recorded without copying any bytes), then persist it with
    `trackio.log_artifact`. Logging freezes the artifact and populates its
    read-only `version`, `aliases`, `size`, and `manifest`.

    Args:
        name (`str`):
            Artifact name, unique within the project. Must match
            `^[A-Za-z0-9._-]+$` (letters, digits, dot, underscore, hyphen).
        type (`str`):
            Free-form category such as `"model"` or `"dataset"`, used to group
            artifacts.
        description (`str`, *optional*):
            Human-readable description of the artifact.
        metadata (`dict`, *optional*):
            Arbitrary JSON-serializable metadata stored alongside the version.
    """

    def __init__(
        self,
        name: str,
        type: str,
        description: str | None = None,
        metadata: dict | None = None,
    ):
        cas.validate_artifact_name(name)
        self._name = name
        self._type = type
        self._description = description
        self._metadata: dict = dict(metadata) if metadata else {}
        self._pending_files: list[tuple[Path, str]] = []
        self._pending_references: list[
            tuple[str, str, Sha256Digest | ETag | URIStr, int]
        ] = []
        self._logged = False
        self._version: int | None = None
        self._aliases: tuple[str, ...] = ()
        self._size: int | None = None
        self._manifest: Manifest | None = None
        self._manifest_digest: Sha256Digest | None = None
        self._project: str | None = None
        self._remote_source: dict | None = None
        self._registry: str | None = None
        self._source_project: str | None = None
        self._source_artifact: str | None = None
        self._source_version: int | None = None

    @property
    def name(self) -> str:
        """Artifact name, unique within its project."""
        return self._name

    @property
    def type(self) -> str:
        """Free-form category such as `"model"` or `"dataset"`."""
        return self._type

    @property
    def description(self) -> str | None:
        """Human-readable description, or None if unset."""
        return self._description

    @description.setter
    def description(self, value: str | None) -> None:
        self._description = value

    @property
    def metadata(self) -> dict:
        """Live, mutable metadata dict; assignments like `art.metadata["k"] = v`
        made before logging are preserved."""
        return self._metadata

    @metadata.setter
    def metadata(self, value: dict | None) -> None:
        self._metadata = dict(value) if value else {}

    @property
    def version(self) -> str | None:
        """Version string in `"v<N>"` form (e.g. `"v3"`), or None if the
        artifact has not been logged or fetched yet."""
        return None if self._version is None else f"v{self._version}"

    @property
    def aliases(self) -> tuple[str, ...]:
        """Aliases pointing at this version, e.g. `("latest", "prod")`."""
        return self._aliases

    @property
    def size(self) -> int | None:
        """Total size in bytes of the artifact's files plus any referenced data
        whose size is known, or None if not yet logged."""
        return self._size

    @property
    def manifest(self) -> Manifest | None:
        """List of manifest entries describing the artifact's contents, or None
        if not yet logged or fetched. File entries carry `path`, `digest`, and
        `size`; reference entries carry `path`, `ref` (a URI), `size`, and a
        `digest` — a sha256 for local/LFS references, the provider's opaque ETag
        for HTTP or object-store references, or the URI itself when no checksum
        is available. Returns a fresh copy on each access."""
        return None if self._manifest is None else [dict(e) for e in self._manifest]

    @property
    def manifest_digest(self) -> Sha256Digest | None:
        """Digest over the manifest (file paths plus their content), used to
        de-duplicate re-logged content; None until logged or fetched."""
        return self._manifest_digest

    @property
    def digest(self) -> Sha256Digest | None:
        """Alias of `manifest_digest`."""
        return self._manifest_digest

    @property
    def qualified_name(self) -> str:
        """`"<project>/<name>:v<N>"` for a logged or fetched artifact."""
        if self._project is None or self._version is None:
            raise RuntimeError(
                "Artifact has no qualified name until it is logged or fetched."
            )
        return f"{self._project}/{self._name}:v{self._version}"

    @property
    def project(self) -> str | None:
        """Project the artifact belongs to, or None until logged or fetched."""
        return self._project

    @property
    def is_link(self) -> bool:
        """True if this artifact is a registry link, i.e. the pointer
        returned by `Run.link_artifact`, rather than a source artifact
        version."""
        return self._registry is not None

    @property
    def source_name(self) -> str | None:
        """Name of the source artifact version this artifact's content comes
        from. Equal to `name` unless this artifact is a registry link."""
        return self._source_artifact if self.is_link else self._name

    @property
    def source_version(self) -> str | None:
        """Version string (`"v<N>"`) of the source artifact version. Equal to
        `version` unless this artifact is a registry link."""
        if self.is_link:
            return f"v{self._source_version}"
        return self.version

    @property
    def source_project(self) -> str | None:
        """Project the source artifact version was logged in. Equal to
        `project` unless this artifact is a registry link."""
        return self._source_project if self.is_link else self._project

    @property
    def source_qualified_name(self) -> str:
        """`"<project>/<name>:v<N>"` of the source artifact version. Equal to
        `qualified_name` unless this artifact is a registry link."""
        if self.is_link:
            return (
                f"{self._source_project}/{self._source_artifact}"
                f":v{self._source_version}"
            )
        return self.qualified_name

    def wait(self, timeout: int | None = None) -> "Artifact":
        """No-op: trackio logs artifacts synchronously, so the artifact is
        already committed by the time `log_artifact` returns."""
        if not self._logged:
            raise RuntimeError(
                "Cannot wait on an Artifact that has not been logged; "
                "call log_artifact first."
            )
        return self

    def add_file(self, local_path: str | Path, name: str | None = None) -> None:
        """Stage a single file for inclusion in the artifact.

        Args:
            local_path (`str` or `Path`):
                Path to an existing regular file to add.
            name (`str`, *optional*):
                Logical path the file is stored under inside the artifact.
                Defaults to the file's basename.
        """
        if self._logged:
            raise RuntimeError(
                "Cannot add files to an Artifact that has already been logged or fetched."
            )
        src = Path(local_path).resolve()
        if not src.is_file():
            raise ValueError(f"Not a regular file: {local_path}")
        logical = cas.validate_logical_path(name if name is not None else src.name)
        self._pending_files.append((src, logical))

    def add_dir(self, local_dir: str | Path, name: str | None = None) -> None:
        """Stage every regular file under a directory, recursively.

        Symlinks are skipped.

        Args:
            local_dir (`str` or `Path`):
                Path to an existing directory whose files are added.
            name (`str`, *optional*):
                Logical path prefix for the added files. Defaults to no prefix,
                so files keep their paths relative to `local_dir`.
        """
        if self._logged:
            raise RuntimeError(
                "Cannot add files to an Artifact that has already been logged or fetched."
            )
        root = Path(local_dir).resolve()
        if not root.is_dir():
            raise ValueError(f"Not a directory: {local_dir}")
        prefix = cas.validate_logical_path(name.rstrip("/")) + "/" if name else ""
        for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
            dirnames.sort()
            for filename in sorted(filenames):
                entry = Path(dirpath) / filename
                if entry.is_symlink() or not entry.is_file():
                    continue
                rel = entry.relative_to(root).as_posix()
                logical = cas.validate_logical_path(prefix + rel)
                self._pending_files.append((entry, logical))

    def add_reference(
        self,
        uri: str,
        name: str | None = None,
        checksum: bool = True,
        max_objects: int | None = None,
    ) -> None:
        """Stage a reference to external data, without copying any bytes.

        Unlike `add_file`/`add_dir`, a reference records the data's URI (plus,
        when available, a size and checksum) *without staging the bytes into
        the content-addressed store*. This is how you version and track
        lineage over large or already-durably-stored datasets that must not be
        duplicated.

        A URI that denotes a directory (`file://`, `hf://`, or a prefix
        expanded by a custom handler) is expanded into one entry per object,
        capped by `max_objects`. Reference bytes are never uploaded to a Space
        or bucket.

        The URI is stored verbatim in the artifact manifest, and manifests may
        be synced to a shared Hugging Face Dataset — so a signed URI triggers a
        warning for security reasons; please prefer the object's canonical
        unsigned URI (e.g. `s3://bucket/key`).

        Args:
            uri (`str`):
                Location of the referenced data, percent-encoded (build local
                URIs with `pathlib.Path.as_uri()`). `file://`, `http(s)://`,
                and `hf://` are resolved and fetched natively; any other scheme
                (`s3://`, `gs://`, Azure blob URLs, ...) requires a custom
                `ReferenceHandler` registered via
                `trackio.register_reference_handler` — see the artifacts
                documentation for complete examples — and raises otherwise.
            name (`str`, *optional*):
                Logical path the reference is stored under. Defaults to the last
                segment of `uri`; for an expanded prefix (ending with /) it is the
                prefix under which each object's relative path is nested.
            checksum (`bool`, *optional*, defaults to `True`):
                When `True`, probes the source to derive its size and a
                checksum (and to expand a directory/prefix): `file://` is
                stream-hashed to a sha256, `hf://` uses its LFS sha256 or git
                blob id, and `http(s)://` uses the server `ETag`. This may read
                the filesystem or make network requests. When no checksum can
                be obtained for a *remote* source (e.g. no ETag), the URI
                itself is used as the `digest` and a warning is emitted. A
                local `file://` path that does not exist instead raises. Pass
                `checksum=False` to skip remote probing entirely.
            max_objects (`int`, *optional*):
                Cap on how many objects a directory/prefix expands into (default
                10,000); exceeding it raises.
        """
        if self._logged:
            raise RuntimeError(
                "Cannot add references to an Artifact that has already been "
                "logged or fetched."
            )
        scheme, normalized = references.validate_reference_uri(uri)
        if references.looks_signed(normalized):
            utils._emit_nonfatal_warning(
                f"Reference {uri!r} looks like a signed URL, and the full URI "
                "(embedded credential included) is stored in the artifact "
                "manifest, which may be synced to a shared HF Dataset. Prefer "
                "the object's canonical unsigned URI (e.g. s3://bucket/key or "
                "the URL without its signed query string)."
            )
        cap = references.DEFAULT_MAX_OBJECTS if max_objects is None else max_objects
        resolved = references.resolve_reference(normalized, scheme, checksum, cap)
        if not resolved:
            raise ValueError(f"Reference URI {uri!r} matched no objects.")
        used_uri_fallback = False
        name_prefix = f"{name.rstrip('/')}/" if name is not None else ""
        for entry in resolved:
            if entry.relkey is None:
                logical = self._reference_logical_name(name, entry.uri, uri)
            else:
                logical = cas.validate_logical_path(name_prefix + entry.relkey)
            ref_digest: Sha256Digest | ETag | URIStr | None = entry.digest
            if ref_digest is None:
                ref_digest = URIStr(entry.uri)
                used_uri_fallback = True
            ref_size = 0 if entry.size is None else entry.size
            self._pending_references.append((logical, entry.uri, ref_digest, ref_size))
        if checksum and used_uri_fallback:
            utils._emit_nonfatal_warning(
                f"Reference {uri!r} was recorded without a content checksum, so its "
                "version identity is its URI; re-logging changed content at the same "
                "location will reuse the existing version instead of creating a new "
                f"one. {references.checksum_hint(scheme, normalized)}"
            )

    @staticmethod
    def _reference_logical_name(name: str | None, resolved_uri: str, uri: str) -> str:
        if name is not None:
            return cas.validate_logical_path(name)
        derived = references.default_reference_name(resolved_uri)
        if not derived:
            raise ValueError(
                f"Could not derive a name from URI {uri!r}; pass name= explicitly."
            )
        return cas.validate_logical_path(derived)

    def _build_manifest(self, project: str) -> Manifest:
        if not self._pending_files and not self._pending_references:
            raise ValueError(
                f"Artifact {self._name!r} has no files or references; "
                "call add_file/add_dir/add_reference first."
            )
        cas.assert_manifest_paths_compatible(
            [logical for _, logical in self._pending_files]
            + [logical for logical, *_ in self._pending_references]
        )

        entries: Manifest = []
        for src, logical in self._pending_files:
            digest, size = cas.stage_blob_into_project(src, project)
            entries.append({"path": logical, "digest": digest, "size": size})
        for logical, uri, ref_digest, ref_size in self._pending_references:
            entry: ManifestEntry = {
                "path": logical,
                "ref": uri,
                "digest": ref_digest,
                "size": ref_size,
            }
            entries.append(entry)
        return entries

    def _hydrate_from_db(
        self,
        *,
        project: str,
        version: int,
        aliases: list[str],
        manifest: Manifest,
        manifest_digest: Sha256Digest,
        size_bytes: int,
        description: str | None = None,
        metadata: dict | None = None,
    ) -> None:
        if description is not None:
            self._description = description
        if metadata is not None:
            self._metadata = dict(metadata)
        self._project = project
        self._version = version
        self._aliases = tuple(aliases)
        self._manifest = [dict(e) for e in manifest]
        self._manifest_digest = manifest_digest
        self._size = size_bytes
        self._logged = True

    def download(self, root: str | Path | None = None) -> str:
        """Materialize the artifact's files into a local directory.

        Files are copied from Trackio's content-addressed cache (and fetched
        from the remote when missing locally), so repeated calls are cheap and
        idempotent.

        Reference entries added via `add_reference` are fetched here too: the
        object at each reference URI is downloaded into the directory (via the
        bundled `httpx` for `http(s)://`, `huggingface_hub` for `hf://`, and
        the registered custom `ReferenceHandler` for any other scheme). Each
        object is written atomically and calls are idempotent. Because reference digests
        are opaque (a provider ETag or the URI itself), a present file is assumed
        current and is not re-verified against the source, and a source whose
        re-probed checksum no longer matches the recorded one is downloaded
        anyway with a warning. Downloading can transfer a large amount of data;
        to work with the URIs without downloading, read them from the `references`
        property or `get_entry_uri` instead. A missing source, an unreachable
        server, or a scheme with no registered handler raises.

        Args:
            root (`str` or `Path`, *optional*):
                Directory to write the files into. Defaults to
                `./.trackio/artifact-downloads/<project>/<name>_v<version>/`,
                keyed by project so same-named artifacts from different projects
                never collide, and by the resolved version so a moving alias
                like `latest` never leaves behind stale files from a previous
                version.

        Returns:
            The absolute path to the download directory, as a string.
        """
        if not self._logged:
            raise RuntimeError(
                "Cannot download an Artifact that has not been logged or fetched."
            )
        if self.is_link:
            raise NotImplementedError(
                "Downloading through a registry location is not supported "
                "yet; it arrives with registry resolution. Download the "
                f"source artifact version ({self.source_qualified_name}) "
                "instead."
            )
        if self._manifest is None or self._project is None or self._version is None:
            raise RuntimeError("Artifact is missing manifest, project, or version.")

        if root is None:
            project = utils.canonical_project_name(self._project)
            root_path = (
                Path.cwd()
                / ".trackio"
                / "artifact-downloads"
                / project
                / f"{self._name}_v{self._version}"
            )
        else:
            root_path = Path(root)
        root_path.mkdir(parents=True, exist_ok=True)

        for entry in self._manifest:
            logical = cas.validate_logical_path(entry["path"])
            if references.is_reference_entry(entry):
                scheme, uri = references.validate_reference_uri(entry["ref"])
                _materialize_reference(
                    uri, scheme, root_path / logical, entry["digest"]
                )
                continue
            digest = cas.validate_digest(entry["digest"])
            blob = cas.blob_path(self._project, digest)
            if not blob.is_file():
                if self._remote_source is None:
                    raise FileNotFoundError(
                        f"Artifact blob {digest} not available locally or "
                        "remotely. The producer machine may not have shipped "
                        "this blob yet."
                    )
                _fetch_blob_from_remote(
                    self._remote_source, self._project, digest, blob
                )
            _materialize(blob, root_path / logical, entry["size"])

        return str(root_path)

    def link(self, target_path: str, aliases: list[str] | None = None) -> "Artifact":
        """Link this artifact version into a registry collection.

        A link is a pointer to this version: no files are copied. See
        `Run.link_artifact` for the full semantics (collection versioning,
        aliases, and the returned linked artifact).

        The artifact must already be logged or fetched; unlike
        `Run.link_artifact`, this does not log a draft artifact for you, and
        the link records no publishing run. Linking is local for now: an
        artifact fetched from a Space or a self-hosted server raises
        `NotImplementedError`.

        Args:
            target_path (`str`):
                The collection to link into, as
                `"registry-<registry>/<collection>"`. The registry must
                already exist.
            aliases (`list[str]`, *optional*):
                Aliases to place on the linked version. `latest` is managed
                automatically; passing it is a no-op.

        Returns:
            The linked artifact at its registry location.
        """
        if not self._logged:
            raise RuntimeError(
                "Cannot link an Artifact that has not been logged or fetched. "
                "Log it first with log_artifact, or fetch a version with "
                "use_artifact, then link the result."
            )
        registry, collection = parse_collection_target(target_path)
        return self._link_version(registry, collection, aliases, None, None)

    def unlink(self) -> None:
        """Remove this registry link.

        Call this on the linked artifact returned by `link` or
        `Run.link_artifact`, not on a source artifact version. The source
        artifact and its files are untouched; only the collection membership
        is removed. Aliases pointing at the link go with it, and the
        collection version number is never reused. Unlinking is local for
        now.
        """
        if not self.is_link:
            raise ValueError(
                "unlink() removes a registry link; call it on the linked "
                "artifact returned by link() or Run.link_artifact, not on a "
                "source artifact version."
            )
        RegistryStorage.unlink(self._registry, self._name, self._version)

    def _resolve_link_source(self) -> tuple[str, str, int]:
        """Coordinates ``(project, artifact, version)`` a link operation
        records for this artifact. A registry-linked artifact links its
        source version directly, so links never chain."""
        if self.is_link:
            return self._source_project, self._source_artifact, self._source_version
        return self._project, self._name, self._version

    def _link_version(
        self,
        registry: str,
        collection: str,
        aliases: list[str] | None,
        run_name: str | None,
        run_id: str | None,
    ) -> "Artifact":
        """Link this logged artifact version into `registry`/`collection` and
        return the linked artifact hydrated at its registry location."""
        source_project, source_artifact, source_version = self._resolve_link_source()
        if self._remote_source is not None:
            raise NotImplementedError(
                "Linking an artifact fetched from a Space or a self-hosted "
                "server is not supported yet; it arrives with the registry "
                "server endpoints."
            )
        manifest = self._manifest or []
        link = RegistryStorage.link_artifact_version(
            registry=registry,
            collection=collection,
            type=self._type,
            source_project=source_project,
            source_artifact=source_artifact,
            source_version=source_version,
            aliases=aliases,
            run_name=run_name,
            run_id=run_id,
        )
        return Artifact._from_registry_link(
            registry,
            collection,
            {
                **link,
                "source": {
                    "type": self._type,
                    "description": self._description,
                    "metadata": self._metadata,
                    "manifest": manifest,
                    "manifest_digest": self._manifest_digest,
                    "size_bytes": self._size or 0,
                },
            },
        )

    @classmethod
    def _from_registry_link(
        cls, registry: str, collection: str, link: dict
    ) -> "Artifact":
        """Build the linked artifact at its registry location from a local
        link record."""
        source = link["source"]
        linked = cls(
            name=collection,
            type=source["type"],
            description=source.get("description"),
            metadata=source.get("metadata"),
        )
        linked._hydrate_from_db(
            project=registry_project_name(registry),
            version=int(link["collection_version"]),
            aliases=link["aliases"],
            manifest=source["manifest"],
            manifest_digest=source["manifest_digest"],
            size_bytes=int(source["size_bytes"]),
        )
        linked._registry = registry
        linked._source_project = link["source_project"]
        linked._source_artifact = link["source_artifact"]
        linked._source_version = int(link["source_version"])
        return linked

    @property
    def references(self) -> list[dict]:
        """Reference entries (each with `path`, `ref`, `size`, and a `digest`)
        recorded via `add_reference`. These point at external data not stored in
        Trackio; read them to work with the URIs without downloading (unlike
        `download()`, which fetches them). Returns a fresh copy on each access;
        empty if the artifact has no references or has not been logged yet."""
        if self._manifest is None:
            return []
        return [dict(e) for e in self._manifest if references.is_reference_entry(e)]

    def get_entry_uri(self, name: str) -> str | None:
        """Return the URI recorded for the reference entry at logical path
        `name`, or None if there is no reference entry with that name."""
        if self._manifest is None:
            return None
        for entry in self._manifest:
            if entry.get("path") == name and references.is_reference_entry(entry):
                return entry["ref"]
        return None

    def __repr__(self) -> str:
        parts: list[str] = [f"name={self._name!r}", f"type={self._type!r}"]
        if self._version is not None:
            parts.append(f"version=v{self._version}")
        if self._aliases:
            parts.append(f"aliases={list(self._aliases)!r}")
        return f"Artifact({', '.join(parts)})"
