import json
import sqlite3
from contextlib import contextmanager

import pytest

from trackio.doris_migration import (
    AUTHORITATIVE_TABLES,
    _records_evidence,
    _target_evidence,
    inspect_sqlite_project,
    migrate_sqlite_to_doris,
)
from trackio.doris_storage import DorisStorage


def _source_database(path):
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            """
            CREATE TABLE metrics (
                id INTEGER PRIMARY KEY,
                run_id TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                run_name TEXT NOT NULL,
                step INTEGER NOT NULL,
                metrics TEXT NOT NULL,
                log_id TEXT,
                space_id TEXT
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE configs (
                id INTEGER PRIMARY KEY,
                run_id TEXT NOT NULL,
                run_name TEXT NOT NULL,
                config TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        connection.executemany(
            """
            INSERT INTO metrics
                (id, run_id, timestamp, run_name, step, metrics, log_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    1,
                    "run-v1",
                    "2026-07-26T11:00:00+00:00",
                    "run",
                    0,
                    '{"loss":1.0}',
                    "log-0",
                ),
                (
                    2,
                    "run-v1",
                    "2026-07-26T11:00:01+00:00",
                    "run",
                    1,
                    '{"loss":0.5}',
                    "log-1",
                ),
            ],
        )
        connection.execute(
            """
            INSERT INTO configs
                (id, run_id, run_name, config, created_at)
            VALUES (1, 'run-v1', 'run', '{"engine":"sqlite"}',
                    '2026-07-26T11:00:00+00:00')
            """
        )
        connection.commit()
    finally:
        connection.close()


def test_dry_run_inspects_without_connecting_to_doris(tmp_path):
    source = tmp_path / "migration-project.db"
    receipt = tmp_path / "receipt.json"
    _source_database(source)

    inspected = inspect_sqlite_project(source)
    assert inspected["tables"]["metrics"] == 2
    assert inspected["tables"]["configs"] == 1
    assert inspected["run_count"] == 1

    result = migrate_sqlite_to_doris(source, receipt, dry_run=True)
    assert result["dry_run"] is True
    assert result["verified"] is False
    stored = json.loads(receipt.read_text())
    assert stored["projects"][0]["source"]["sha256"] == inspected["sha256"]


def test_project_filter_fails_closed_for_unknown_project(tmp_path):
    source = tmp_path / "migration-project.db"
    _source_database(source)

    try:
        migrate_sqlite_to_doris(
            tmp_path,
            tmp_path / "receipt.json",
            dry_run=True,
            projects=("missing-project",),
        )
    except FileNotFoundError as error:
        assert "missing-project" in str(error)
    else:
        raise AssertionError("missing project filter should fail")


def test_snapshot_includes_committed_wal_rows(tmp_path):
    source = tmp_path / "wal-project.db"
    _source_database(source)
    connection = sqlite3.connect(source)
    try:
        assert connection.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
        connection.execute("PRAGMA wal_autocheckpoint=0")
        connection.execute(
            """
            INSERT INTO metrics
                (id, run_id, timestamp, run_name, step, metrics, log_id)
            VALUES (3, 'run-v1', '2026-07-26T11:00:02+00:00',
                    'run', 2, '{"loss":0.25}', 'log-2')
            """
        )
        connection.commit()
        assert source.with_name(f"{source.name}-wal").is_file()

        inspected = inspect_sqlite_project(source)
    finally:
        connection.close()

    assert inspected["wal_present"] is True
    assert inspected["tables"]["metrics"] == 3
    assert inspected["evidence"]["metrics"]["count"] == 3
    assert inspected["sha256"] == inspected["snapshot_sha256"]


def test_canonical_evidence_detects_same_count_different_content():
    first = {
        table: ([{"value": 1}] if table == "metrics" else [])
        for table in AUTHORITATIVE_TABLES
    }
    second = {
        table: ([{"value": 2}] if table == "metrics" else [])
        for table in AUTHORITATIVE_TABLES
    }

    first_evidence = _records_evidence(first)
    second_evidence = _records_evidence(second)

    assert first_evidence["metrics"]["count"] == second_evidence["metrics"]["count"]
    assert first_evidence["metrics"]["sha256"] != second_evidence["metrics"]["sha256"]


def test_target_verification_connection_never_initializes_schema(monkeypatch):
    calls = []

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def execute(self, query, params):
            calls.append((query, params))

        def fetchall(self):
            return []

    class Connection:
        def cursor(self):
            return Cursor()

    @contextmanager
    def connection(*, initialize=True, include_database=True):
        del include_database
        assert initialize is False
        yield Connection()

    monkeypatch.setattr(DorisStorage, "_connection", staticmethod(connection))

    evidence = _target_evidence("verify-only-project")

    assert set(evidence) == set(AUTHORITATIVE_TABLES)
    assert all(value["count"] == 0 for value in evidence.values())
    assert calls


def test_verify_only_does_not_call_schema_initializer(tmp_path, monkeypatch):
    source = tmp_path / "migration-project.db"
    _source_database(source)
    source_evidence = inspect_sqlite_project(source)["evidence"]

    def forbidden_initialize():
        raise AssertionError("verify-only must not initialize Doris")

    monkeypatch.setattr(DorisStorage, "initialize", forbidden_initialize)
    monkeypatch.setattr(
        "trackio.doris_migration._target_evidence",
        lambda project: source_evidence,
    )

    result = migrate_sqlite_to_doris(
        source,
        tmp_path / "receipt.json",
        verify_only=True,
    )

    assert result["verified"] is True
    assert result["projects"][0]["target_evidence"] == source_evidence


def test_verify_only_rejects_equal_counts_with_different_content(tmp_path, monkeypatch):
    source = tmp_path / "migration-project.db"
    receipt_path = tmp_path / "receipt.json"
    _source_database(source)
    target_evidence = inspect_sqlite_project(source)["evidence"]
    target_evidence["metrics"] = {
        **target_evidence["metrics"],
        "sha256": "0" * 64,
    }
    monkeypatch.setattr(
        "trackio.doris_migration._target_evidence",
        lambda project: target_evidence,
    )

    with pytest.raises(RuntimeError, match="reconciliation failed"):
        migrate_sqlite_to_doris(
            source,
            receipt_path,
            verify_only=True,
        )

    receipt = json.loads(receipt_path.read_text())
    mismatch = receipt["projects"][0]["mismatches"]["metrics"]
    assert mismatch["source"]["count"] == mismatch["target"]["count"]
    assert mismatch["source"]["sha256"] != mismatch["target"]["sha256"]


def test_snapshot_evidence_covers_artifacts_aliases_and_links(tmp_path):
    source = tmp_path / "artifact-project.db"
    _source_database(source)
    manifest = [{"path": "adapter.bin", "digest": "a" * 64, "size": 9}]
    _, manifest_digest, _ = DorisStorage._canonical_manifest(manifest)
    connection = sqlite3.connect(source)
    try:
        connection.executescript(
            """
            CREATE TABLE artifacts (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                type TEXT NOT NULL,
                description TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE artifact_versions (
                id INTEGER PRIMARY KEY,
                artifact_id INTEGER NOT NULL,
                version INTEGER NOT NULL,
                manifest_digest TEXT NOT NULL,
                manifest TEXT NOT NULL,
                metadata TEXT,
                size_bytes INTEGER NOT NULL,
                producer_run_id TEXT,
                producer_run_name TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE artifact_aliases (
                artifact_id INTEGER NOT NULL,
                alias TEXT NOT NULL,
                artifact_version_id INTEGER NOT NULL
            );
            CREATE TABLE run_artifact_links (
                id INTEGER PRIMARY KEY,
                run_id TEXT,
                run_name TEXT,
                artifact_version_id INTEGER NOT NULL,
                direction TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )
        connection.execute(
            """
            INSERT INTO artifacts
                (id, name, type, description, created_at)
            VALUES (1, 'adapter', 'model', 'retained',
                    '2026-07-01T00:00:00+00:00')
            """
        )
        connection.execute(
            """
            INSERT INTO artifact_versions
                (id, artifact_id, version, manifest_digest, manifest, metadata,
                 size_bytes, producer_run_id, producer_run_name, created_at)
            VALUES (2, 1, 4, ?, ?, '{"format":"peft"}', 9,
                    'run-v1', 'run', '2026-07-02T00:00:00+00:00')
            """,
            (manifest_digest, json.dumps(manifest)),
        )
        connection.execute(
            """
            INSERT INTO artifact_aliases
                (artifact_id, alias, artifact_version_id)
            VALUES (1, 'candidate', 2)
            """
        )
        connection.execute(
            """
            INSERT INTO run_artifact_links
                (id, run_id, run_name, artifact_version_id, direction, created_at)
            VALUES (3, 'run-v1', 'run', 2, 'output',
                    '2026-07-03T00:00:00+00:00')
            """
        )
        connection.commit()
    finally:
        connection.close()

    evidence = inspect_sqlite_project(source)["evidence"]

    assert evidence["artifacts"]["count"] == 1
    assert evidence["artifact_versions"]["count"] == 1
    assert evidence["artifact_aliases"]["count"] == 1
    assert evidence["run_artifact_links"]["count"] == 1
