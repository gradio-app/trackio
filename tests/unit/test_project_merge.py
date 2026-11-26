import shutil
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import orjson
import pytest

import trackio
from trackio import cli, provenance
from trackio.project_merge import (
    MergeConflictError,
    merge_project,
    merge_project_dirs,
)
from trackio.sqlite_storage import SQLiteStorage

PROJECT = "memorization-capacity"


@pytest.fixture(autouse=True)
def job_env(monkeypatch, tmp_path):
    for name in ("HF_JOB_ID", "HF_JOB_OWNER", "HF_JOB_FLAVOR", "HF_JOB_IMAGE"):
        monkeypatch.delenv(name, raising=False)
    script = tmp_path / "train.py"
    script.write_text("print('training')\n")
    monkeypatch.setattr(provenance, "entry_script", lambda: script)
    monkeypatch.chdir(tmp_path)
    return script


def _log_runs(runs, job_id=None, monkeypatch=None, image=False, artifact=None):
    if job_id is not None:
        monkeypatch.setenv("HF_JOB_ID", job_id)
        monkeypatch.setenv("HF_JOB_OWNER", "someone")
    for name, losses in runs:
        trackio.init(project=PROJECT, name=name, config={"width": len(losses)})
        for loss in losses:
            payload = {"loss": loss}
            if image:
                payload["sample"] = trackio.Image(
                    np.zeros((4, 4, 3), dtype=np.uint8), caption=name
                )
            trackio.log(payload)
        if artifact is not None:
            art = trackio.Artifact(name="model", type="model")
            art.add_file(artifact)
            trackio.log_artifact(art, aliases=["best"])
        trackio.finish()
    if job_id is not None:
        monkeypatch.delenv("HF_JOB_ID")
        monkeypatch.delenv("HF_JOB_OWNER")


def _move_project(temp_dir, dest: Path) -> Path:
    """Move the project out of TRACKIO_DIR, as one job's bucket would hold it."""
    root = Path(temp_dir)
    dest.mkdir(parents=True)
    db_name = SQLiteStorage.get_project_db_filename(PROJECT)
    for suffix in ("", "-wal", "-shm"):
        path = root / f"{db_name}{suffix}"
        if path.exists():
            shutil.move(path, dest / path.name)
    for kind in ("media", "artifacts"):
        path = root / kind / PROJECT
        if path.exists():
            (dest / kind).mkdir()
            shutil.move(path, dest / kind / PROJECT)
    return dest


def _job(temp_dir, tmp_path, label, runs, **kwargs):
    _log_runs(runs, **kwargs)
    return _move_project(temp_dir, tmp_path / "jobs" / label)


def _row_counts():
    with sqlite3.connect(SQLiteStorage.get_project_db_path(PROJECT)) as conn:
        return {
            table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("metrics", "configs", "system_metrics")
        }


def _losses(run):
    return [
        row["loss"]
        for row in SQLiteStorage.get_logs(PROJECT, run)
        if row.get("loss") is not None
    ]


def test_merge_combines_parallel_jobs_and_keeps_provenance(
    temp_dir, tmp_path, monkeypatch, job_env
):
    a = _job(
        temp_dir,
        tmp_path,
        "1x32",
        [("w32-s0", [3.0, 2.0]), ("w32-s1", [3.5])],
        job_id="job-a",
        monkeypatch=monkeypatch,
    )
    b = _job(
        temp_dir,
        tmp_path,
        "1x64",
        [("w64-s0", [1.0, 0.5, 0.25])],
        job_id="job-b",
        monkeypatch=monkeypatch,
    )
    assert SQLiteStorage.get_runs(PROJECT) == []

    result = merge_project_dirs(PROJECT, [a, b])

    assert sorted(SQLiteStorage.get_runs(PROJECT)) == ["w32-s0", "w32-s1", "w64-s0"]
    assert _losses("w32-s0") == [3.0, 2.0]
    assert _losses("w64-s0") == [1.0, 0.5, 0.25]
    assert result["rows_added"]["metrics"] == 6
    assert result["rows_added"]["configs"] == 3
    assert [r["status"] for s in result["sources"] for r in s["runs"]] == ["new"] * 3

    configs = {
        record["name"]: SQLiteStorage.get_run_config(PROJECT, record["name"])
        for record in SQLiteStorage.get_run_records(PROJECT)
    }
    assert configs["w32-s0"]["_Job"]["id"] == "job-a"
    assert configs["w64-s0"]["_Job"]["id"] == "job-b"
    assert configs["w64-s0"]["width"] == 3
    rows = provenance.verify_project_code(
        PROJECT, configs, files=[job_env], check_jobs=False
    )
    assert all(row["ok"] and row["matches_local"] for row in rows)


def test_merge_is_idempotent(temp_dir, tmp_path):
    a = _job(temp_dir, tmp_path, "a", [("run-a", [1.0, 2.0])])
    b = _job(temp_dir, tmp_path, "b", [("run-b", [3.0])])
    merge_project_dirs(PROJECT, [a, b])
    before = _row_counts()

    again = merge_project_dirs(PROJECT, [a, b, a])

    assert _row_counts() == before
    assert set(again["rows_added"].values()) == {0}
    assert {r["status"] for s in again["sources"] for r in s["runs"]} == {"existing"}


def test_merge_adds_only_missing_rows_of_existing_run(temp_dir, tmp_path):
    a = _job(temp_dir, tmp_path, "a", [("run-a", [1.0, 2.0])])
    merge_project_dirs(PROJECT, [a])
    db = a / SQLiteStorage.get_project_db_filename(PROJECT)
    with sqlite3.connect(db) as conn:
        run_id, run_name = conn.execute(
            "SELECT run_id, run_name FROM metrics LIMIT 1"
        ).fetchone()
        conn.execute(
            "INSERT INTO metrics (run_id, timestamp, run_name, step, metrics, log_id) "
            "VALUES (?, '2099-01-01T00:00:00', ?, 2, ?, 'late-log-id')",
            (run_id, run_name, orjson.dumps({"loss": 0.5})),
        )

    result = merge_project_dirs(PROJECT, [a])

    assert result["rows_added"]["metrics"] == 1
    assert _losses("run-a") == [1.0, 2.0, 0.5]


def test_name_collision_is_refused_without_writing(temp_dir, tmp_path):
    a = _job(temp_dir, tmp_path, "a", [("baseline", [1.0]), ("only-a", [1.0])])
    b = _job(temp_dir, tmp_path, "b", [("baseline", [2.0])])

    with pytest.raises(MergeConflictError, match="'baseline'"):
        merge_project_dirs(PROJECT, [a, b])

    assert SQLiteStorage.get_runs(PROJECT) == []


def test_collision_with_existing_local_run_is_refused(temp_dir, tmp_path):
    a = _job(temp_dir, tmp_path, "a", [("baseline", [1.0])])
    _log_runs([("baseline", [9.0])])

    with pytest.raises(MergeConflictError):
        merge_project_dirs(PROJECT, [a])

    assert _losses("baseline") == [9.0]


def test_name_collision_suffix(temp_dir, tmp_path):
    a = _job(temp_dir, tmp_path, "a", [("baseline", [1.0])])
    b = _job(temp_dir, tmp_path, "b", [("baseline", [2.0]), ("baseline-2", [3.0])])

    result = merge_project_dirs(PROJECT, [a, b], on_conflict="suffix")

    assert sorted(SQLiteStorage.get_runs(PROJECT)) == [
        "baseline",
        "baseline-2",
        "baseline-3",
    ]
    assert _losses("baseline") == [1.0]
    assert _losses("baseline-3") == [2.0]
    assert _losses("baseline-2") == [3.0]
    renamed = [r for r in result["sources"][1]["runs"] if r["name"] != r["source_name"]]
    assert [(r["source_name"], r["name"]) for r in renamed] == [
        ("baseline", "baseline-3")
    ]

    merge_project_dirs(PROJECT, [a, b], on_conflict="suffix")
    assert len(SQLiteStorage.get_runs(PROJECT)) == 3


def test_suffix_moves_media_and_rewrites_paths(temp_dir, tmp_path):
    a = _job(temp_dir, tmp_path, "a", [("baseline", [1.0])], image=True)
    b = _job(temp_dir, tmp_path, "b", [("baseline", [2.0])], image=True)

    merge_project_dirs(PROJECT, [a, b], on_conflict="suffix")

    for run in ("baseline", "baseline-2"):
        (sample,) = [row["sample"] for row in SQLiteStorage.get_logs(PROJECT, run)]
        assert sample["file_path"].startswith(f"{PROJECT}/{run}/")
        assert (Path(temp_dir) / "media" / sample["file_path"]).is_file()


def test_merge_replays_artifacts(temp_dir, tmp_path):
    weights_a = tmp_path / "a.bin"
    weights_a.write_bytes(b"weights from job a")
    weights_b = tmp_path / "b.bin"
    weights_b.write_bytes(b"weights from job b")
    a = _job(temp_dir, tmp_path, "a", [("run-a", [1.0])], artifact=weights_a)
    b = _job(temp_dir, tmp_path, "b", [("run-b", [1.0])], artifact=weights_b)

    result = merge_project_dirs(PROJECT, [a, b])
    assert result["artifact_versions_added"] == 2
    assert merge_project_dirs(PROJECT, [a, b])["artifact_versions_added"] == 0

    latest = SQLiteStorage.resolve_artifact_version(PROJECT, "model", "latest")
    assert latest["version"] == 1
    trackio.init(project=PROJECT, name="consumer")
    v0 = Path(trackio.use_artifact("model:v0").download(tmp_path / "v0"))
    v1 = Path(trackio.use_artifact("model:latest").download(tmp_path / "v1"))
    trackio.finish()
    assert (v0 / "a.bin").read_bytes() == b"weights from job a"
    assert (v1 / "b.bin").read_bytes() == b"weights from job b"


def test_invalid_on_conflict(temp_dir, tmp_path):
    a = _job(temp_dir, tmp_path, "a", [("run-a", [1.0])])
    with pytest.raises(ValueError, match="on_conflict"):
        merge_project_dirs(PROJECT, [a], on_conflict="overwrite")


def test_missing_source_db(temp_dir, tmp_path):
    with pytest.raises(FileNotFoundError):
        merge_project_dirs(PROJECT, [tmp_path / "empty"])


@pytest.fixture
def fake_buckets(monkeypatch, tmp_path):
    """Serve `tmp_path/buckets/<id>/trackio/...` through the bucket API."""
    root = tmp_path / "buckets"

    def bucket_dir(bucket_id):
        return root / bucket_id.replace("/", "__")

    def list_bucket_tree(bucket_id, prefix=None, recursive=True, token=None):
        base = bucket_dir(bucket_id)
        for path in sorted(base.rglob("*")):
            rel = path.relative_to(base).as_posix()
            if path.is_file() and rel.startswith(prefix or ""):
                yield SimpleNamespace(type="file", path=rel)

    def download_bucket_files(bucket_id, files, token=None, **kwargs):
        for remote, local in files:
            source = bucket_dir(bucket_id) / remote
            if source.is_file():
                shutil.copy2(source, local)

    monkeypatch.setattr(
        "trackio.bucket_storage.huggingface_hub.list_bucket_tree", list_bucket_tree
    )
    monkeypatch.setattr(
        "trackio.bucket_storage.huggingface_hub.download_bucket_files",
        download_bucket_files,
    )

    def upload(bucket_id, job_dir):
        shutil.copytree(job_dir, bucket_dir(bucket_id) / "trackio")
        shutil.rmtree(job_dir)

    return upload


def test_merge_from_buckets(temp_dir, tmp_path, fake_buckets):
    fake_buckets(
        "me/data-1x32",
        _job(temp_dir, tmp_path, "a", [("w32", [1.0])], image=True),
    )
    fake_buckets("me/data-1x64", _job(temp_dir, tmp_path, "b", [("w64", [2.0])]))

    result = merge_project(PROJECT, buckets=["me/data-1x32", "me/data-1x64"])

    assert [s["source"] for s in result["sources"]] == [
        "hf://buckets/me/data-1x32",
        "hf://buckets/me/data-1x64",
    ]
    assert sorted(SQLiteStorage.get_runs(PROJECT)) == ["w32", "w64"]
    (sample,) = [row["sample"] for row in SQLiteStorage.get_logs(PROJECT, "w32")]
    assert (Path(temp_dir) / "media" / sample["file_path"]).is_file()


def test_merge_from_bucket_without_project(temp_dir, tmp_path, fake_buckets):
    (tmp_path / "buckets" / "me__empty").mkdir(parents=True)
    with pytest.raises(FileNotFoundError, match="me/empty"):
        merge_project(PROJECT, buckets=["me/empty"])


def test_cli_merge(temp_dir, tmp_path, fake_buckets, monkeypatch, capsys):
    fake_buckets("me/data-a", _job(temp_dir, tmp_path, "a", [("baseline", [1.0])]))
    local = _job(temp_dir, tmp_path, "b", [("baseline", [2.0])])
    argv = [
        "trackio",
        "merge",
        "--project",
        PROJECT,
        "--bucket",
        "me/data-a",
        "--source",
        str(local),
    ]

    monkeypatch.setattr("sys.argv", argv)
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 1
    assert "--on-conflict suffix" in capsys.readouterr().err

    monkeypatch.setattr("sys.argv", argv + ["--on-conflict", "suffix"])
    cli.main()
    out = capsys.readouterr().out
    assert "baseline-2 (renamed from 'baseline')" in out
    assert sorted(SQLiteStorage.get_runs(PROJECT)) == ["baseline", "baseline-2"]
