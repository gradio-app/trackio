from trackio.sqlite_storage import SQLiteStorage


def _pragma(conn, name):
    return conn.execute(f"PRAGMA {name}").fetchone()[0]


def test_mmap_disabled_by_default(temp_dir):
    db_path = SQLiteStorage.init_db("proj")
    with SQLiteStorage._get_connection(db_path) as conn:
        assert _pragma(conn, "mmap_size") == 0
        assert _pragma(conn, "journal_mode") == "wal"
        assert _pragma(conn, "synchronous") == 1
        assert _pragma(conn, "temp_store") == 2


def test_pragma_env_overrides(temp_dir, monkeypatch):
    monkeypatch.setenv("TRACKIO_SQLITE_MMAP_SIZE", "1048576")
    monkeypatch.setenv("TRACKIO_SQLITE_SYNCHRONOUS", "full")
    monkeypatch.setenv("TRACKIO_SQLITE_JOURNAL_MODE", "delete")
    monkeypatch.setenv("TRACKIO_SQLITE_TEMP_STORE", "file")
    monkeypatch.setenv("TRACKIO_SQLITE_LOCKING_MODE", "exclusive")
    db_path = SQLiteStorage.init_db("proj-overrides")
    with SQLiteStorage._get_connection(db_path) as conn:
        assert _pragma(conn, "mmap_size") == 1048576
        assert _pragma(conn, "synchronous") == 2
        assert _pragma(conn, "journal_mode") == "delete"
        assert _pragma(conn, "temp_store") == 1
        assert _pragma(conn, "locking_mode") == "exclusive"


def test_invalid_pragma_env_values_ignored(temp_dir, monkeypatch):
    monkeypatch.setenv("TRACKIO_SQLITE_MMAP_SIZE", "not-a-number")
    monkeypatch.setenv("TRACKIO_SQLITE_SYNCHRONOUS", "banana")
    monkeypatch.setenv("TRACKIO_SQLITE_LOCKING_MODE", "DROP TABLE metrics")
    db_path = SQLiteStorage.init_db("proj-invalid")
    with SQLiteStorage._get_connection(db_path) as conn:
        assert _pragma(conn, "mmap_size") == 0
        assert _pragma(conn, "synchronous") == 1
        assert _pragma(conn, "locking_mode") == "normal"
