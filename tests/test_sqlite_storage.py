import os
import sqlite3
import tempfile

import pytest

from trackio.sqlite_storage import SQLiteStorage


@pytest.fixture
def temp_db(monkeypatch):
    with tempfile.TemporaryDirectory() as tmpdir:
        monkeypatch.setattr("trackio.sqlite_storage.TRACKIO_DIR", tmpdir)
        yield tmpdir


def test_init_creates_tables_and_config(temp_db):
    storage = SQLiteStorage("proj1", "run1", {"foo": "bar"})
    assert os.path.exists(storage.db_path)
    with sqlite3.connect(storage.db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT config FROM configs WHERE project_name=? AND run_name=?",
            ("proj1", "run1"),
        )
        row = cursor.fetchone()
        assert row is not None
        assert "foo" in row[0]


def test_log_and_get_metrics(temp_db):
    storage = SQLiteStorage("proj1", "run1", {})
    metrics = {"acc": 0.9}
    storage.log(metrics)
    results = storage.get_metrics("proj1", "run1")
    assert len(results) == 1
    assert results[0]["acc"] == 0.9
    assert "timestamp" in results[0]


def test_get_projects_and_runs(temp_db):
    storage = SQLiteStorage("proj1", "run1", {})
    storage.log({"a": 1})
    storage2 = SQLiteStorage("proj2", "run2", {})
    storage2.log({"b": 2})
    projects = set(storage.get_projects())
    assert {"proj1", "proj2"}.issubset(projects)
    runs = set(storage.get_runs("proj1"))
    assert "run1" in runs
