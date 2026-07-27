"""Database driver boundary for Trackio's SQLite-compatible metadata store."""

from __future__ import annotations

import os
import sqlite3 as _sqlite
from typing import Any

import turso as _turso

ENGINE = os.environ.get("TRACKIO_DATABASE_ENGINE", "turso").strip().lower()
if ENGINE not in {"turso", "sqlite", "doris"}:
    raise RuntimeError("TRACKIO_DATABASE_ENGINE must be 'turso', 'sqlite', or 'doris'")

# This module is deliberately the SQLite-compatible driver boundary. Doris is
# selected one layer above it through ``trackio.storage``. Keep the sqlite
# symbols importable so legacy modules can load, but fail closed if a
# SQLite-specific caller accidentally attempts to open a database in Doris
# mode.
_driver = _turso if ENGINE == "turso" else _sqlite


class _TursoConnection:
    """Small sqlite3-compatibility wrapper around pyturso connections.

    pyturso currently permits operations after ``close()``. Trackio relies on
    sqlite3's stricter lifecycle contract, so enforce it at the driver boundary
    instead of leaking backend-specific behavior throughout the application.
    """

    def __init__(self, connection: Any) -> None:
        object.__setattr__(self, "_connection", connection)
        object.__setattr__(self, "_closed", False)

    def _check_open(self) -> None:
        if self._closed:
            raise _sqlite.ProgrammingError("Cannot operate on a closed database.")

    def close(self) -> None:
        if not self._closed:
            self._connection.close()
            object.__setattr__(self, "_closed", True)

    def __enter__(self) -> _TursoConnection:
        self._check_open()
        self._connection.__enter__()
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> Any:
        self._check_open()
        return self._connection.__exit__(exc_type, exc, traceback)

    def __getattr__(self, name: str) -> Any:
        self._check_open()
        return getattr(self._connection, name)

    def __setattr__(self, name: str, value: Any) -> None:
        if name in {"_connection", "_closed"}:
            object.__setattr__(self, name, value)
            return
        self._check_open()
        setattr(self._connection, name, value)


Connection = _TursoConnection if ENGINE == "turso" else _sqlite.Connection
Cursor = _driver.Cursor
Row = _driver.Row
Error = _driver.Error
DatabaseError = _driver.DatabaseError
OperationalError = (
    (_turso.OperationalError, _turso.DatabaseError)
    if ENGINE == "turso"
    else _sqlite.OperationalError
)
IntegrityError = _driver.IntegrityError
ProgrammingError = _driver.ProgrammingError
ReadonlyDatabaseError = _sqlite.DatabaseError


def connect(
    database: str,
    timeout: float = 30.0,
    check_same_thread: bool = True,
    **kwargs: Any,
) -> Any:
    """Open the configured engine while retaining sqlite3-compatible callers."""
    if ENGINE == "doris":
        raise RuntimeError(
            "SQLite-compatible connect() is unavailable when "
            "TRACKIO_DATABASE_ENGINE=doris; use the selected Trackio storage provider"
        )
    if ENGINE == "turso":
        del timeout, check_same_thread
        return _TursoConnection(_turso.connect(database, **kwargs))
    return _sqlite.connect(
        database,
        timeout=timeout,
        check_same_thread=check_same_thread,
        **kwargs,
    )


def readonly_sqlite_connect(database: str) -> _sqlite.Connection:
    """Open an immutable compatibility reader for guarded arbitrary SQL."""
    connection = _sqlite.connect(f"file:{database}?mode=ro", uri=True)
    connection.row_factory = _sqlite.Row
    return connection


sqlite_authorizer = _sqlite
