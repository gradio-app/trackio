import logging
import sys
from unittest.mock import MagicMock

from trackio import Run
from trackio.media import get_project_media_path


def _log(run: Run, stream: str = "stdout"):
    log_dir = get_project_media_path(project=run.project, run=run.name)
    return log_dir / f"{stream}-{run.id}.log"


def test_run_captures_console_output(temp_dir, capsys):
    logger = logging.getLogger("trackio-console-test")
    handler = logging.StreamHandler(sys.stderr)
    logger.addHandler(handler)
    try:
        run = Run(url=None, project="proj", client=None, name="run1", space_id=None)
        print("loss 0.5")
        sys.stdout.writelines(["via writelines\n"])
        logger.warning("from logging")
        run.finish()
        print("after finish")
    finally:
        logger.removeHandler(handler)

    stdout_log = _log(run).read_text()
    assert "loss 0.5" in stdout_log
    assert "via writelines" in stdout_log
    assert "after finish" not in stdout_log
    assert "from logging" in _log(run, "stderr").read_text()
    assert "loss 0.5" in capsys.readouterr().out
    assert "write" not in vars(sys.stdout)


def test_console_capture_disabled_by_env(temp_dir, monkeypatch):
    monkeypatch.setenv("TRACKIO_DISABLE_CONSOLE_CAPTURE", "1")
    run = Run(url=None, project="proj", client=None, name="run1", space_id=None)
    print("not captured")
    run.finish()

    assert not _log(run).exists()


def test_new_run_takes_over_console_capture(temp_dir):
    first = Run(url=None, project="proj", client=None, name="first", space_id=None)
    second = Run(url=None, project="proj", client=None, name="second", space_id=None)
    print("to second")
    first.finish()
    print("still to second")
    second.finish()

    assert "to second" not in _log(first).read_text()
    assert "to second" in _log(second).read_text()
    assert "still to second" in _log(second).read_text()


def test_runs_with_the_same_name_keep_separate_logs(temp_dir):
    first = Run(url=None, project="proj", client=None, name="baseline", space_id=None)
    print("first attempt")
    first.finish()
    second = Run(url=None, project="proj", client=None, name="baseline", space_id=None)
    print("second attempt")
    second.finish()
    resumed = Run(
        url=None,
        project="proj",
        client=None,
        name="baseline",
        space_id=None,
        run_id=first.id,
    )
    print("first resumed")
    resumed.finish()

    assert "second attempt" not in _log(first).read_text()
    assert "first resumed" in _log(first).read_text()
    assert "first attempt" not in _log(second).read_text()


def test_finish_restores_write_patched_by_another_lib(temp_dir, monkeypatch):
    other_write = MagicMock(wraps=sys.stdout.write)
    monkeypatch.setattr(sys.stdout, "write", other_write)
    Run(url=None, project="proj", client=None, name="run1", space_id=None).finish()
    assert sys.stdout.write is other_write


def test_remote_run_uploads_console_logs(temp_dir, monkeypatch):
    uploads = []
    monkeypatch.setattr(
        Run, "_queue_upload", lambda self, path, step: uploads.append(path)
    )
    run = Run(
        url="fake_url",
        project="proj",
        client=MagicMock(),
        name="run1",
        space_id="user/space",
    )
    print("remote output")
    run.finish()

    assert uploads == [_log(run)]
