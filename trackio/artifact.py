import os
import shutil
import uuid
from pathlib import Path

import httpx
from huggingface_hub.utils import get_token

from trackio import cas, utils
from trackio.remote_client import _merge_client_headers, _resolve_src_url
from trackio.typehints import Manifest, Sha256Digest


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
    partial = dst.parent / f"{dst.name}.partial.{uuid.uuid4().hex}"
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
    """Fetch `GET /artifact_blob/<project>/<digest>` into the local CAS,
    verifying the streamed bytes hash to `digest`. Authenticates the request
    (HF token for a Space, write token for a self-hosted server) so blobs on a
    private remote are reachable.
    """
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


class Artifact:
    """A versioned, named bundle of files attached to a project.

    Construct an `Artifact`, add files to it with `add_file` / `add_dir`, then
    persist it with `trackio.log_artifact`. Logging freezes the artifact and
    populates its read-only `version`, `aliases`, `size`, and `manifest`.

    Args:
        name (`str`):
            Artifact name, unique within the project. Must match
            `^[A-Za-z0-9._-]+$` (letters, digits, dot, underscore, hyphen).
        type (`str`):
            Free-form category such as `"model"` or `"dataset"`, used to group
            and filter artifacts.
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
        self._logged = False
        self._version: int | None = None
        self._aliases: tuple[str, ...] = ()
        self._size: int | None = None
        self._manifest: Manifest | None = None
        self._manifest_digest: Sha256Digest | None = None
        self._project: str | None = None
        self._remote_source: dict | None = None

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
        """Total size of the artifact's files in bytes, or None if not yet logged."""
        return self._size

    @property
    def manifest(self) -> Manifest | None:
        """List of file entries (each with `path`, `digest`, and `size`)
        describing the artifact's contents, or None if not yet logged or
        fetched. Returns a fresh copy on each access."""
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

    def _build_manifest(self, project: str) -> Manifest:
        if not self._pending_files:
            raise ValueError(
                f"Artifact {self._name!r} has no files; call add_file/add_dir first."
            )
        cas.assert_manifest_paths_compatible(
            logical for _, logical in self._pending_files
        )

        entries: Manifest = []
        for src, logical in self._pending_files:
            digest, size = cas.stage_blob_into_project(src, project)
            entries.append({"path": logical, "digest": digest, "size": size})
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

        Args:
            root (`str` or `Path`, *optional*):
                Directory to write the files into. Defaults to
                `./artifacts/<project>/<name>_v<version>/`, keyed by project so
                same-named artifacts from different projects never collide, and
                by the resolved version so a moving alias like `latest` never
                leaves behind stale files from a previous version.

        Returns:
            The absolute path to the download directory, as a string.
        """
        if not self._logged:
            raise RuntimeError(
                "Cannot download an Artifact that has not been logged or fetched."
            )
        if self._manifest is None or self._project is None or self._version is None:
            raise RuntimeError("Artifact is missing manifest, project, or version.")

        if root is None:
            project = utils.canonical_project_name(self._project)
            root_path = (
                Path.cwd() / "artifacts" / project / f"{self._name}_v{self._version}"
            )
        else:
            root_path = Path(root)
        root_path.mkdir(parents=True, exist_ok=True)

        for entry in self._manifest:
            digest = cas.validate_digest(entry["digest"])
            logical = cas.validate_logical_path(entry["path"])
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

    def __repr__(self) -> str:
        parts: list[str] = [f"name={self._name!r}", f"type={self._type!r}"]
        if self._version is not None:
            parts.append(f"version=v{self._version}")
        if self._aliases:
            parts.append(f"aliases={list(self._aliases)!r}")
        return f"Artifact({', '.join(parts)})"
