import os
import subprocess
import sys
from contextlib import contextmanager

import pymysql
import pytest

from trackio.doris_storage import DorisStorage
from trackio.sqlite_storage import SQLiteStorage
from trackio.storage import get_storage, is_retryable_storage_error


@pytest.mark.parametrize("engine", ["sqlite", "turso"])
def test_embedded_engines_keep_sqlite_storage(engine):
    assert get_storage(engine) is SQLiteStorage


def test_unknown_engine_fails_with_supported_choices():
    with pytest.raises(RuntimeError, match="'turso'.*'sqlite'.*'doris'"):
        get_storage("postgres")


def test_doris_selection_does_not_open_a_sqlite_database(tmp_path):
    env = {
        **os.environ,
        "TRACKIO_DATABASE_ENGINE": "doris",
        "TRACKIO_DORIS_HOST": "127.0.0.1",
        "TRACKIO_DORIS_DATABASE": "trackio_test",
        "TRACKIO_DORIS_USER": "trackio",
        "TRACKIO_DIR": str(tmp_path),
    }
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from trackio.storage import Storage; "
                "from trackio.doris_storage import DorisStorage; "
                "assert Storage is DorisStorage"
            ),
        ],
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert list(tmp_path.glob("*.db")) == []


@pytest.mark.parametrize("code", [1047, 1205, 2003, 2006, 2013])
def test_transient_mysql_failures_are_retryable(code):
    assert is_retryable_storage_error(pymysql.err.OperationalError(code, "transient"))


def test_mysql_auth_failure_is_not_retried():
    assert not is_retryable_storage_error(
        pymysql.err.OperationalError(1045, "access denied")
    )


def test_doris_run_name_resolution_uses_run_creation_time():
    class Cursor:
        query = ""
        params = ()

        def execute(self, query, params):
            self.query = query
            self.params = params

        def fetchone(self):
            return {"run_id": "newer-run"}

    cursor = Cursor()

    resolved = DorisStorage._resolve_run_id(
        cursor,
        "project",
        "same-name",
        None,
    )

    assert resolved == "newer-run"
    assert "MIN(timestamp) AS created_at" in cursor.query
    assert "GROUP BY run_id" in cursor.query
    assert "ORDER BY created_at DESC" in cursor.query
    assert cursor.params == ("project", "same-name")


def test_doris_run_records_match_sqlite_metric_and_artifact_authority():
    records = DorisStorage._run_records_from_evidence(
        [
            {
                "run_id": "metric-v1",
                "run_name": "train",
                "created_at": "2026-07-02T00:00:00+00:00",
            },
            {
                "run_id": "metric-v1",
                "run_name": "train",
                "created_at": "2026-07-03T00:00:00+00:00",
            },
        ],
        [
            {
                "run_id": None,
                "run_name": "artifact-only",
                "created_at": "2026-07-01T00:00:00+00:00",
            },
            {
                "run_id": "artifact-v1",
                "run_name": "artifact-only",
                "created_at": "2026-07-01T00:00:01+00:00",
            },
            {
                "run_id": None,
                "run_name": "train",
                "created_at": "2026-06-30T00:00:00+00:00",
            },
            {
                "run_id": None,
                "run_name": None,
                "created_at": "2026-07-04T00:00:00+00:00",
            },
        ],
    )

    assert records == [
        {
            "id": "artifact-v1",
            "name": "artifact-only",
            "created_at": "2026-07-01T00:00:01+00:00",
        },
        {
            "id": "metric-v1",
            "name": "train",
            "created_at": "2026-07-02T00:00:00+00:00",
        },
    ]
    assert all(record["id"] != "None" for record in records)


def test_doris_artifact_counts_fold_legacy_links_without_double_counting():
    records = [
        {
            "id": "train-v1",
            "name": "train",
            "created_at": "2026-07-01T00:00:00+00:00",
        }
    ]
    rows = [
        {
            "run_id": None,
            "run_name": "train",
            "version_id": 7,
            "direction": "output",
        },
        {
            "run_id": "train-v1",
            "run_name": "train",
            "version_id": 7,
            "direction": "output",
        },
        {
            "run_id": "train-v1",
            "run_name": "train",
            "version_id": 8,
            "direction": "input",
        },
    ]

    assert DorisStorage._artifact_link_counts_from_rows(rows, records) == [
        {
            "run_id": "train-v1",
            "run_name": "train",
            "input": 1,
            "output": 1,
        }
    ]


def test_doris_at_time_window_matches_sqlite_filter_precedence(monkeypatch):
    rows = [
        {"timestamp": "2026-07-27T10:00:00Z", "step": 0, "loss": 3.0},
        {
            "timestamp": "2026-07-27T10:00:02+00:00",
            "step": 1,
            "loss": 2.0,
        },
        {
            "timestamp": "2026-07-27T10:00:05+00:00",
            "step": 2,
            "loss": 1.0,
        },
    ]
    monkeypatch.setattr(
        DorisStorage,
        "get_logs",
        classmethod(lambda cls, *args, **kwargs: rows),
    )

    around_time = DorisStorage.get_metric_values(
        "project",
        "run",
        "loss",
        at_time="2026-07-27T10:00:02+00:00",
        window=2,
    )
    exact_step = DorisStorage.get_snapshot(
        "project",
        "run",
        step=2,
        at_time="2026-07-27T10:00:00+00:00",
        window=10,
    )

    assert [row["step"] for row in around_time] == [0, 1]
    assert exact_step["loss"] == [
        {
            "timestamp": "2026-07-27T10:00:05+00:00",
            "step": 2,
            "value": 1.0,
        }
    ]


def test_doris_tab_flags_classify_payloads_and_trace_types(monkeypatch):
    seen = []

    class Cursor:
        query = ""

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def execute(self, query, params):
            self.query = " ".join(query.split())
            seen.append((self.query, params))

        def fetchone(self):
            if (
                '"_type":"trackio.image"' in self.query
                or '"_type":"trackio.markdown"' in self.query
                or "trace_type = 'verifiers'" in self.query
            ):
                return {"present": 1}
            return None

    class Connection:
        def cursor(self):
            return Cursor()

    @contextmanager
    def connection(**kwargs):
        del kwargs
        yield Connection()

    monkeypatch.setattr(DorisStorage, "_connection", staticmethod(connection))

    assert DorisStorage.get_tab_availability_flags("project") == {
        "metrics": False,
        "media": True,
        "reports": True,
        "system": False,
        "traces": False,
        "alerts": False,
        "verifiers_traces": True,
        "artifacts": False,
    }
    assert any("REGEXP" in query for query, _ in seen)
    assert any("trace_type = 'trackio'" in query for query, _ in seen)


@pytest.mark.parametrize(
    ("description", "expects_update"),
    [(None, False), ("revised", True)],
)
def test_doris_artifact_relog_preserves_identity_fields(
    monkeypatch, description, expects_update
):
    executed = []

    class Cursor:
        query = ""

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def execute(self, query, params):
            self.query = " ".join(query.split())
            executed.append((self.query, params))

        def fetchone(self):
            if "SELECT artifact_type FROM artifacts" in self.query:
                return {"artifact_type": "model"}
            if "SELECT version_id, version_number FROM artifact_versions" in self.query:
                return {"version_id": 7, "version_number": 0}
            if "SELECT version_number FROM artifact_aliases" in self.query:
                return None
            raise AssertionError(f"unexpected fetchone query: {self.query}")

    class Connection:
        def cursor(self):
            return Cursor()

    @contextmanager
    def connection(**kwargs):
        del kwargs
        yield Connection()

    monkeypatch.setattr(DorisStorage, "_connection", staticmethod(connection))
    monkeypatch.setattr(
        DorisStorage,
        "get_artifact_manifest",
        classmethod(
            lambda cls, project, name, spec: {
                "version_id": 7,
                "version": 0,
            }
        ),
    )

    DorisStorage.commit_artifact_version(
        project="project",
        name="adapter",
        type="model",
        description=description,
        manifest=[{"path": "model.bin", "digest": "a" * 64, "size": 1}],
        metadata=None,
        aliases=None,
        run_name="producer",
        run_id="producer-v1",
    )

    statements = [query for query, _ in executed]
    assert not any("INSERT INTO artifacts " in query for query in statements)
    assert (
        any("UPDATE artifacts SET description" in query for query in statements)
        is expects_update
    )


def test_artifact_migration_preserves_versions_and_lineage_timestamps(monkeypatch):
    executed = []

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def execute(self, query, params):
            executed.append((" ".join(query.split()), params))

    class Connection:
        def cursor(self):
            return Cursor()

    @contextmanager
    def connection(**kwargs):
        del kwargs
        yield Connection()

    monkeypatch.setattr(
        DorisStorage,
        "_connection",
        staticmethod(connection),
    )
    manifest = [{"path": "model.bin", "digest": "a" * 64, "size": 7}]
    _, manifest_digest, _ = DorisStorage._canonical_manifest(manifest)

    DorisStorage.import_artifact_graph(
        "project",
        artifacts=[
            {
                "id": 10,
                "name": "adapter",
                "type": "model",
                "description": "retained",
                "created_at": "2026-07-01T00:00:00+00:00",
            }
        ],
        versions=[
            {
                "id": 20,
                "artifact_id": 10,
                "version": 4,
                "manifest_digest": manifest_digest,
                "manifest": manifest,
                "metadata": {"format": "peft"},
                "size_bytes": 7,
                "producer_run_id": "producer-v1",
                "producer_run_name": "producer",
                "created_at": "2026-07-02T00:00:00+00:00",
            }
        ],
        aliases=[
            {
                "artifact_id": 10,
                "artifact_version_id": 20,
                "alias": "candidate",
            }
        ],
        links=[
            {
                "run_id": "consumer-v1",
                "run_name": "consumer",
                "artifact_version_id": 20,
                "direction": "input",
                "created_at": "2026-07-03T00:00:00+00:00",
            }
        ],
    )

    artifact_write = next(
        item for item in executed if "INSERT INTO artifacts" in item[0]
    )
    version_write = next(
        item for item in executed if "INSERT INTO artifact_versions" in item[0]
    )
    alias_write = next(
        item for item in executed if "INSERT INTO artifact_aliases" in item[0]
    )
    link_write = next(
        item for item in executed if "INSERT INTO run_artifact_links" in item[0]
    )
    assert artifact_write[1][-1] == "2026-07-01T00:00:00+00:00"
    assert version_write[1][3] == 4
    assert version_write[1][-1] == "2026-07-02T00:00:00+00:00"
    assert alias_write[1][4] == 4
    assert link_write[1][-1] == "2026-07-03T00:00:00+00:00"
