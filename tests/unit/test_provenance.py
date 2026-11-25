import importlib
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import trackio
from trackio import cli, provenance
from trackio.sqlite_storage import SQLiteStorage


@pytest.fixture(autouse=True)
def no_ambient_job(monkeypatch):
    for name in ("HF_JOB_ID", "HF_JOB_OWNER", "HF_JOB_FLAVOR", "HF_JOB_IMAGE"):
        monkeypatch.delenv(name, raising=False)


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

    same = provenance.verify_project_code("prov", configs, files=[script])
    assert same[0]["ok"] and same[0]["matches_local"]

    edited = tmp_path / "edited" / "train.py"
    edited.parent.mkdir()
    edited.write_text("print('training, but different')\n")
    differs = provenance.verify_project_code("prov", configs, files=[edited])
    assert not differs[0]["ok"] and not differs[0]["matches_local"]
    assert differs[0]["problems"] == [
        "train.py: recorded hash differs from the local file"
    ]


@pytest.fixture
def helper_module(tmp_path, monkeypatch):
    helper = tmp_path / "helper_model.py"
    helper.write_text("WIDTH = 4\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.delitem(sys.modules, "helper_model", raising=False)
    importlib.import_module("helper_model")
    yield helper
    sys.modules.pop("helper_model", None)


def test_init_records_local_modules(temp_dir, script, helper_module, monkeypatch):
    monkeypatch.delenv("HF_JOB_ID", raising=False)
    _make_run("prov", "run-mod")

    code = _logged_config("prov", "run-mod")["_Code"]
    assert code["files"] == {"helper_model.py": provenance.sha256_file(helper_module)}

    configs = {"run-mod": _logged_config("prov", "run-mod")}
    rows = provenance.verify_project_code(
        "prov", configs, files=[script, helper_module]
    )
    assert rows[0]["ok"] and rows[0]["matches_local"]


def test_local_modules_skip_relative_and_missing_files(script, monkeypatch):
    monkeypatch.setitem(sys.modules, "rel_mod", SimpleNamespace(__file__="_ops.py"))
    gone = script.parent / "gone.py"
    monkeypatch.setitem(sys.modules, "gone_mod", SimpleNamespace(__file__=str(gone)))

    assert provenance.local_modules(script) == {}
    assert provenance.code_provenance(script)["sha256"] == provenance.sha256_file(
        script
    )


def _fake_job(monkeypatch, executed: dict[str, str], stage: str = "COMPLETED"):
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
        for remote, local in files:
            downloads.append((bucket_id, remote))
            name = remote.rsplit("/", 1)[-1]
            if name in executed:
                Path(local).write_text(executed[name])

    monkeypatch.setattr(provenance.huggingface_hub, "download_bucket_files", download)
    return downloads


def test_verify_against_executed_job_files(
    temp_dir, script, helper_module, monkeypatch
):
    monkeypatch.setenv("HF_JOB_ID", "abc123")
    monkeypatch.setenv("HF_JOB_OWNER", "someone")
    _make_run("prov", "run-job")
    configs = {"run-job": _logged_config("prov", "run-job")}
    sources = {"train.py": script.read_text(), "helper_model.py": "WIDTH = 4\n"}

    downloads = _fake_job(monkeypatch, sources)
    rows = provenance.verify_project_code("prov", configs)
    assert rows[0]["ok"] and rows[0]["matches_executed"]
    assert sorted(downloads) == [
        ("someone/jobs-artifacts", "20260101-abc/helper_model.py"),
        ("someone/jobs-artifacts", "20260101-abc/train.py"),
    ]

    _fake_job(monkeypatch, {**sources, "helper_model.py": "WIDTH = 8\n"})
    rows = provenance.verify_project_code("prov", configs)
    assert not rows[0]["ok"]
    assert rows[0]["problems"] == ["helper_model.py: the job ran different code"]

    _fake_job(monkeypatch, sources, stage="ERROR")
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
