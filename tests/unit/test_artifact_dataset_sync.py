"""Dataset-mode sync coverage for artifacts.

Dataset-backed Spaces persist data by exporting the SQLite DB to parquet and
rebuilding it from parquet on restart; the `.db` file itself is never
committed. These tests pin that artifact metadata survives that round-trip and
that `load_from_dataset` pulls artifact blobs back.
"""

import os
from pathlib import Path

import pytest

from trackio.dummy_commit_scheduler import DummyCommitScheduler
from trackio.sqlite_storage import SQLiteStorage


def _build_sample_artifacts(project):
    model_id = SQLiteStorage.create_or_get_artifact(
        project, "model", "model", "a model"
    )
    v0_id, _, _ = SQLiteStorage.insert_artifact_version(
        project,
        model_id,
        [{"path": "w.bin", "digest": "a" * 64, "size": 5}],
        {"epoch": 1},
        "rid-train",
        "train",
    )
    SQLiteStorage.reassign_alias(project, model_id, "latest", v0_id)
    SQLiteStorage.insert_run_artifact_link(
        project, "train", "rid-train", v0_id, "output"
    )
    v1_id, _, _ = SQLiteStorage.insert_artifact_version(
        project,
        model_id,
        [{"path": "w.bin", "digest": "b" * 64, "size": 7}],
        {"epoch": 2},
        "rid-train",
        "train",
    )
    SQLiteStorage.reassign_alias(project, model_id, "latest", v1_id)
    SQLiteStorage.reassign_alias(project, model_id, "best", v1_id)
    SQLiteStorage.insert_run_artifact_link(
        project, "train", "rid-train", v1_id, "output"
    )
    SQLiteStorage.insert_run_artifact_link(project, "eval", "rid-eval", v1_id, "input")

    data_id = SQLiteStorage.create_or_get_artifact(project, "data", "dataset", None)
    d0_id, _, _ = SQLiteStorage.insert_artifact_version(
        project,
        data_id,
        [{"path": "d.csv", "digest": "c" * 64, "size": 3}],
        None,
        "rid-prep",
        "prep",
    )
    SQLiteStorage.reassign_alias(project, data_id, "latest", d0_id)
    SQLiteStorage.insert_run_artifact_link(project, "prep", "rid-prep", d0_id, "output")


def _snapshot(project):
    snap = {"versions": {}, "manifests": {}, "lineage": {}}
    for name in ("data", "model"):
        latest = SQLiteStorage.get_artifact_manifest(project, name, None)
        if latest is None:
            continue
        latest["aliases"] = sorted(latest["aliases"])
        snap["manifests"][name] = latest
        versions = []
        v = 0
        while (
            record := SQLiteStorage.get_artifact_manifest(project, name, f"v{v}")
        ) is not None:
            record["aliases"] = sorted(record["aliases"])
            versions.append(record)
            v += 1
        snap["versions"][name] = versions
    for run_name, run_id in (
        ("train", "rid-train"),
        ("eval", "rid-eval"),
        ("prep", "rid-prep"),
    ):
        snap["lineage"][run_name] = SQLiteStorage.get_run_artifacts(
            project, run_name, run_id
        )
    return snap


def test_artifact_metadata_survives_parquet_roundtrip(temp_dir):
    SQLiteStorage.init_db("proj")
    SQLiteStorage.log(project="proj", run="train", metrics={"loss": 0.1})
    _build_sample_artifacts("proj")

    before = _snapshot("proj")
    assert set(before["manifests"]) == {"data", "model"}
    assert before["manifests"]["model"]["version"] == 1
    assert "best" in before["manifests"]["model"]["aliases"]
    assert len(before["lineage"]["train"]["output"]) == 2
    assert len(before["lineage"]["eval"]["input"]) == 1

    SQLiteStorage._dataset_import_attempted = True
    SQLiteStorage.export_to_parquet()

    db_path = SQLiteStorage.get_project_db_path("proj")
    for table in SQLiteStorage._ARTIFACT_PARQUET_TABLES:
        assert (Path(temp_dir) / f"{db_path.stem}_{table}.parquet").exists()

    os.unlink(db_path)
    SQLiteStorage.import_from_parquet()

    assert _snapshot("proj") == before


def test_artifact_only_project_survives_roundtrip(temp_dir):
    aid = SQLiteStorage.create_or_get_artifact("artonly", "m", "model", None)
    vid, _, _ = SQLiteStorage.insert_artifact_version(
        "artonly", aid, [{"path": "a", "digest": "d" * 64, "size": 1}], None, None, "r"
    )
    SQLiteStorage.reassign_alias("artonly", aid, "latest", vid)

    SQLiteStorage._dataset_import_attempted = True
    SQLiteStorage.export_to_parquet()

    db_path = SQLiteStorage.get_project_db_path("artonly")
    os.unlink(db_path)
    SQLiteStorage.import_from_parquet()

    assert "artonly" in SQLiteStorage.get_projects()
    record = SQLiteStorage.get_artifact_manifest("artonly", "m", None)
    assert record is not None
    assert record["version"] == 0


def test_delete_project_prevents_artifact_resurrection(temp_dir):
    import trackio

    aid = SQLiteStorage.create_or_get_artifact("doomed", "m", "model", None)
    vid, _, _ = SQLiteStorage.insert_artifact_version(
        "doomed", aid, [{"path": "a", "digest": "a" * 64, "size": 1}], None, None, "r"
    )
    SQLiteStorage.reassign_alias("doomed", aid, "latest", vid)

    SQLiteStorage._dataset_import_attempted = True
    SQLiteStorage.export_to_parquet()

    db_path = SQLiteStorage.get_project_db_path("doomed")
    assert any(p.exists() for p in SQLiteStorage._project_parquet_paths(db_path))

    assert trackio.delete_project("doomed", force=True) is True
    assert not any(p.exists() for p in SQLiteStorage._project_parquet_paths(db_path))

    SQLiteStorage.import_from_parquet()
    assert "doomed" not in SQLiteStorage.get_projects()
    assert not db_path.exists()


def test_delete_project_removes_artifact_blobs_and_media(temp_dir):
    import trackio
    from trackio import cas, utils

    SQLiteStorage.create_or_get_artifact("doomed", "m", "model", None)

    src = Path(temp_dir) / "w.bin"
    src.write_bytes(b"weights")
    cas.stage_blob_into_project(src, "doomed")

    blobs_dir = utils.project_artifacts_dir("doomed")
    assert any(p.is_file() for p in blobs_dir.rglob("*"))

    media_dir = utils.project_media_dir("doomed")
    media_dir.mkdir(parents=True, exist_ok=True)
    (media_dir / "img.png").write_bytes(b"img")

    assert trackio.delete_project("doomed", force=True) is True
    assert not blobs_dir.exists()
    assert not media_dir.exists()


def test_project_named_like_artifact_table_does_not_collide(temp_dir):
    """A project whose name ends in `_artifacts` exports its metrics as
    `<project>_artifacts.parquet`, which collides with the artifact-table
    suffix. Its metrics must still round-trip and must not be misrouted into a
    phantom `<project minus _artifacts>` project's artifacts table."""
    SQLiteStorage.init_db("model_artifacts")
    SQLiteStorage.log(project="model_artifacts", run="train", metrics={"loss": 0.1})
    aid = SQLiteStorage.create_or_get_artifact("model_artifacts", "m", "model", None)
    vid, _, _ = SQLiteStorage.insert_artifact_version(
        "model_artifacts",
        aid,
        [{"path": "w.bin", "digest": "a" * 64, "size": 5}],
        None,
        None,
        "train",
    )
    SQLiteStorage.reassign_alias("model_artifacts", aid, "latest", vid)

    SQLiteStorage._dataset_import_attempted = True
    SQLiteStorage.export_to_parquet()

    os.unlink(SQLiteStorage.get_project_db_path("model_artifacts"))
    SQLiteStorage.import_from_parquet()

    projects = SQLiteStorage.get_projects()
    assert "model_artifacts" in projects
    assert "model" not in projects
    runs = SQLiteStorage.get_run_records("model_artifacts")
    assert [r["name"] for r in runs] == ["train"]
    record = SQLiteStorage.get_artifact_manifest("model_artifacts", "m", None)
    assert record is not None
    assert record["version"] == 0


def test_validate_project_name_rejects_reserved_sidecar_suffixes():
    for suffix in (
        "_system",
        "_configs",
        "_traces",
        "_artifacts",
        "_artifact_versions",
        "_artifact_aliases",
        "_run_artifact_links",
    ):
        with pytest.raises(ValueError, match="reserved suffix"):
            SQLiteStorage.validate_project_name(f"model{suffix}")
        with pytest.raises(ValueError, match="reserved suffix"):
            SQLiteStorage.validate_project_name(f"my.model{suffix}")


def test_validate_project_name_allows_ordinary_names():
    for name in (
        "model",
        "model-v2",
        "artifacts",
        "system",
        "my.model",
        "run_artifact_links",
        "experiments",
    ):
        SQLiteStorage.validate_project_name(name)


def test_init_rejects_reserved_project_name():
    import trackio

    with pytest.raises(ValueError, match="reserved suffix"):
        trackio.init(project="model_artifacts")


def test_artifact_parquet_export_skips_unchanged_db(temp_dir):
    aid = SQLiteStorage.create_or_get_artifact("p", "m", "model", None)
    vid, _, _ = SQLiteStorage.insert_artifact_version(
        "p", aid, [{"path": "a", "digest": "a" * 64, "size": 1}], None, None, "r"
    )
    SQLiteStorage.reassign_alias("p", aid, "latest", vid)

    SQLiteStorage._dataset_import_attempted = True
    SQLiteStorage.export_to_parquet()

    pq = Path(temp_dir) / "p_artifact_versions.parquet"
    assert pq.exists()
    first_mtime = pq.stat().st_mtime_ns

    SQLiteStorage.export_to_parquet()
    assert pq.stat().st_mtime_ns == first_mtime

    SQLiteStorage.insert_artifact_version(
        "p", aid, [{"path": "a", "digest": "b" * 64, "size": 2}], None, None, "r"
    )
    SQLiteStorage.export_to_parquet()
    assert pq.stat().st_mtime_ns != first_mtime


def test_artifact_parquet_export_detects_wal_only_change(temp_dir):
    """A version write reflected only in the -wal sidecar (checkpoint-on-close
    suppressed by a concurrent reader, so the main .db mtime stays stale) must
    still trigger a re-export. Regression for the staleness check that compared
    only the .db mtime and ignored the WAL sidecar."""
    import sqlite3

    aid = SQLiteStorage.create_or_get_artifact("p", "m", "model", None)
    vid, _, _ = SQLiteStorage.insert_artifact_version(
        "p", aid, [{"path": "a", "digest": "a" * 64, "size": 1}], None, None, "r"
    )
    SQLiteStorage.reassign_alias("p", aid, "latest", vid)

    SQLiteStorage._dataset_import_attempted = True
    SQLiteStorage.export_to_parquet()

    pq = Path(temp_dir) / "p_artifact_versions.parquet"
    first_mtime = pq.stat().st_mtime_ns
    db_path = SQLiteStorage.get_project_db_path("p")

    reader = sqlite3.connect(str(db_path))
    try:
        reader.execute("BEGIN")
        reader.execute("SELECT * FROM artifact_versions").fetchall()

        SQLiteStorage.insert_artifact_version(
            "p", aid, [{"path": "a", "digest": "b" * 64, "size": 2}], None, None, "r"
        )
        assert db_path.with_name(db_path.name + "-wal").is_file()
        assert db_path.stat().st_mtime_ns <= first_mtime

        SQLiteStorage.export_to_parquet()
    finally:
        reader.close()

    assert pq.stat().st_mtime_ns != first_mtime
    assert len(SQLiteStorage._read_parquet_rows(pq)) == 2


@pytest.fixture
def dataset_loader(monkeypatch):
    from trackio import sqlite_storage as _ss

    def _setup(repo_files, import_from_parquet=None, download=None):
        monkeypatch.setenv("TRACKIO_DATASET_ID", "user/ds")
        monkeypatch.setenv("SPACE_REPO_NAME", "user/space")
        monkeypatch.delenv("TRACKIO_BUCKET_ID", raising=False)
        monkeypatch.setattr(_ss.SQLiteStorage, "_dataset_import_attempted", False)
        monkeypatch.setattr(_ss.SQLiteStorage, "_dataset_import_pending", False)
        monkeypatch.setattr(_ss.SQLiteStorage, "_dataset_remote_synced", False)
        monkeypatch.setattr(
            _ss.SQLiteStorage,
            "get_scheduler",
            staticmethod(lambda: DummyCommitScheduler()),
        )
        monkeypatch.setattr(
            _ss.SQLiteStorage,
            "import_from_parquet",
            staticmethod(import_from_parquet or (lambda: None)),
        )

        class _FakeApi:
            def list_repo_files(self, repo_id, repo_type=None):
                return repo_files

        requested = []

        def _fake_download(dataset_id, file, repo_type=None, local_dir=None):
            requested.append(file)
            dest = Path(local_dir) / file
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(b"x")
            return str(dest)

        monkeypatch.setattr(_ss.hf, "HfApi", lambda: _FakeApi())
        monkeypatch.setattr(_ss.hf, "hf_hub_download", download or _fake_download)
        return _ss, requested

    return _setup


def test_load_from_dataset_downloads_artifact_blobs(temp_dir, dataset_loader):
    artifact_blob = "artifacts/proj/blobs/sha256/aa/" + "a" * 64

    _ss, requested = dataset_loader(
        [
            "proj.parquet",
            "proj_artifact_versions.parquet",
            "media/proj/run/img.png",
            artifact_blob,
            "proj.db",
            "README.md",
        ]
    )

    _ss.SQLiteStorage.load_from_dataset()

    assert artifact_blob in requested
    assert "media/proj/run/img.png" in requested
    assert "proj.parquet" in requested
    assert "proj_artifact_versions.parquet" in requested
    assert "proj.db" not in requested
    assert "README.md" not in requested


def test_load_from_dataset_retries_import_after_transient_failure(
    temp_dir, dataset_loader
):
    """A transient import failure must not permanently block the import. The
    first call downloads and fails in import_from_parquet, leaving the gate open
    with the import still pending; the next call re-runs the import even though
    no new files download, and only then marks the dataset import attempted."""
    import_calls = []

    def _flaky_import():
        import_calls.append(1)
        if len(import_calls) == 1:
            raise RuntimeError("locked parquet")

    _ss, downloads = dataset_loader(["proj.parquet"], import_from_parquet=_flaky_import)

    _ss.SQLiteStorage.load_from_dataset()
    assert _ss.SQLiteStorage._dataset_import_attempted is False
    assert _ss.SQLiteStorage._dataset_import_pending is True

    _ss.SQLiteStorage.load_from_dataset()
    assert _ss.SQLiteStorage._dataset_import_attempted is True
    assert _ss.SQLiteStorage._dataset_import_pending is False
    assert len(import_calls) == 2
    assert downloads == ["proj.parquet"]


def test_load_from_dataset_skips_import_when_nothing_downloaded(
    temp_dir, dataset_loader
):
    """Guards the persistent-storage path: when no new files download, the
    destructive import_from_parquet must NOT run, so live DB tables are never
    replaced by a staler parquet snapshot."""
    (Path(temp_dir) / "proj.parquet").write_bytes(b"x")

    import_calls = []

    def _fail_download(*args, **kwargs):
        raise AssertionError("must not download an already-present file")

    _ss, _ = dataset_loader(
        ["proj.parquet"],
        import_from_parquet=lambda: import_calls.append(1),
        download=_fail_download,
    )

    _ss.SQLiteStorage.load_from_dataset()
    assert _ss.SQLiteStorage._dataset_import_attempted is True
    assert import_calls == []


def test_load_from_dataset_does_not_deadlock_on_reentrant_init_db(
    temp_dir, monkeypatch
):
    import threading

    from trackio import sqlite_storage as _ss

    monkeypatch.setenv("TRACKIO_DATASET_ID", "user/ds")
    monkeypatch.setenv("SPACE_REPO_NAME", "user/space")
    monkeypatch.delenv("TRACKIO_BUCKET_ID", raising=False)

    class _RealLockScheduler:
        def __init__(self):
            self.lock = threading.Lock()

    sched = _RealLockScheduler()
    monkeypatch.setattr(_ss.SQLiteStorage, "get_scheduler", staticmethod(lambda: sched))
    monkeypatch.setattr(_ss.SQLiteStorage, "_dataset_import_attempted", True)
    monkeypatch.setattr(_ss.SQLiteStorage, "_dataset_import_pending", False)
    monkeypatch.setattr(_ss.SQLiteStorage, "_dataset_remote_synced", False)

    SQLiteStorage.init_db("proj")
    SQLiteStorage.log(project="proj", run="train", metrics={"loss": 0.1})
    SQLiteStorage.export_to_parquet()

    remote = Path(temp_dir) / "_remote"
    remote.mkdir()
    moved = []
    for pq in Path(temp_dir).glob("*.parquet"):
        pq.rename(remote / pq.name)
        moved.append(pq.name)
    db_path = SQLiteStorage.get_project_db_path("proj")
    for suffix in ("", "-wal", "-shm", "-journal"):
        sidecar = db_path.with_name(db_path.name + suffix)
        if sidecar.exists():
            sidecar.unlink()

    class _FakeApi:
        def list_repo_files(self, repo_id, repo_type=None):
            return moved

    def _fake_download(dataset_id, file, repo_type=None, local_dir=None):
        dest = Path(local_dir) / file
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes((remote / file).read_bytes())
        return str(dest)

    monkeypatch.setattr(_ss.hf, "HfApi", lambda: _FakeApi())
    monkeypatch.setattr(_ss.hf, "hf_hub_download", _fake_download)
    monkeypatch.setattr(_ss.SQLiteStorage, "_dataset_import_attempted", False)
    monkeypatch.setattr(_ss.SQLiteStorage, "_dataset_import_pending", False)

    done = threading.Event()

    def _run():
        try:
            SQLiteStorage.load_from_dataset()
        finally:
            done.set()

    threading.Thread(target=_run, daemon=True).start()
    assert done.wait(timeout=10), "load_from_dataset deadlocked on re-entrant init_db"
    assert "proj" in SQLiteStorage.get_projects()


def test_artifact_parquet_tables_match_schema(temp_dir):
    """Guard against silent schema drift: _ARTIFACT_PARQUET_TABLES must list
    every column of each artifact table, in order. A column added to the
    CREATE TABLE without updating this dict would otherwise be silently
    dropped on every dataset export/import round-trip."""
    import sqlite3

    SQLiteStorage.init_db("schemacheck")
    db_path = SQLiteStorage.get_project_db_path("schemacheck")
    conn = sqlite3.connect(str(db_path))
    try:
        for table, columns in SQLiteStorage._ARTIFACT_PARQUET_TABLES.items():
            actual = [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]
            assert actual == columns, f"{table}: parquet {columns} != schema {actual}"
    finally:
        conn.close()
