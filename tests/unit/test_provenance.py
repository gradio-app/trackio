from pathlib import Path
from types import SimpleNamespace

import pytest

import trackio
from trackio import cli, provenance
from trackio.sqlite_storage import SQLiteStorage


@pytest.fixture
def script(tmp_path, monkeypatch):
    path = tmp_path / "train.py"
    path.write_text("print('training')\n")
    monkeypatch.setattr(provenance, "entry_script", lambda: path)
    return path


def _logged_config(project, run):
    return SQLiteStorage.get_run_config(project, run)


def _make_run(project, run):
    trackio.init(project=project, name=run, config={"lr": 0.1})
    trackio.log({"loss": 1.0})
    trackio.finish()


def test_init_records_code_and_environment(temp_dir, script, monkeypatch):
    monkeypatch.delenv("HF_JOB_ID", raising=False)
    _make_run("prov", "run-a")

    config = _logged_config("prov", "run-a")
    assert config["_Code"]["path"] == "train.py"
    assert config["_Code"]["sha256"] == provenance.sha256_file(script)
    assert config["_Environment"]["python"]
    assert "trackio" in config["_Environment"]["packages"]
    assert "_Job" not in config


def test_init_records_hf_job(temp_dir, script, monkeypatch):
    monkeypatch.setenv("HF_JOB_ID", "abc123")
    monkeypatch.setenv("HF_JOB_OWNER", "someone")
    monkeypatch.setenv("HF_JOB_FLAVOR", "a10g-small")
    _make_run("prov", "run-job")

    job = _logged_config("prov", "run-job")["_Job"]
    assert job == {
        "id": "abc123",
        "owner": "someone",
        "flavor": "a10g-small",
        "url": "https://huggingface.co/jobs/someone/abc123",
    }


def test_provenance_can_be_disabled(temp_dir, script, monkeypatch):
    monkeypatch.setenv("TRACKIO_RECORD_PROVENANCE", "0")
    _make_run("prov", "run-off")

    config = _logged_config("prov", "run-off")
    assert "_Code" not in config and "_Environment" not in config


def test_verify_against_local_file(temp_dir, script, tmp_path, monkeypatch):
    monkeypatch.delenv("HF_JOB_ID", raising=False)
    _make_run("prov", "run-a")
    configs = {"run-a": _logged_config("prov", "run-a")}

    same = provenance.verify_project_code("prov", configs, file=script)
    assert same[0]["ok"] and same[0]["matches_local"]

    edited = tmp_path / "edited.py"
    edited.write_text("print('training, but different')\n")
    differs = provenance.verify_project_code("prov", configs, file=edited)
    assert not differs[0]["ok"] and not differs[0]["matches_local"]


def _fake_job(monkeypatch, executed_source: str, stage: str = "COMPLETED"):
    volume = SimpleNamespace(
        mount_path="/data", source="someone/jobs-artifacts", path="20260101-abc"
    )
    monkeypatch.setattr(
        provenance.huggingface_hub,
        "inspect_job",
        lambda job_id, namespace=None, token=None: SimpleNamespace(
            status=SimpleNamespace(stage=stage), volumes=[volume]
        ),
    )
    downloads = []

    def download(bucket_id, files, raise_on_missing_files=False, token=None):
        downloads.append((bucket_id, files[0][0]))
        Path(files[0][1]).write_text(executed_source)

    monkeypatch.setattr(provenance.huggingface_hub, "download_bucket_files", download)
    return downloads


def test_verify_against_executed_job_script(temp_dir, script, monkeypatch):
    monkeypatch.setenv("HF_JOB_ID", "abc123")
    monkeypatch.setenv("HF_JOB_OWNER", "someone")
    _make_run("prov", "run-job")
    configs = {"run-job": _logged_config("prov", "run-job")}

    downloads = _fake_job(monkeypatch, script.read_text())
    rows = provenance.verify_project_code("prov", configs)
    assert rows[0]["ok"] and rows[0]["matches_executed"]
    assert downloads == [("someone/jobs-artifacts", "20260101-abc/train.py")]

    _fake_job(monkeypatch, "print('swapped')\n")
    rows = provenance.verify_project_code("prov", configs)
    assert not rows[0]["ok"] and not rows[0]["matches_executed"]

    _fake_job(monkeypatch, script.read_text(), stage="ERROR")
    rows = provenance.verify_project_code("prov", configs)
    assert not rows[0]["ok"] and "job status is ERROR" in rows[0]["problems"]


def test_cli_verify_exit_codes(temp_dir, script, tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("HF_JOB_ID", raising=False)
    _make_run("prov", "run-a")

    monkeypatch.setattr(
        "sys.argv",
        ["trackio", "verify", "--project", "prov", "--file", str(script)],
    )
    cli.main()
    assert "OK" in capsys.readouterr().out

    other = tmp_path / "other.py"
    other.write_text("pass\n")
    monkeypatch.setattr(
        "sys.argv",
        ["trackio", "verify", "--project", "prov", "--file", str(other)],
    )
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 1
