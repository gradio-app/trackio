import os
import re
import shutil
import uuid
from pathlib import Path
from typing import Any

from trackio import cas
from trackio.typehints import Manifest, Sha256Digest

_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")
_READ_ONLY_ATTRS = frozenset(
    {
        "name",
        "type",
        "description",
        "metadata",
        "version",
        "aliases",
        "size",
        "manifest",
        "manifest_digest",
        "project",
    }
)


def _materialize(blob: Path, dst: Path, size: int) -> None:
    """Copy `blob` to `dst` unless an identically-sized file is already there.

    Always copies (never hardlinks) so user edits to materialized files cannot
    reach back into the content-addressed cache. The copy goes through a
    `.partial.<uuid>` temp file + atomic rename so concurrent or interrupted
    downloads never leave a torn file at `dst`.
    """
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.is_file() and dst.stat().st_size == size:
        return
    partial = dst.parent / f"{dst.name}.partial.{uuid.uuid4().hex}"
    try:
        shutil.copyfile(blob, partial)
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
    """Stream `GET /artifact_blob/<project>/<digest>` from the remote, rehash
    while writing, and atomic-rename into the local CAS.

    Resolves `remote_source` to a base URL via `_resolve_src_url`. Raises
    `FileNotFoundError` on 404; `ValueError` (via `cas.stage_blob_from_chunks`)
    if the bytes don't hash to `digest`.
    """
    import httpx

    from trackio.remote_client import _resolve_src_url

    src = remote_source.get("space_id") or remote_source.get("server_base_url")
    if not src:
        raise RuntimeError(
            "Artifact has _remote_source set but neither space_id nor "
            "server_base_url is populated."
        )
    base_url = _resolve_src_url(src).rstrip("/")
    url = f"{base_url}/artifact_blob/{project}/{digest}"
    with httpx.stream(
        "GET",
        url,
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
            max_bytes=None,
        )


class Artifact:
    """A versioned, named bundle of files attached to a project.

    Constructed mutable; `add_file` / `add_dir` accumulate pending entries.
    `Run.log_artifact` (or `trackio.log_artifact`) freezes the artifact and
    populates read-only attrs `version`, `aliases`, `size`, `manifest`.
    """

    def __init__(
        self,
        name: str,
        type: str,
        description: str | None = None,
        metadata: dict | None = None,
    ):
        if not isinstance(name, str) or not _NAME_RE.match(name):
            raise ValueError(
                f"Artifact name {name!r} must match ^[A-Za-z0-9._-]+$ "
                "(letters, digits, dot, underscore, hyphen)."
            )
        self._name = name
        self._type = type
        self._description = description
        self._metadata: dict | None = dict(metadata) if metadata else None
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
        return self._name

    @property
    def type(self) -> str:
        return self._type

    @property
    def description(self) -> str | None:
        return self._description

    @property
    def metadata(self) -> dict | None:
        return None if self._metadata is None else dict(self._metadata)

    @property
    def version(self) -> int | None:
        return self._version

    @property
    def aliases(self) -> tuple[str, ...]:
        return self._aliases

    @property
    def size(self) -> int | None:
        return self._size

    @property
    def manifest(self) -> Manifest | None:
        return None if self._manifest is None else [dict(e) for e in self._manifest]

    @property
    def manifest_digest(self) -> Sha256Digest | None:
        return self._manifest_digest

    @property
    def project(self) -> str | None:
        return self._project

    def add_file(self, local_path: str | Path, name: str | None = None) -> None:
        if self._logged:
            raise RuntimeError(
                "Cannot add files to an Artifact that has already been logged or fetched."
            )
        src = Path(local_path).resolve()
        if not src.is_file():
            raise ValueError(f"Not a regular file: {local_path}")
        logical = name if name is not None else src.name
        self._pending_files.append((src, logical))

    def add_dir(self, local_dir: str | Path, name: str | None = None) -> None:
        if self._logged:
            raise RuntimeError(
                "Cannot add files to an Artifact that has already been logged or fetched."
            )
        root = Path(local_dir).resolve()
        if not root.is_dir():
            raise ValueError(f"Not a directory: {local_dir}")
        prefix = name.rstrip("/") + "/" if name else ""
        for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
            dirnames.sort()
            for filename in sorted(filenames):
                entry = Path(dirpath) / filename
                if entry.is_symlink() or not entry.is_file():
                    continue
                rel = entry.relative_to(root).as_posix()
                self._pending_files.append((entry, prefix + rel))

    def _build_manifest(self, project: str) -> Manifest:
        if not self._pending_files:
            raise ValueError(
                f"Artifact {self._name!r} has no files; call add_file/add_dir first."
            )
        seen: set[str] = set()
        for _, logical in self._pending_files:
            if logical in seen:
                raise ValueError(f"Duplicate logical path in manifest: {logical!r}")
            seen.add(logical)

        entries: Manifest = []
        for src, logical in self._pending_files:
            digest, size = cas.hash_file(src)
            cas.stage_blob_from_file(src, digest, cas.blob_path(project, digest))
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
        """Materialize artifact files at `root/<logical_path>` for each manifest entry.

        Default `root` is `./artifacts/<name>:v<version>/` (CWD-relative),
        always named by the resolved version so a moving alias like `latest`
        never leaves stale files from a previous version in the directory.

        Returns the absolute path to `root` as a string. Idempotent: files are
        copied from the content-addressed cache and skipped on the second
        call.
        """
        if not self._logged:
            raise RuntimeError(
                "Cannot download an Artifact that has not been logged or fetched."
            )
        if self._manifest is None or self._project is None or self._version is None:
            raise RuntimeError("Artifact is missing manifest, project, or version.")

        if root is None:
            root_path = Path.cwd() / "artifacts" / f"{self._name}:v{self._version}"
        else:
            root_path = Path(root)
        root_path.mkdir(parents=True, exist_ok=True)

        for entry in self._manifest:
            digest = entry["digest"]
            logical = entry["path"]
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
            parts.append(f"version={self._version}")
        if self._aliases:
            parts.append(f"aliases={list(self._aliases)!r}")
        return f"Artifact({', '.join(parts)})"

    def __setattr__(self, key: str, value: Any) -> None:
        if key in _READ_ONLY_ATTRS:
            raise AttributeError(
                f"Artifact.{key} is read-only; set via log_artifact/use_artifact."
            )
        super().__setattr__(key, value)
