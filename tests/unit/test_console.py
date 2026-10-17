import logging
import sys
from unittest.mock import MagicMock

from trackio import Run
from trackio.media import get_project_media_path


def test_run_captures_console_output(temp_dir, capsys):
    logger = logging.getLogger("trackio-console-test")
    handler = logging.StreamHandler(sys.stderr)
    logger.addHandler(handler)
    try:
        run = Run(url=None, project="proj", client=None, name="run1", space_id=None)
        print("loss 0.5")
        logger.warning("from logging")
        run.finish()
        print("after finish")
    finally:
        logger.removeHandler(handler)

    log_dir = get_project_media_path(project="proj", run="run1")
    stdout_log = (log_dir / "stdout.log").read_text()
    assert "loss 0.5" in stdout_log
    assert "after finish" not in stdout_log
    assert "from logging" in (log_dir / "stderr.log").read_text()
    assert "loss 0.5" in capsys.readouterr().out
    assert "write" not in vars(sys.stdout)


def test_console_capture_disabled_by_env(temp_dir, monkeypatch):
    monkeypatch.setenv("TRACKIO_DISABLE_CONSOLE_CAPTURE", "1")
    run = Run(url=None, project="proj", client=None, name="run1", space_id=None)
    print("not captured")
    run.finish()

    log_dir = get_project_media_path(project="proj", run="run1")
    assert not (log_dir / "stdout.log").exists()


def test_new_run_takes_over_console_capture(temp_dir):
    first = Run(url=None, project="proj", client=None, name="first", space_id=None)
    second = Run(url=None, project="proj", client=None, name="second", space_id=None)
    print("to second")
    first.finish()
    print("still to second")
    second.finish()

    first_log = get_project_media_path(project="proj", run="first") / "stdout.log"
    second_log = get_project_media_path(project="proj", run="second") / "stdout.log"
    assert "to second" not in first_log.read_text()
    assert "to second" in second_log.read_text()
    assert "still to second" in second_log.read_text()


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

    log_dir = get_project_media_path(project="proj", run="run1")
    assert uploads == [log_dir / "stdout.log"]
