"""A registry stored in a Hugging Face bucket.

A bucket-backed registry needs no Space and no server: every writer talks to
the bucket directly with its own Hugging Face credentials, which is what lets a
run that logs to a Space publish into an org-wide catalog.

Object storage offers no compare-and-swap, so a shared SQLite database (or a
shared state file) cannot be safely read-modify-written by two machines — the
second writer would silently overwrite the first. What it does offer is writing
objects under unique keys, so the registry's append-only event log is the stored
form:

    trackio/registries/<registry>/registry.json           name, description, created_at
    trackio/registries/<registry>/events/<event_uid>.json  one immutable object per mutation

State is a fold of that log, materialized into a local projection database
(`~/.cache/huggingface/trackio/registry-cache/<bucket>/<registry>.db`) by
`RegistryStorage`'s reducer — the same reducer the local backend uses, so both
backends agree by construction. The projection is a cache: deleting it costs a
re-fold, never data.

Two consequences of assigning versions during the fold rather than at write
time, both intentional: concurrent links are ordered by `event_uid`
(timestamp, then writer, then sequence), and a version number a writer reports
can be superseded once a concurrent writer's events are folded in. Alias moves,
including `latest`, are last-writer-wins under the same order.
"""

import sqlite3
import tempfile
from pathlib import Path

import huggingface_hub
import orjson
from huggingface_hub.errors import BucketNotFoundError

from trackio import cas
from trackio.bucket_storage import _list_bucket_file_paths, create_bucket_if_not_exists
from trackio.registry_storage import (
    RegistryStorage,
    new_event,
    validate_collection_name,
    validate_collection_type,
    validate_registry_name,
)
from trackio.utils import TRACKIO_DIR

REGISTRIES_BUCKET_PREFIX = "trackio/registries"
MANIFEST_FILENAME = "registry.json"


def _registry_prefix(registry: str) -> str:
    return f"{REGISTRIES_BUCKET_PREFIX}/{registry}"


def _manifest_path(registry: str) -> str:
    return f"{_registry_prefix(registry)}/{MANIFEST_FILENAME}"


def _events_prefix(registry: str) -> str:
    return f"{_registry_prefix(registry)}/events"


def _event_path(registry: str, event_uid: str) -> str:
    return f"{_events_prefix(registry)}/{event_uid}.json"


def _bucket_slug(bucket_id: str) -> str:
    return bucket_id.replace("/", "--")


class BucketRegistryStorage:
    """The `RegistryStorage` operations, backed by a bucket instead of a local
    project database. Reads answer from the local projection after refreshing it
    from the bucket; writes derive their outcome against that projection, upload
    the resulting event, and only then commit it locally, so a failed upload
    leaves nothing behind."""

    def __init__(self, bucket_id: str):
        self.bucket_id = bucket_id

    def _token(self) -> str | None:
        return huggingface_hub.utils.get_token()

    def cache_db_path(self, registry: str) -> Path:
        validate_registry_name(registry)
        return (
            TRACKIO_DIR
            / "registry-cache"
            / _bucket_slug(self.bucket_id)
            / f"{registry}.db"
        )

    def _read_manifest(self, registry: str) -> dict | None:
        """The registry's manifest object, or None when the registry does not
        exist. Its presence — not the presence of any event — is what makes a
        registry exist, mirroring the local creation marker."""
        validate_registry_name(registry)
        remote_path = _manifest_path(registry)
        try:
            paths = _list_bucket_file_paths(
                self.bucket_id, prefix=_registry_prefix(registry)
            )
        except BucketNotFoundError:
            return None
        if remote_path not in paths:
            return None
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            local = Path(tmpdir) / MANIFEST_FILENAME
            huggingface_hub.download_bucket_files(
                self.bucket_id,
                files=[(remote_path, str(local))],
                token=self._token(),
            )
            if not local.is_file():
                return None
            return orjson.loads(local.read_bytes())

    def _upload_objects(self, objects: list[tuple[bytes, str]]) -> None:
        huggingface_hub.batch_bucket_files(
            self.bucket_id, add=objects, token=self._token()
        )

    def _remote_event_uids(self, registry: str) -> list[str]:
        prefix = _events_prefix(registry)
        try:
            paths = _list_bucket_file_paths(self.bucket_id, prefix=prefix)
        except BucketNotFoundError:
            return []
        return sorted(Path(p).stem for p in paths if p.endswith(".json"))

    def _download_events(self, registry: str, event_uids: list[str]) -> list[dict]:
        if not event_uids:
            return []
        events = []
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            files = [
                (_event_path(registry, uid), str(Path(tmpdir) / f"{uid}.json"))
                for uid in event_uids
            ]
            huggingface_hub.download_bucket_files(
                self.bucket_id, files=files, token=self._token()
            )
            for _, local in files:
                local_path = Path(local)
                if local_path.is_file():
                    events.append(orjson.loads(local_path.read_bytes()))
        return events

    def _connect(self, registry: str) -> sqlite3.Connection:
        """Open the local projection, creating its schema on first use."""
        db_path = self.cache_db_path(registry)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        RegistryStorage._create_registry_tables_cursor(conn)
        conn.commit()
        return conn

    def _refresh_cursor(self, conn: sqlite3.Connection, registry: str) -> None:
        """Fold every event the bucket has and the projection does not."""
        known = {
            row[0]
            for row in conn.execute(
                "SELECT event_uid FROM registry_events WHERE event_uid IS NOT NULL"
            ).fetchall()
        }
        missing = [uid for uid in self._remote_event_uids(registry) if uid not in known]
        if not missing:
            return
        RegistryStorage.replay_events_cursor(
            conn, self._download_events(registry, missing)
        )

    def _require_registry(self, registry: str) -> dict:
        manifest = self._read_manifest(registry)
        if manifest is None:
            raise ValueError(
                f"Registry {registry!r} does not exist in bucket "
                f"{self.bucket_id!r}. Create it first with "
                f"trackio.Api().create_registry({registry!r}, "
                f"bucket_id={self.bucket_id!r})."
            )
        return manifest

    def registry_exists(self, registry: str) -> bool:
        return self._read_manifest(registry) is not None

    def get_registry(self, registry: str) -> dict | None:
        manifest = self._read_manifest(registry)
        if manifest is None:
            return None
        return {
            "name": registry,
            "description": manifest.get("description"),
            "created_at": manifest.get("created_at"),
        }

    def create_registry(self, registry: str, description: str | None = None) -> dict:
        """Create the bucket if needed (private), then write the manifest and
        the ``create`` event. Raises when the manifest already exists."""
        validate_registry_name(registry)
        if self.registry_exists(registry):
            raise ValueError(
                f"Registry {registry!r} already exists in bucket {self.bucket_id!r}."
            )
        create_bucket_if_not_exists(self.bucket_id, private=True)
        event = new_event("create", {"registry": registry})
        manifest = {
            "name": registry,
            "description": description,
            "created_at": event["ts"],
        }
        conn = self._connect(registry)
        try:
            RegistryStorage.apply_event_cursor(conn, dict(event))
            self._upload_objects(
                [
                    (orjson.dumps(manifest), _manifest_path(registry)),
                    (orjson.dumps(event), _event_path(registry, event["event_uid"])),
                ]
            )
            RegistryStorage._store_event_cursor(conn, event)
            conn.commit()
        finally:
            conn.close()
        return {"name": registry, "description": description}

    def _commit_remote_event(
        self, conn: sqlite3.Connection, registry: str, event: dict
    ) -> dict:
        """Apply `event` to the projection, upload it, then record it locally.
        The caller commits; an upload failure propagates before anything is
        committed, so the projection never claims a mutation the bucket never
        received."""
        result = RegistryStorage.apply_event_cursor(conn, event)
        self._upload_objects(
            [(orjson.dumps(event), _event_path(registry, event["event_uid"]))]
        )
        RegistryStorage._store_event_cursor(conn, event)
        return result

    def create_collection(
        self,
        registry: str,
        name: str,
        type: str,
        description: str | None = None,
    ) -> dict:
        validate_collection_name(name)
        validate_collection_type(type)
        self._require_registry(registry)
        conn = self._connect(registry)
        try:
            self._refresh_cursor(conn, registry)
            existing = RegistryStorage.get_collection_cursor(conn, name)
            if existing is not None:
                if existing["type"] != type:
                    raise ValueError(
                        f"Collection {name!r} in registry {registry!r} accepts "
                        f"type {existing['type']!r}, not {type!r}."
                    )
                created = False
                if description is not None and description != existing["description"]:
                    self._commit_remote_event(
                        conn,
                        registry,
                        new_event(
                            "update",
                            {
                                "registry": registry,
                                "collection": name,
                                "description": description,
                            },
                        ),
                    )
            else:
                created = True
                self._commit_remote_event(
                    conn,
                    registry,
                    new_event(
                        "create",
                        {
                            "registry": registry,
                            "collection": name,
                            "type": type,
                            "description": description,
                        },
                    ),
                )
            conn.commit()
            row = RegistryStorage.get_collection_cursor(conn, name)
        finally:
            conn.close()
        return {
            "name": row["name"],
            "type": row["type"],
            "description": row["description"],
            "created_at": row["created_at"],
            "created": created,
        }

    def link_artifact_version(
        self,
        registry: str,
        collection: str,
        type: str,
        source_project: str,
        source_artifact: str,
        source_version: int,
        aliases: list[str] | None,
        run_name: str | None = None,
        run_id: str | None = None,
        manifest_digest: str | None = None,
        source_space_id: str | None = None,
        source_bucket_id: str | None = None,
    ) -> dict:
        validate_collection_name(collection)
        validate_collection_type(type)
        user_aliases = [
            alias for alias in cas.validate_aliases(aliases) if alias != "latest"
        ]
        self._require_registry(registry)
        source = {
            "source_project": source_project,
            "source_artifact": source_artifact,
            "source_version": source_version,
        }
        conn = self._connect(registry)
        try:
            self._refresh_cursor(conn, registry)
            existing = RegistryStorage.get_collection_cursor(conn, collection)
            if existing is None:
                self._commit_remote_event(
                    conn,
                    registry,
                    new_event(
                        "create",
                        {
                            "registry": registry,
                            "collection": collection,
                            "type": type,
                            "description": None,
                        },
                    ),
                )
            elif existing["type"] != type:
                raise ValueError(
                    f"Collection {collection!r} in registry {registry!r} accepts "
                    f"type {existing['type']!r}, not {type!r}."
                )
            link_event = new_event(
                "link",
                {
                    "registry": registry,
                    "collection": collection,
                    **source,
                    "manifest_digest": manifest_digest,
                    "source_space_id": source_space_id,
                    "source_bucket_id": source_bucket_id,
                    "run_name": run_name,
                    "run_id": run_id,
                },
            )
            linked = RegistryStorage.apply_event_cursor(conn, link_event)
            if linked["created"]:
                self._upload_objects(
                    [
                        (
                            orjson.dumps(link_event),
                            _event_path(registry, link_event["event_uid"]),
                        )
                    ]
                )
                RegistryStorage._store_event_cursor(conn, link_event)
            for alias in user_aliases:
                if RegistryStorage._alias_points_at_cursor(
                    conn, collection, alias, linked["link_id"]
                ):
                    continue
                self._commit_remote_event(
                    conn,
                    registry,
                    new_event(
                        "promote",
                        {
                            "registry": registry,
                            "collection": collection,
                            "alias": alias,
                            **source,
                            "run_name": run_name,
                            "run_id": run_id,
                        },
                    ),
                )
            conn.commit()
            link_row = conn.execute(
                """SELECT collection_version, created_at FROM collection_links
                WHERE id = ?""",
                (linked["link_id"],),
            ).fetchone()
            alias_rows = conn.execute(
                "SELECT alias FROM collection_aliases WHERE link_id = ?",
                (linked["link_id"],),
            ).fetchall()
        finally:
            conn.close()
        return {
            "registry": registry,
            "collection": collection,
            "type": type,
            "collection_version": int(link_row["collection_version"]),
            **source,
            "aliases": sorted(row["alias"] for row in alias_rows),
            "created_at": link_row["created_at"],
            "created": linked["created"],
        }

    def unlink(self, registry: str, collection: str, collection_version: int) -> dict:
        self._require_registry(registry)
        conn = self._connect(registry)
        try:
            self._refresh_cursor(conn, registry)
            resolved = RegistryStorage._resolve_link_cursor(
                conn, registry, collection, collection_version
            )
            removed = self._commit_remote_event(
                conn,
                registry,
                new_event(
                    "unlink",
                    {
                        "registry": registry,
                        "collection": collection,
                        "collection_version": collection_version,
                        "source_project": resolved["source_project"],
                        "source_artifact": resolved["source_artifact"],
                        "source_version": resolved["source_version"],
                    },
                ),
            )
            conn.commit()
        finally:
            conn.close()
        return {
            "registry": registry,
            "collection": collection,
            "collection_version": collection_version,
            "source_project": resolved["source_project"],
            "source_artifact": resolved["source_artifact"],
            "source_version": resolved["source_version"],
            "removed_aliases": removed["removed_aliases"],
            "latest_version": removed["latest_version"],
        }

    def get_collection(self, registry: str, name: str) -> dict | None:
        if not self.registry_exists(registry):
            return None
        conn = self._connect(registry)
        try:
            self._refresh_cursor(conn, registry)
            conn.commit()
            return RegistryStorage.get_collection_cursor(conn, name)
        finally:
            conn.close()

    def list_collections(self, registry: str) -> list[dict]:
        if not self.registry_exists(registry):
            return []
        conn = self._connect(registry)
        try:
            self._refresh_cursor(conn, registry)
            conn.commit()
            return RegistryStorage.list_collections_cursor(conn)
        finally:
            conn.close()

    def get_events(self, registry: str) -> list[dict]:
        if not self.registry_exists(registry):
            return []
        conn = self._connect(registry)
        try:
            self._refresh_cursor(conn, registry)
            conn.commit()
            return RegistryStorage.get_events_cursor(conn)
        finally:
            conn.close()
