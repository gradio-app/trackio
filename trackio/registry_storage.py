"""Storage layer for artifact registries.

A registry is a regular trackio project named with the reserved
``registry-`` prefix, reusing the per-project SQLite database, locking, and
connection machinery of `SQLiteStorage` and keeping the standard project
schema. Its four registry tables (``collections``, ``collection_links``,
``collection_aliases``, ``registry_events``) are documented in the storage
schema docs. Collection versions come from a per-collection counter that
only moves forward, and every mutation appends an audit event in the same
transaction.
"""

import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import orjson

from trackio import cas
from trackio.sqlite_storage import SQLiteStorage
from trackio.utils import REGISTRY_PROJECT_PREFIX

REGISTRY_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+\Z")


def validate_registry_name(name: str) -> str:
    """Registry names become part of a project name, so they are restricted to
    characters that `canonical_project_name` keeps unchanged."""
    if not isinstance(name, str) or not REGISTRY_NAME_RE.match(name):
        raise ValueError(
            f"Registry name {name!r} must match ^[A-Za-z0-9_-]+$ "
            "(letters, digits, underscore, hyphen)."
        )
    return name


def validate_collection_name(name: str) -> str:
    if not isinstance(name, str) or not cas.ARTIFACT_NAME_RE.match(name):
        raise ValueError(
            f"Collection name {name!r} must match ^[A-Za-z0-9._-]+$ "
            "(letters, digits, dot, underscore, hyphen)."
        )
    return name


def validate_collection_type(collection_type: str) -> str:
    if not isinstance(collection_type, str) or len(collection_type) == 0:
        raise ValueError(
            f"Collection type must be a non-empty string, got {collection_type!r}."
        )
    return collection_type


def registry_project_name(registry: str) -> str:
    """On-disk project name backing a registry, e.g. ``registry-models``."""
    return f"{REGISTRY_PROJECT_PREFIX}{validate_registry_name(registry)}"


def parse_collection_target(target_path: str) -> tuple[str, str]:
    """Split a ``"registry-<registry>/<collection>"`` target path (e.g.
    ``"registry-models/churn-model"``) into its validated
    ``(registry, collection)`` parts. The first segment is the registry's
    project name, prefix included."""
    if (
        not isinstance(target_path, str)
        or target_path.count("/") != 1
        or not target_path.startswith(REGISTRY_PROJECT_PREFIX)
    ):
        raise ValueError(
            f"Registry target {target_path!r} must be "
            f"'{REGISTRY_PROJECT_PREFIX}<registry>/<collection>', "
            f"e.g. '{REGISTRY_PROJECT_PREFIX}models/churn-model'."
        )
    project, collection = target_path.split("/")
    registry = project[len(REGISTRY_PROJECT_PREFIX) :]
    validate_registry_name(registry)
    validate_collection_name(collection)
    return registry, collection


class RegistryStorage:
    @staticmethod
    def registry_exists(registry: str) -> bool:
        return SQLiteStorage.get_project_db_path(
            registry_project_name(registry)
        ).exists()

    @staticmethod
    def create_registry(registry: str, description: str | None = None) -> dict:
        """Create the registry's database and append a ``create`` event.

        The database gets the standard project schema plus the registry
        tables. An optional `description` is recorded on the create event.
        Raises ValueError when the registry already exists. Registries are
        never created implicitly: linking or creating a collection in a
        registry that does not exist raises.
        """
        project = registry_project_name(registry)
        if RegistryStorage.registry_exists(registry):
            raise ValueError(f"Registry {registry!r} already exists.")

        db_path = RegistryStorage.init_registry_db(registry)
        now = datetime.now(timezone.utc).isoformat()

        SQLiteStorage.set_project_metadata(project, "registry_created_at", now)
        if description is not None:
            SQLiteStorage.set_project_metadata(
                project, "registry_description", description
            )
        with SQLiteStorage._get_process_lock(project):
            with SQLiteStorage._get_connection(db_path) as conn:
                RegistryStorage._append_event_cursor(
                    conn, "create", {"registry": registry}, now
                )
                conn.commit()
        return {"name": registry, "description": description}

    @staticmethod
    def get_registry(registry: str) -> dict | None:
        """Describe the registry itself: its `name`, `description` (set at
        creation), and `created_at`. Both are read from `project_metadata`.
        Returns None when the registry does not exist.
        """
        project = registry_project_name(registry)
        if not SQLiteStorage.get_project_db_path(project).exists():
            return None
        return {
            "name": registry,
            "description": SQLiteStorage.get_project_metadata(
                project, "registry_description"
            ),
            "created_at": SQLiteStorage.get_project_metadata(
                project, "registry_created_at"
            ),
        }

    @staticmethod
    def _require_registry(registry: str) -> Path:
        """Path of the registry's database, raising when the registry has not
        been created yet."""
        db_path = SQLiteStorage.get_project_db_path(registry_project_name(registry))
        if not db_path.exists():
            raise ValueError(
                f"Registry {registry!r} does not exist. Create it first with "
                f"trackio.Api().create_registry({registry!r})."
            )
        return db_path

    @staticmethod
    def init_registry_db(registry: str) -> Path:
        """Initialize the registry's database and return its path.

        The database is created with the standard project schema first, then
        the registry tables are added.
        """
        project = registry_project_name(registry)
        db_path = SQLiteStorage.init_db(project)
        with SQLiteStorage._get_process_lock(project):
            with SQLiteStorage._get_connection(db_path, row_factory=None) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS collections (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name TEXT NOT NULL UNIQUE,
                        type TEXT NOT NULL,
                        description TEXT,
                        next_version INTEGER NOT NULL DEFAULT 0,
                        created_at TEXT NOT NULL
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS collection_links (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        collection_id INTEGER NOT NULL REFERENCES collections(id),
                        collection_version INTEGER NOT NULL,
                        source_project TEXT NOT NULL,
                        source_artifact TEXT NOT NULL,
                        source_version INTEGER NOT NULL,
                        created_at TEXT NOT NULL,
                        UNIQUE(collection_id, source_project, source_artifact,
                               source_version),
                        UNIQUE(collection_id, collection_version)
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS collection_aliases (
                        collection_id INTEGER NOT NULL REFERENCES collections(id),
                        alias TEXT NOT NULL,
                        link_id INTEGER NOT NULL REFERENCES collection_links(id),
                        PRIMARY KEY (collection_id, alias)
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS registry_events (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        ts TEXT NOT NULL,
                        kind TEXT NOT NULL,
                        payload TEXT NOT NULL
                    )
                    """
                )
                conn.commit()
        return db_path

    @staticmethod
    def _append_event_cursor(
        conn: sqlite3.Connection,
        kind: str,
        payload: dict,
        now: str,
    ) -> None:
        conn.execute(
            "INSERT INTO registry_events (ts, kind, payload) VALUES (?, ?, ?)",
            (now, kind, orjson.dumps(payload).decode("utf-8")),
        )

    @staticmethod
    def _create_or_get_collection_cursor(
        conn: sqlite3.Connection,
        registry: str,
        name: str,
        type: str,
        description: str | None,
        now: str,
    ) -> tuple[int, bool]:
        """Return ``(collection_id, created)`` for the collection named `name`,
        creating it if absent. For an existing collection a non-None, changed
        `description` is applied in place (appending an ``update`` event); the
        type is immutable and a mismatch raises. Creation appends a ``create``
        event."""
        cursor = conn.cursor()
        row = cursor.execute(
            "SELECT id, type, description FROM collections WHERE name = ?", (name,)
        ).fetchone()
        if row is not None:
            if row["type"] != type:
                raise ValueError(
                    f"Collection {name!r} in registry {registry!r} accepts "
                    f"type {row['type']!r}, not {type!r}."
                )
            if description is not None and description != row["description"]:
                cursor.execute(
                    "UPDATE collections SET description = ? WHERE id = ?",
                    (description, int(row["id"])),
                )
                RegistryStorage._append_event_cursor(
                    conn,
                    "update",
                    {
                        "registry": registry,
                        "collection": name,
                        "description": description,
                    },
                    now,
                )
            return int(row["id"]), False
        cursor.execute(
            """INSERT INTO collections
            (name, type, description, next_version, created_at)
            VALUES (?, ?, ?, 0, ?)""",
            (name, type, description, now),
        )
        collection_id = int(cursor.lastrowid)
        RegistryStorage._append_event_cursor(
            conn,
            "create",
            {
                "registry": registry,
                "collection": name,
                "type": type,
                "description": description,
            },
            now,
        )
        return collection_id, True

    @staticmethod
    def _reassign_collection_alias_cursor(
        conn: sqlite3.Connection,
        collection_id: int,
        alias: str,
        link_id: int,
    ) -> None:
        if cas.ARTIFACT_VERSION_SPEC_RE.match(alias):
            raise ValueError(
                f"Alias '{alias}' is reserved for version pointers (vN); "
                "choose another."
            )
        conn.execute(
            """INSERT INTO collection_aliases (collection_id, alias, link_id)
            VALUES (?, ?, ?)
            ON CONFLICT(collection_id, alias) DO UPDATE SET
                link_id = excluded.link_id""",
            (collection_id, alias, link_id),
        )

    @staticmethod
    def _promote_alias_cursor(
        conn: sqlite3.Connection,
        registry: str,
        collection_id: int,
        collection: str,
        alias: str,
        link_id: int,
        collection_version: int,
        run_name: str | None,
        run_id: str | None,
        now: str,
    ) -> None:
        """Upsert `alias` onto `link_id` and append a ``promote`` event
        recording the version it moved from. An exact no-op (the alias already
        points at `link_id`) writes nothing."""
        current = conn.execute(
            """SELECT ca.link_id, cl.collection_version
            FROM collection_aliases ca
            JOIN collection_links cl ON cl.id = ca.link_id
            WHERE ca.collection_id = ? AND ca.alias = ?""",
            (collection_id, alias),
        ).fetchone()
        if current is not None and int(current["link_id"]) == link_id:
            return
        RegistryStorage._reassign_collection_alias_cursor(
            conn, collection_id, alias, link_id
        )
        RegistryStorage._append_event_cursor(
            conn,
            "promote",
            {
                "registry": registry,
                "collection": collection,
                "alias": alias,
                "collection_version": collection_version,
                "previous_version": (
                    None if current is None else int(current["collection_version"])
                ),
                "run_name": run_name,
                "run_id": run_id,
            },
            now,
        )

    @staticmethod
    def _insert_collection_link_cursor(
        conn: sqlite3.Connection,
        registry: str,
        collection_id: int,
        collection: str,
        source_project: str,
        source_artifact: str,
        source_version: int,
        run_name: str | None,
        run_id: str | None,
        now: str,
    ) -> tuple[int, int, bool]:
        """Return ``(link_id, collection_version, created)``. Re-linking an
        already-linked source version returns the existing link unchanged
        (``created`` False). A new link consumes the collection's monotonic
        ``next_version`` counter, moves the collection's ``latest`` alias onto
        itself (part of the link operation, recorded by the ``link`` event),
        and appends that event."""
        cursor = conn.cursor()
        existing = cursor.execute(
            """SELECT id, collection_version FROM collection_links
            WHERE collection_id = ? AND source_project = ?
              AND source_artifact = ? AND source_version = ?""",
            (collection_id, source_project, source_artifact, source_version),
        ).fetchone()
        if existing is not None:
            return int(existing["id"]), int(existing["collection_version"]), False
        row = cursor.execute(
            "SELECT next_version FROM collections WHERE id = ?", (collection_id,)
        ).fetchone()
        collection_version = int(row["next_version"])
        cursor.execute(
            """INSERT INTO collection_links
            (collection_id, collection_version, source_project, source_artifact,
             source_version, created_at)
            VALUES (?, ?, ?, ?, ?, ?)""",
            (
                collection_id,
                collection_version,
                source_project,
                source_artifact,
                source_version,
                now,
            ),
        )
        link_id = int(cursor.lastrowid)
        cursor.execute(
            "UPDATE collections SET next_version = ? WHERE id = ?",
            (collection_version + 1, collection_id),
        )
        RegistryStorage._reassign_collection_alias_cursor(
            conn, collection_id, "latest", link_id
        )
        RegistryStorage._append_event_cursor(
            conn,
            "link",
            {
                "registry": registry,
                "collection": collection,
                "collection_version": collection_version,
                "source_project": source_project,
                "source_artifact": source_artifact,
                "source_version": source_version,
                "run_name": run_name,
                "run_id": run_id,
            },
            now,
        )
        return link_id, collection_version, True

    @staticmethod
    def link_artifact_version(
        registry: str,
        collection: str,
        type: str,
        source_project: str,
        source_artifact: str,
        source_version: int,
        aliases: list[str] | None,
        run_name: str | None = None,
        run_id: str | None = None,
    ) -> dict:
        """Link one artifact version into `registry`/`collection` and return
        the link record.

        The registry must already exist. The collection is created on first
        use and adopts the linked version's type; later links must match it.
        Re-linking an already-linked source version returns the existing
        link (``created`` False) and still moves the requested `aliases`.
        An alias move may go backward (a rollback). ``latest`` is managed
        automatically and always follows the newest linked version; passing
        it in `aliases` is a no-op rather than an error (matching wandb)."""
        validate_collection_name(collection)
        validate_collection_type(type)
        user_aliases = [
            alias for alias in cas.validate_aliases(aliases) if alias != "latest"
        ]
        project = registry_project_name(registry)
        db_path = RegistryStorage._require_registry(registry)
        now = datetime.now(timezone.utc).isoformat()
        with SQLiteStorage._get_process_lock(project):
            with SQLiteStorage._get_connection(db_path) as conn:
                collection_id, _ = RegistryStorage._create_or_get_collection_cursor(
                    conn, registry, collection, type, None, now
                )
                link_id, collection_version, created = (
                    RegistryStorage._insert_collection_link_cursor(
                        conn,
                        registry,
                        collection_id,
                        collection,
                        source_project,
                        source_artifact,
                        source_version,
                        run_name,
                        run_id,
                        now,
                    )
                )
                for alias in user_aliases:
                    RegistryStorage._promote_alias_cursor(
                        conn,
                        registry,
                        collection_id,
                        collection,
                        alias,
                        link_id,
                        collection_version,
                        run_name,
                        run_id,
                        now,
                    )
                link_row = conn.execute(
                    """SELECT collection_version, source_project, source_artifact,
                       source_version, created_at
                    FROM collection_links WHERE id = ?""",
                    (link_id,),
                ).fetchone()
                alias_rows = conn.execute(
                    "SELECT alias FROM collection_aliases WHERE link_id = ?",
                    (link_id,),
                ).fetchall()
                conn.commit()
                return {
                    "registry": registry,
                    "collection": collection,
                    "type": type,
                    "collection_version": int(link_row["collection_version"]),
                    "source_project": link_row["source_project"],
                    "source_artifact": link_row["source_artifact"],
                    "source_version": int(link_row["source_version"]),
                    "aliases": sorted(r["alias"] for r in alias_rows),
                    "created_at": link_row["created_at"],
                    "created": created,
                }

    @staticmethod
    def create_collection(
        registry: str,
        name: str,
        type: str,
        description: str | None = None,
    ) -> dict:
        """Create the collection (or fetch it, refreshing a non-None
        `description` in place) and return its summary. The registry must
        already exist (see `create_registry`); the type is fixed at creation
        and a mismatch raises."""
        validate_collection_name(name)
        validate_collection_type(type)
        project = registry_project_name(registry)
        db_path = RegistryStorage._require_registry(registry)
        now = datetime.now(timezone.utc).isoformat()
        with SQLiteStorage._get_process_lock(project):
            with SQLiteStorage._get_connection(db_path) as conn:
                collection_id, created = (
                    RegistryStorage._create_or_get_collection_cursor(
                        conn, registry, name, type, description, now
                    )
                )
                row = conn.execute(
                    """SELECT name, type, description, created_at
                    FROM collections WHERE id = ?""",
                    (collection_id,),
                ).fetchone()
                conn.commit()
                return {
                    "name": row["name"],
                    "type": row["type"],
                    "description": row["description"],
                    "created_at": row["created_at"],
                    "created": created,
                }

    @staticmethod
    def unlink(
        registry: str,
        collection: str,
        collection_version: int,
    ) -> dict:
        """Remove the link at `collection_version` and return what was
        removed.

        Aliases pointing at the link are removed with it and recorded in
        the ``unlink`` event. The version number is never reused. Raises
        ValueError when the registry, collection, or version does not
        exist."""
        project = registry_project_name(registry)
        db_path = SQLiteStorage.get_project_db_path(project)
        if not db_path.exists():
            raise ValueError(f"Registry {registry!r} does not exist.")
        now = datetime.now(timezone.utc).isoformat()
        with SQLiteStorage._get_process_lock(project):
            with SQLiteStorage._get_connection(db_path) as conn:
                resolved = RegistryStorage._resolve_link_cursor(
                    conn, registry, collection, collection_version
                )
                link_id = resolved["link_id"]
                alias_rows = conn.execute(
                    "SELECT alias FROM collection_aliases WHERE link_id = ?",
                    (link_id,),
                ).fetchall()
                removed_aliases = sorted(r["alias"] for r in alias_rows)
                conn.execute(
                    "DELETE FROM collection_aliases WHERE link_id = ?", (link_id,)
                )
                conn.execute("DELETE FROM collection_links WHERE id = ?", (link_id,))
                RegistryStorage._append_event_cursor(
                    conn,
                    "unlink",
                    {
                        "registry": registry,
                        "collection": collection,
                        "collection_version": collection_version,
                        "source_project": resolved["source_project"],
                        "source_artifact": resolved["source_artifact"],
                        "source_version": resolved["source_version"],
                        "removed_aliases": removed_aliases,
                    },
                    now,
                )
                conn.commit()
                return {
                    "registry": registry,
                    "collection": collection,
                    "collection_version": collection_version,
                    "source_project": resolved["source_project"],
                    "source_artifact": resolved["source_artifact"],
                    "source_version": resolved["source_version"],
                    "removed_aliases": removed_aliases,
                }

    @staticmethod
    def _resolve_link_cursor(
        conn: sqlite3.Connection,
        registry: str,
        collection: str,
        collection_version: int,
    ) -> dict:
        coll = conn.execute(
            "SELECT id FROM collections WHERE name = ?", (collection,)
        ).fetchone()
        if coll is None:
            raise ValueError(
                f"Collection {collection!r} not found in registry {registry!r}."
            )
        collection_id = int(coll["id"])
        link = conn.execute(
            """SELECT id, source_project, source_artifact, source_version
            FROM collection_links
            WHERE collection_id = ? AND collection_version = ?""",
            (collection_id, collection_version),
        ).fetchone()
        if link is None:
            raise ValueError(
                f"Version v{collection_version} not found in collection "
                f"{collection!r} of registry {registry!r}."
            )
        return {
            "collection_id": collection_id,
            "link_id": int(link["id"]),
            "source_project": link["source_project"],
            "source_artifact": link["source_artifact"],
            "source_version": int(link["source_version"]),
        }

    @staticmethod
    def _links_by_collection_cursor(
        conn: sqlite3.Connection,
        collection_id: int | None = None,
    ) -> dict[int, list[dict]]:
        """Link dicts (newest first, with aliases) grouped by collection id,
        for one collection or for all of them."""
        where = "WHERE collection_id = ?" if collection_id is not None else ""
        params = (collection_id,) if collection_id is not None else ()
        link_rows = conn.execute(
            f"""SELECT id, collection_id, collection_version, source_project,
               source_artifact, source_version, created_at
            FROM collection_links {where}
            ORDER BY collection_id, collection_version DESC""",
            params,
        ).fetchall()
        alias_rows = conn.execute(
            f"SELECT alias, link_id FROM collection_aliases {where}",
            params,
        ).fetchall()
        aliases_by_link: dict[int, list[str]] = {}
        for alias_row in alias_rows:
            aliases_by_link.setdefault(int(alias_row["link_id"]), []).append(
                alias_row["alias"]
            )
        links_by_collection: dict[int, list[dict]] = {}
        for link in link_rows:
            links_by_collection.setdefault(int(link["collection_id"]), []).append(
                {
                    "collection_version": int(link["collection_version"]),
                    "source_project": link["source_project"],
                    "source_artifact": link["source_artifact"],
                    "source_version": int(link["source_version"]),
                    "aliases": sorted(aliases_by_link.get(int(link["id"]), [])),
                    "created_at": link["created_at"],
                }
            )
        return links_by_collection

    @staticmethod
    def get_collection(registry: str, name: str) -> dict | None:
        """Describe one collection: its type, description, and every link
        (newest first) with source coordinates and aliases. Returns None
        when the registry or the collection does not exist."""
        SQLiteStorage._ensure_hub_loaded()
        db_path = SQLiteStorage.get_project_db_path(registry_project_name(registry))
        if not db_path.exists():
            return None
        with SQLiteStorage._get_connection(db_path) as conn:
            try:
                row = conn.execute(
                    """SELECT id, name, type, description, created_at
                    FROM collections WHERE name = ?""",
                    (name,),
                ).fetchone()
            except sqlite3.OperationalError:
                return None
            if row is None:
                return None
            collection_id = int(row["id"])
            links = RegistryStorage._links_by_collection_cursor(
                conn, collection_id
            ).get(collection_id, [])
            return {
                "name": row["name"],
                "type": row["type"],
                "description": row["description"],
                "created_at": row["created_at"],
                "links": links,
            }

    @staticmethod
    def list_collections(registry: str) -> list[dict]:
        """Every collection in `registry` with its links, ordered by type
        then name (mirroring `SQLiteStorage.list_artifacts`). Returns []
        when the registry does not exist."""
        SQLiteStorage._ensure_hub_loaded()
        db_path = SQLiteStorage.get_project_db_path(registry_project_name(registry))
        if not db_path.exists():
            return []
        with SQLiteStorage._get_connection(db_path) as conn:
            try:
                rows = conn.execute(
                    """SELECT id, name, type, description, created_at
                    FROM collections ORDER BY type, name"""
                ).fetchall()
                links_by_collection = RegistryStorage._links_by_collection_cursor(conn)
            except sqlite3.OperationalError:
                return []
            result = []
            for row in rows:
                links = links_by_collection.get(int(row["id"]), [])
                result.append(
                    {
                        "name": row["name"],
                        "type": row["type"],
                        "description": row["description"],
                        "created_at": row["created_at"],
                        "num_links": len(links),
                        "latest_version": (
                            links[0]["collection_version"] if links else None
                        ),
                        "links": links,
                    }
                )
            return result

    @staticmethod
    def get_events(registry: str) -> list[dict]:
        """The registry's append-only audit log, oldest first, with payloads
        parsed back into dicts. Returns [] when the registry does not exist."""
        SQLiteStorage._ensure_hub_loaded()
        db_path = SQLiteStorage.get_project_db_path(registry_project_name(registry))
        if not db_path.exists():
            return []
        with SQLiteStorage._get_connection(db_path) as conn:
            try:
                rows = conn.execute(
                    "SELECT id, ts, kind, payload FROM registry_events ORDER BY id"
                ).fetchall()
            except sqlite3.OperationalError:
                return []
            return [
                {
                    "id": int(row["id"]),
                    "ts": row["ts"],
                    "kind": row["kind"],
                    "payload": orjson.loads(row["payload"]),
                }
                for row in rows
            ]
