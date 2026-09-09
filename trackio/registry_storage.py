"""Storage layer for artifact registries.

A local registry is a regular trackio project named with the reserved
``registry-`` prefix, reusing the per-project SQLite database, locking, and
connection machinery of `SQLiteStorage` and keeping the standard project
schema. Its four registry tables (``collections``, ``collection_links``,
``collection_aliases``, ``registry_events``) are documented in the storage
schema docs.

Mutations are event-sourced: each one is built as an event (`new_event`),
folded into the projection tables by `apply_event_cursor`, and appended to
``registry_events`` in the same transaction. Collection versions are assigned
by the fold rather than claimed by the writer, and events are idempotent, which
is what lets `trackio.registry_bucket` keep the same registry in object storage
— where an append-only log is the only thing concurrent writers can safely
share — and reuse this reducer to materialize it.
"""

import itertools
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

import orjson

from trackio import cas
from trackio.sqlite_storage import SQLiteStorage
from trackio.utils import REGISTRY_PROJECT_PREFIX

REGISTRY_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+\Z")

_WRITER_ID = uuid.uuid4().hex[:8]
_EVENT_SEQ = itertools.count()


def new_event(kind: str, payload: dict, ts: str | None = None) -> dict:
    """Build one registry mutation as a self-describing record.

    A mutation is expressed as an event first and applied second, so the same
    reducer serves a local database and an object-store backend where the log
    is the only thing writers can safely append to. `event_uid` is
    ``<compact-utc>-<writer>-<seq>``: fixed width, so sorting it lexicographically
    totally orders events across writers, and unique, so replaying a log twice
    changes nothing.
    """
    now = datetime.now(timezone.utc)
    return {
        "event_uid": (
            f"{now.strftime('%Y%m%dT%H%M%S%f')}-{_WRITER_ID}-{next(_EVENT_SEQ):06d}"
        ),
        "ts": ts or now.isoformat(),
        "kind": kind,
        "payload": payload,
    }


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


def resolve_collection_link(links: list[dict], spec: str | None) -> dict:
    """Pick the link a ``use_artifact`` spec refers to from a collection's
    ``links`` (as returned by ``get_collection``): ``None`` or ``"latest"`` for
    the newest version, ``"v<N>"`` for a collection version, anything else for
    an alias."""
    if not links:
        raise ValueError("Collection is empty: nothing has been linked into it.")
    if spec is None or spec == "latest":
        return max(links, key=lambda link: int(link["collection_version"]))
    version_match = re.fullmatch(r"v(\d+)", spec)
    for link in links:
        if version_match is not None:
            if int(link["collection_version"]) == int(version_match.group(1)):
                return link
        elif spec in link.get("aliases", []):
            return link
    kind = "Version" if version_match is not None else "Alias"
    raise ValueError(f"{kind} {spec!r} not found in collection.")


class RegistryStorage:
    REGISTRY_CREATED_AT_KEY = "registry_created_at"
    REGISTRY_DESCRIPTION_KEY = "registry_description"

    @staticmethod
    def registry_exists(registry: str) -> bool:
        return RegistryStorage._registry_created_at(registry) is not None

    @staticmethod
    def _registry_created_at(registry: str) -> str | None:
        """Creation timestamp of the registry, or None when it has not been
        created. `create_registry` writes this marker in the same transaction
        as the ``create`` event, so it — not the mere existence of the database
        file — is what makes a registry exist: a database left behind by an
        interrupted creation carries no marker and can be created again."""
        project = registry_project_name(registry)
        if not SQLiteStorage.get_project_db_path(project).exists():
            return None
        return SQLiteStorage.get_project_metadata(
            project, RegistryStorage.REGISTRY_CREATED_AT_KEY
        )

    @staticmethod
    def _registry_marker_cursor(conn: sqlite3.Connection) -> str | None:
        """`_registry_created_at` read through an open connection, so the
        existence check can share a transaction with the writes that follow."""
        row = conn.execute(
            "SELECT value FROM project_metadata WHERE key = ?",
            (RegistryStorage.REGISTRY_CREATED_AT_KEY,),
        ).fetchone()
        return None if row is None else row[0]

    @staticmethod
    def create_registry(registry: str, description: str | None = None) -> dict:
        """Create the registry's database and append a ``create`` event.

        The database gets the standard project schema plus the registry
        tables. An optional `description` is recorded on the create event.
        Raises ValueError when the registry already exists. Registries are
        never created implicitly: linking or creating a collection in a
        registry that does not exist raises.

        The existence check, the registry tables, the creation marker and
        description, and the ``create`` event all happen under one process
        lock in a single transaction, with the check repeated after the lock
        is held. Concurrent creators therefore cannot both succeed, and an
        interrupted creation commits nothing for a retry to inherit.
        """
        project = registry_project_name(registry)
        db_path = SQLiteStorage.init_db(project)
        with SQLiteStorage._get_process_lock(project):
            with SQLiteStorage._get_connection(db_path) as conn:
                if RegistryStorage._registry_marker_cursor(conn) is not None:
                    raise ValueError(f"Registry {registry!r} already exists.")
                RegistryStorage._create_registry_tables_cursor(conn)
                RegistryStorage._commit_event_cursor(
                    conn, new_event("create", {"registry": registry})
                )
                if description is not None:
                    conn.execute(
                        """INSERT OR REPLACE INTO project_metadata (key, value)
                        VALUES (?, ?)""",
                        (RegistryStorage.REGISTRY_DESCRIPTION_KEY, description),
                    )
                conn.commit()
        return {"name": registry, "description": description}

    @staticmethod
    def get_registry(registry: str) -> dict | None:
        """Describe the registry itself: its `name`, `description` (set at
        creation), and `created_at`. Both are read from `project_metadata`.
        Returns None when the registry does not exist.
        """
        created_at = RegistryStorage._registry_created_at(registry)
        if created_at is None:
            return None
        return {
            "name": registry,
            "description": SQLiteStorage.get_project_metadata(
                registry_project_name(registry),
                RegistryStorage.REGISTRY_DESCRIPTION_KEY,
            ),
            "created_at": created_at,
        }

    @staticmethod
    def list_registries() -> list[dict]:
        """List local registries, ordered by name.

        Registry databases share the project directory and are identified by
        both their reserved project-name prefix and their atomic creation
        marker. A prefixed database left behind by an interrupted creation is
        therefore not exposed as a registry.
        """
        registries = []
        for project in SQLiteStorage.get_projects():
            if not project.startswith(REGISTRY_PROJECT_PREFIX):
                continue
            registry = project[len(REGISTRY_PROJECT_PREFIX) :]
            try:
                record = RegistryStorage.get_registry(registry)
            except ValueError:
                continue
            if record is not None:
                registries.append(record)
        return registries

    @staticmethod
    def _require_registry(registry: str) -> Path:
        """Path of the registry's database, raising when the registry has not
        been created yet — a database left behind by an interrupted creation
        does not count as one."""
        if RegistryStorage._registry_created_at(registry) is None:
            raise ValueError(
                f"Registry {registry!r} does not exist. Create it first with "
                f"trackio.Api().create_registry({registry!r})."
            )
        return SQLiteStorage.get_project_db_path(registry_project_name(registry))

    @staticmethod
    def init_registry_db(registry: str) -> Path:
        """Initialize the registry's database and return its path.

        The database is created with the standard project schema first, then
        the registry tables are added. This leaves the registry unmarked;
        `create_registry` is what makes it exist.
        """
        project = registry_project_name(registry)
        db_path = SQLiteStorage.init_db(project)
        with SQLiteStorage._get_process_lock(project):
            with SQLiteStorage._get_connection(db_path, row_factory=None) as conn:
                RegistryStorage._create_registry_tables_cursor(conn)
                conn.commit()
        return db_path

    @staticmethod
    def _create_registry_tables_cursor(conn: sqlite3.Connection) -> None:
        """Add the registry tables to a database. Idempotent, and callable from
        within a caller's lock and transaction. `project_metadata` is included
        so the schema is self-contained: a project database already has that
        table, and a standalone projection of a remote registry needs it for
        the creation marker."""
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS project_metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
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
                source_space_id TEXT,
                source_bucket_id TEXT,
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
                event_uid TEXT,
                ts TEXT NOT NULL,
                kind TEXT NOT NULL,
                payload TEXT NOT NULL
            )
            """
        )
        RegistryStorage._add_missing_columns_cursor(
            conn,
            {
                "registry_events": {"event_uid": "TEXT"},
                "collection_links": {
                    "source_space_id": "TEXT",
                    "source_bucket_id": "TEXT",
                },
            },
        )
        cursor.execute(
            """CREATE UNIQUE INDEX IF NOT EXISTS idx_registry_events_uid
            ON registry_events(event_uid)"""
        )

    @staticmethod
    def _add_missing_columns_cursor(
        conn: sqlite3.Connection, columns_by_table: dict[str, dict[str, str]]
    ) -> None:
        """Add columns a registry database created by an older Trackio is
        missing. `CREATE TABLE IF NOT EXISTS` leaves an existing table alone, so
        new columns need this."""
        for table, columns in columns_by_table.items():
            present = {
                row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
            }
            for column, decl in columns.items():
                if column not in present:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")

    @staticmethod
    def _store_event_cursor(conn: sqlite3.Connection, event: dict) -> None:
        """Append `event` to the log. Re-storing an event already in the log is
        a no-op, which is what makes replaying a remote log idempotent."""
        conn.execute(
            """INSERT OR IGNORE INTO registry_events (event_uid, ts, kind, payload)
            VALUES (?, ?, ?, ?)""",
            (
                event["event_uid"],
                event["ts"],
                event["kind"],
                orjson.dumps(event["payload"]).decode("utf-8"),
            ),
        )

    @staticmethod
    def apply_event_cursor(conn: sqlite3.Connection, event: dict) -> dict:
        """Fold one event into the projection tables (`collections`,
        `collection_links`, `collection_aliases`) and return whatever it
        derived — the assigned `collection_version`, the version an alias moved
        from, the aliases an unlink removed.

        Derived values are also stamped back into `event["payload"]`, so a
        caller that stores the event afterwards records what actually happened.
        Applying the same event twice is a no-op.
        """
        kind = event["kind"]
        payload = event["payload"]
        ts = event["ts"]
        if kind == "create":
            if "collection" in payload:
                return RegistryStorage._apply_collection_create(conn, payload, ts)
            return RegistryStorage._apply_registry_create(conn, ts)
        if kind == "update":
            return RegistryStorage._apply_collection_update(conn, payload)
        if kind == "link":
            return RegistryStorage._apply_link(conn, payload, ts)
        if kind == "promote":
            return RegistryStorage._apply_promote(conn, payload)
        if kind == "unlink":
            return RegistryStorage._apply_unlink(conn, payload)
        raise ValueError(f"Unknown registry event kind {kind!r}.")

    @staticmethod
    def _commit_event_cursor(conn: sqlite3.Connection, event: dict) -> dict:
        """Apply `event` and append it to the log inside the caller's
        transaction, so the projection and the log can never disagree."""
        result = RegistryStorage.apply_event_cursor(conn, event)
        RegistryStorage._store_event_cursor(conn, event)
        return result

    @staticmethod
    def replay_events_cursor(conn: sqlite3.Connection, events: list[dict]) -> None:
        """Fold a log into an empty or partially-built projection, oldest event
        first. Events already in the log are skipped, and the stored payload is
        left exactly as the writer wrote it — the projection, not the payload,
        carries the derived truth."""
        known = {
            row[0]
            for row in conn.execute(
                "SELECT event_uid FROM registry_events WHERE event_uid IS NOT NULL"
            ).fetchall()
        }
        for event in sorted(events, key=lambda e: e["event_uid"]):
            if event["event_uid"] in known:
                continue
            RegistryStorage.apply_event_cursor(
                conn, {**event, "payload": dict(event["payload"])}
            )
            RegistryStorage._store_event_cursor(conn, event)

    @staticmethod
    def _apply_registry_create(conn: sqlite3.Connection, ts: str) -> dict:
        conn.execute(
            """INSERT OR REPLACE INTO project_metadata (key, value)
            VALUES (?, ?)""",
            (RegistryStorage.REGISTRY_CREATED_AT_KEY, ts),
        )
        return {}

    @staticmethod
    def _apply_collection_create(
        conn: sqlite3.Connection, payload: dict, ts: str
    ) -> dict:
        conn.execute(
            """INSERT OR IGNORE INTO collections
            (name, type, description, next_version, created_at)
            VALUES (?, ?, ?, 0, ?)""",
            (payload["collection"], payload["type"], payload.get("description"), ts),
        )
        return {}

    @staticmethod
    def _apply_collection_update(conn: sqlite3.Connection, payload: dict) -> dict:
        conn.execute(
            "UPDATE collections SET description = ? WHERE name = ?",
            (payload.get("description"), payload["collection"]),
        )
        return {}

    @staticmethod
    def _collection_id_cursor(conn: sqlite3.Connection, collection: str) -> int | None:
        row = conn.execute(
            "SELECT id FROM collections WHERE name = ?", (collection,)
        ).fetchone()
        return None if row is None else int(row["id"])

    @staticmethod
    def _create_or_get_collection_cursor(
        conn: sqlite3.Connection,
        registry: str,
        name: str,
        type: str,
        description: str | None,
    ) -> tuple[int, bool]:
        """Return ``(collection_id, created)`` for the collection named `name`,
        creating it if absent. For an existing collection a non-None, changed
        `description` is applied in place (through an ``update`` event); the
        type is immutable and a mismatch raises. Creation goes through a
        ``create`` event."""
        row = conn.execute(
            "SELECT id, type, description FROM collections WHERE name = ?", (name,)
        ).fetchone()
        if row is not None:
            if row["type"] != type:
                raise ValueError(
                    f"Collection {name!r} in registry {registry!r} accepts "
                    f"type {row['type']!r}, not {type!r}."
                )
            if description is not None and description != row["description"]:
                RegistryStorage._commit_event_cursor(
                    conn,
                    new_event(
                        "update",
                        {
                            "registry": registry,
                            "collection": name,
                            "description": description,
                        },
                    ),
                )
            return int(row["id"]), False
        RegistryStorage._commit_event_cursor(
            conn,
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
        return RegistryStorage._collection_id_cursor(conn, name), True

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
    def _latest_version_cursor(
        conn: sqlite3.Connection,
        collection_id: int,
    ) -> int | None:
        """Version the collection's ``latest`` alias currently points at, or
        None when the collection has no links."""
        row = conn.execute(
            """SELECT cl.collection_version
            FROM collection_aliases ca
            JOIN collection_links cl ON cl.id = ca.link_id
            WHERE ca.collection_id = ? AND ca.alias = 'latest'""",
            (collection_id,),
        ).fetchone()
        return None if row is None else int(row["collection_version"])

    @staticmethod
    def _reassign_latest_cursor(
        conn: sqlite3.Connection,
        collection_id: int,
    ) -> int | None:
        """Move ``latest`` onto the collection's highest remaining version after
        its holder was unlinked, and return that ``collection_version`` (None
        when no link is left). Without this the collection would sit with no
        ``latest`` at all until the next link, contradicting the invariant that
        ``latest`` always follows the newest linked version."""
        row = conn.execute(
            """SELECT id, collection_version FROM collection_links
            WHERE collection_id = ?
            ORDER BY collection_version DESC LIMIT 1""",
            (collection_id,),
        ).fetchone()
        if row is None:
            return None
        RegistryStorage._reassign_collection_alias_cursor(
            conn, collection_id, "latest", int(row["id"])
        )
        return int(row["collection_version"])

    @staticmethod
    def _find_link_cursor(
        conn: sqlite3.Connection, collection_id: int, payload: dict
    ) -> sqlite3.Row | None:
        """The link an event refers to, by source triple when the payload
        carries one and by `collection_version` otherwise. The triple is the
        stable identity: a version number assigned by one writer can be
        superseded when a concurrent log is folded in, the source coordinates
        never are."""
        if payload.get("source_project") is not None:
            return conn.execute(
                """SELECT id, collection_version FROM collection_links
                WHERE collection_id = ? AND source_project = ?
                  AND source_artifact = ? AND source_version = ?""",
                (
                    collection_id,
                    payload["source_project"],
                    payload["source_artifact"],
                    int(payload["source_version"]),
                ),
            ).fetchone()
        return conn.execute(
            """SELECT id, collection_version FROM collection_links
            WHERE collection_id = ? AND collection_version = ?""",
            (collection_id, int(payload["collection_version"])),
        ).fetchone()

    @staticmethod
    def _apply_link(conn: sqlite3.Connection, payload: dict, ts: str) -> dict:
        """Add the link the event describes and move ``latest`` onto it.

        The version is assigned here rather than by the writer: the version the
        payload asks for is honored only if it is still free (which it always is
        when a single writer's log is replayed in order), and otherwise the
        collection's monotonic counter decides. That keeps numbers unique and
        never-reused however two writers' logs interleave.
        """
        collection_id = RegistryStorage._collection_id_cursor(
            conn, payload["collection"]
        )
        if collection_id is None:
            raise ValueError(
                f"Link event for unknown collection {payload['collection']!r}."
            )
        existing = RegistryStorage._find_link_cursor(conn, collection_id, payload)
        if existing is not None:
            payload["collection_version"] = int(existing["collection_version"])
            return {
                "link_id": int(existing["id"]),
                "collection_version": int(existing["collection_version"]),
                "created": False,
            }
        next_version = int(
            conn.execute(
                "SELECT next_version FROM collections WHERE id = ?", (collection_id,)
            ).fetchone()["next_version"]
        )
        requested = payload.get("collection_version")
        collection_version = (
            int(requested)
            if requested is not None and int(requested) >= next_version
            else next_version
        )
        cursor = conn.cursor()
        cursor.execute(
            """INSERT INTO collection_links
            (collection_id, collection_version, source_project, source_artifact,
             source_version, source_space_id, source_bucket_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                collection_id,
                collection_version,
                payload["source_project"],
                payload["source_artifact"],
                int(payload["source_version"]),
                payload.get("source_space_id"),
                payload.get("source_bucket_id"),
                ts,
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
        payload["collection_version"] = collection_version
        return {
            "link_id": link_id,
            "collection_version": collection_version,
            "created": True,
        }

    @staticmethod
    def _apply_promote(conn: sqlite3.Connection, payload: dict) -> dict:
        collection_id = RegistryStorage._collection_id_cursor(
            conn, payload["collection"]
        )
        if collection_id is None:
            raise ValueError(
                f"Promote event for unknown collection {payload['collection']!r}."
            )
        link = RegistryStorage._find_link_cursor(conn, collection_id, payload)
        if link is None:
            raise ValueError(
                f"Promote event for a version that is not linked in "
                f"{payload['collection']!r}."
            )
        current = conn.execute(
            """SELECT ca.link_id, cl.collection_version
            FROM collection_aliases ca
            JOIN collection_links cl ON cl.id = ca.link_id
            WHERE ca.collection_id = ? AND ca.alias = ?""",
            (collection_id, payload["alias"]),
        ).fetchone()
        RegistryStorage._reassign_collection_alias_cursor(
            conn, collection_id, payload["alias"], int(link["id"])
        )
        payload["collection_version"] = int(link["collection_version"])
        payload["previous_version"] = (
            None if current is None else int(current["collection_version"])
        )
        return {"previous_version": payload["previous_version"]}

    @staticmethod
    def _apply_unlink(conn: sqlite3.Connection, payload: dict) -> dict:
        collection_id = RegistryStorage._collection_id_cursor(
            conn, payload["collection"]
        )
        if collection_id is None:
            raise ValueError(
                f"Unlink event for unknown collection {payload['collection']!r}."
            )
        link = RegistryStorage._find_link_cursor(conn, collection_id, payload)
        if link is None:
            return {"removed_aliases": [], "latest_version": None}
        link_id = int(link["id"])
        removed_aliases = sorted(
            row["alias"]
            for row in conn.execute(
                "SELECT alias FROM collection_aliases WHERE link_id = ?", (link_id,)
            ).fetchall()
        )
        conn.execute("DELETE FROM collection_aliases WHERE link_id = ?", (link_id,))
        conn.execute("DELETE FROM collection_links WHERE id = ?", (link_id,))
        latest_version = (
            RegistryStorage._reassign_latest_cursor(conn, collection_id)
            if "latest" in removed_aliases
            else RegistryStorage._latest_version_cursor(conn, collection_id)
        )
        payload["removed_aliases"] = removed_aliases
        payload["latest_version"] = latest_version
        return {"removed_aliases": removed_aliases, "latest_version": latest_version}

    @staticmethod
    def _alias_points_at_cursor(
        conn: sqlite3.Connection, collection: str, alias: str, link_id: int
    ) -> bool:
        """Whether `alias` already points at `link_id`, in which case promoting
        it is an exact no-op that should write neither rows nor an event."""
        current = conn.execute(
            """SELECT ca.link_id FROM collection_aliases ca
            JOIN collections c ON c.id = ca.collection_id
            WHERE c.name = ? AND ca.alias = ?""",
            (collection, alias),
        ).fetchone()
        return current is not None and int(current["link_id"]) == link_id

    @staticmethod
    def _promote_alias_cursor(
        conn: sqlite3.Connection,
        registry: str,
        collection: str,
        alias: str,
        link_id: int,
        source: dict,
        run_name: str | None,
        run_id: str | None,
    ) -> None:
        """Move `alias` onto the link at `source` through a ``promote`` event.
        An exact no-op (the alias already points at `link_id`) writes nothing."""
        if RegistryStorage._alias_points_at_cursor(conn, collection, alias, link_id):
            return
        RegistryStorage._commit_event_cursor(
            conn,
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
        source_space_id: str | None = None,
        source_bucket_id: str | None = None,
    ) -> dict:
        """Link one artifact version into `registry`/`collection` and return
        the link record.

        The registry must already exist. The collection is created on first
        use and adopts the linked version's type; later links must match it.
        Re-linking an already-linked source version returns the existing
        link (``created`` False) and still moves the requested `aliases`.
        An alias move may go backward (a rollback). ``latest`` is managed
        automatically and always follows the newest linked version; passing
        it in `aliases` is a no-op rather than an error (matching wandb).

        The source's storage coordinates (`source_space_id` /
        `source_bucket_id`, None for a local project) are recorded on the link,
        because where the bytes live cannot be derived from the source
        coordinates alone once a registry is shared across machines."""
        validate_collection_name(collection)
        validate_collection_type(type)
        user_aliases = [
            alias for alias in cas.validate_aliases(aliases) if alias != "latest"
        ]
        project = registry_project_name(registry)
        db_path = RegistryStorage._require_registry(registry)
        source = {
            "source_project": source_project,
            "source_artifact": source_artifact,
            "source_version": source_version,
        }
        with SQLiteStorage._get_process_lock(project):
            with SQLiteStorage._get_connection(db_path) as conn:
                RegistryStorage._create_or_get_collection_cursor(
                    conn, registry, collection, type, None
                )
                link_event = new_event(
                    "link",
                    {
                        "registry": registry,
                        "collection": collection,
                        **source,
                        "source_space_id": source_space_id,
                        "source_bucket_id": source_bucket_id,
                        "run_name": run_name,
                        "run_id": run_id,
                    },
                )
                linked = RegistryStorage.apply_event_cursor(conn, link_event)
                link_id = linked["link_id"]
                created = linked["created"]
                if created:
                    RegistryStorage._store_event_cursor(conn, link_event)
                for alias in user_aliases:
                    RegistryStorage._promote_alias_cursor(
                        conn,
                        registry,
                        collection,
                        alias,
                        link_id,
                        source,
                        run_name,
                        run_id,
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
        with SQLiteStorage._get_process_lock(project):
            with SQLiteStorage._get_connection(db_path) as conn:
                collection_id, created = (
                    RegistryStorage._create_or_get_collection_cursor(
                        conn, registry, name, type, description
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
        the ``unlink`` event. Removing the version that holds ``latest`` moves
        that alias to the highest remaining version in the same transaction;
        ``latest_version`` (in the event and the returned record) is the version
        ``latest`` points at afterwards, None when the collection is left
        empty. The version number is never reused. Raises
        ValueError when the registry, collection, or version does not
        exist."""
        project = registry_project_name(registry)
        db_path = RegistryStorage._require_registry(registry)
        with SQLiteStorage._get_process_lock(project):
            with SQLiteStorage._get_connection(db_path) as conn:
                resolved = RegistryStorage._resolve_link_cursor(
                    conn, registry, collection, collection_version
                )
                removed = RegistryStorage._commit_event_cursor(
                    conn,
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
               source_artifact, source_version, source_space_id,
               source_bucket_id, created_at
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
                    "source_space_id": link["source_space_id"],
                    "source_bucket_id": link["source_bucket_id"],
                    "aliases": sorted(aliases_by_link.get(int(link["id"]), [])),
                    "created_at": link["created_at"],
                }
            )
        return links_by_collection

    @staticmethod
    def get_collection_cursor(conn: sqlite3.Connection, name: str) -> dict | None:
        """`get_collection` against an already-open projection, shared by the
        local database and a remote registry's local projection."""
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
        links = RegistryStorage._links_by_collection_cursor(conn, collection_id).get(
            collection_id, []
        )
        return {
            "name": row["name"],
            "type": row["type"],
            "description": row["description"],
            "created_at": row["created_at"],
            "links": links,
        }

    @staticmethod
    def list_collections_cursor(conn: sqlite3.Connection) -> list[dict]:
        """`list_collections` against an already-open projection."""
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
    def get_events_cursor(conn: sqlite3.Connection) -> list[dict]:
        """`get_events` against an already-open projection."""
        try:
            rows = conn.execute(
                """SELECT id, event_uid, ts, kind, payload
                FROM registry_events ORDER BY id"""
            ).fetchall()
        except sqlite3.OperationalError:
            return []
        return [
            {
                "id": int(row["id"]),
                "event_uid": row["event_uid"],
                "ts": row["ts"],
                "kind": row["kind"],
                "payload": orjson.loads(row["payload"]),
            }
            for row in rows
        ]

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
            return RegistryStorage.get_collection_cursor(conn, name)

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
            return RegistryStorage.list_collections_cursor(conn)

    @staticmethod
    def get_events(registry: str) -> list[dict]:
        """The registry's append-only audit log, oldest first, with payloads
        parsed back into dicts. Returns [] when the registry does not exist."""
        SQLiteStorage._ensure_hub_loaded()
        db_path = SQLiteStorage.get_project_db_path(registry_project_name(registry))
        if not db_path.exists():
            return []
        with SQLiteStorage._get_connection(db_path) as conn:
            return RegistryStorage.get_events_cursor(conn)
