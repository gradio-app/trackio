"""Select Trackio's logical persistence provider.

SQLite and Turso share the historical ``SQLiteStorage`` implementation. Apache
Doris is not SQLite-compatible and therefore implements the same logical
server operations in a separate provider.
"""

from __future__ import annotations

import os
from typing import Any

import pymysql

from trackio import database as sqlite_database
from trackio.doris_storage import DorisStorage
from trackio.sqlite_storage import SQLiteStorage

SUPPORTED_ENGINES = ("turso", "sqlite", "doris")
_sqlite_operational_errors = sqlite_database.OperationalError
if not isinstance(_sqlite_operational_errors, tuple):
    _sqlite_operational_errors = (_sqlite_operational_errors,)
StorageOperationalError = (
    *_sqlite_operational_errors,
    pymysql.err.OperationalError,
    pymysql.err.InterfaceError,
)


def is_retryable_storage_error(error: BaseException) -> bool:
    if isinstance(error, pymysql.err.InterfaceError):
        return True
    if isinstance(error, pymysql.err.OperationalError):
        code = error.args[0] if error.args else None
        return code in {1047, 1205, 2003, 2006, 2013}
    message = str(error).lower()
    return any(
        marker in message
        for marker in (
            "database is locked",
            "disk i/o error",
            "readonly",
            "temporarily unavailable",
        )
    )


def selected_engine() -> str:
    engine = os.environ.get("TRACKIO_DATABASE_ENGINE", "turso").strip().lower()
    if engine not in SUPPORTED_ENGINES:
        choices = ", ".join(repr(choice) for choice in SUPPORTED_ENGINES)
        raise RuntimeError(f"TRACKIO_DATABASE_ENGINE must be one of {choices}")
    return engine


def get_storage(engine: str | None = None) -> type[Any]:
    resolved = (engine or selected_engine()).strip().lower()
    if resolved not in SUPPORTED_ENGINES:
        choices = ", ".join(repr(choice) for choice in SUPPORTED_ENGINES)
        raise RuntimeError(f"TRACKIO_DATABASE_ENGINE must be one of {choices}")
    if resolved == "doris":
        return DorisStorage

    return SQLiteStorage


Storage = get_storage()
