import pytest

from trackio.doris_schema import (
    MANAGED_TABLES,
    SCHEMA_VERSION,
    negotiate_schema,
    schema_statements,
)
from trackio.doris_storage import DorisStorage


def test_empty_database_is_the_only_bootstrap_state():
    assert negotiate_schema(set(), None) == "bootstrap"
    assert negotiate_schema({"unrelated_application_table"}, None) == "bootstrap"


def test_complete_current_schema_is_ready_without_bootstrap():
    assert negotiate_schema(set(MANAGED_TABLES), SCHEMA_VERSION) == "ready"


@pytest.mark.parametrize(
    ("tables", "version", "message"),
    [
        ({"metrics"}, None, "unversioned partial"),
        ({"schema_versions", "metrics"}, None, "unversioned partial"),
        (set(MANAGED_TABLES), SCHEMA_VERSION + 1, "newer"),
        (set(MANAGED_TABLES), SCHEMA_VERSION - 1, "explicit migration"),
        (
            set(MANAGED_TABLES) - {"artifact_aliases"},
            SCHEMA_VERSION,
            "artifact_aliases",
        ),
    ],
)
def test_nonempty_incompatible_schema_fails_closed(tables, version, message):
    with pytest.raises(RuntimeError, match=message):
        negotiate_schema(tables, version)


def test_schema_version_table_is_created_first_and_recorded_separately():
    statements = schema_statements()

    assert "CREATE TABLE IF NOT EXISTS schema_versions" in statements[0]
    assert len(statements) == len(MANAGED_TABLES)
    assert all(
        "INSERT INTO schema_versions" not in statement for statement in statements
    )


class _SchemaCursor:
    def __init__(self, tables, version):
        self.tables = tables
        self.version = version
        self.executed = []
        self.current = ""

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def execute(self, query, params=None):
        self.current = " ".join(query.split())
        self.executed.append((self.current, params))

    def fetchall(self):
        if "information_schema.tables" in self.current:
            return [{"table_name": table} for table in self.tables]
        return []

    def fetchone(self):
        if "SELECT version FROM schema_versions" in self.current:
            return {"version": self.version} if self.version is not None else None
        return None


class _SchemaConnection:
    def __init__(self, cursor):
        self._cursor = cursor
        self.closed = False

    def cursor(self):
        return self._cursor

    def close(self):
        self.closed = True


def _install_schema_connection(monkeypatch, tables, version):
    cursor = _SchemaCursor(tables, version)
    connection = _SchemaConnection(cursor)
    settings = {
        "host": "doris.internal",
        "port": 9030,
        "user": "trackio",
        "password": "",
        "database": "trackio_test",
    }
    monkeypatch.setattr(DorisStorage, "_schema_ready", False)
    monkeypatch.setattr(DorisStorage, "_schema_target", None)
    monkeypatch.setattr(
        DorisStorage, "_settings", classmethod(lambda cls: settings.copy())
    )
    monkeypatch.setattr(
        "trackio.doris_storage.pymysql.connect",
        lambda **kwargs: connection,
    )
    return cursor, connection


def test_current_schema_negotiation_executes_no_ddl(monkeypatch):
    cursor, connection = _install_schema_connection(
        monkeypatch,
        set(MANAGED_TABLES),
        SCHEMA_VERSION,
    )

    DorisStorage._ensure_schema()

    statements = [query for query, _ in cursor.executed]
    assert not any(query.startswith("CREATE ") for query in statements)
    assert not any(query.startswith("INSERT ") for query in statements)
    assert connection.closed is True


def test_newer_schema_fails_before_any_write(monkeypatch):
    cursor, _ = _install_schema_connection(
        monkeypatch,
        set(MANAGED_TABLES),
        SCHEMA_VERSION + 1,
    )

    with pytest.raises(RuntimeError, match="newer"):
        DorisStorage._ensure_schema()

    statements = [query for query, _ in cursor.executed]
    assert not any(
        query.startswith(("CREATE ", "INSERT ", "UPDATE ", "DELETE "))
        for query in statements
    )


def test_empty_database_records_version_only_after_all_tables(monkeypatch):
    cursor, _ = _install_schema_connection(monkeypatch, set(), None)

    DorisStorage._ensure_schema()

    statements = [query for query, _ in cursor.executed]
    version_write = next(
        index
        for index, query in enumerate(statements)
        if query.startswith("INSERT INTO schema_versions")
    )
    table_writes = [
        index
        for index, query in enumerate(statements)
        if query.startswith("CREATE TABLE")
    ]
    assert len(table_writes) == len(MANAGED_TABLES)
    assert version_write > max(table_writes)
