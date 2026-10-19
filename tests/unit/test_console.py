import io
import logging
import sys
from types import SimpleNamespace

import trackio
from trackio import console
from trackio.console import (
    REDACTED,
    TRUNCATION_NOTICE,
    ConsoleCapture,
    get_launch_command,
    read_console_output,
    redact_argv,
    resolve_capture_console,
)
from trackio.run import Run
from trackio.server import get_console_output
from trackio.sqlite_storage import SQLiteStorage


class FakeRun:
    def __init__(self, project="console-project", name="console-run"):
        self.project = project
        self.name = name
        self.uploaded = []

    def _upload_console_file(self, path):
        self.uploaded.append(path)

    def _warn_once(self, key, message):
        pass


def _lines(text):
    return [line.split(" ", 1)[1] for line in text.splitlines()]


def use_fake_streams(monkeypatch):
    stdout, stderr = io.StringIO(), io.StringIO()
    monkeypatch.setattr(sys, "stdout", stdout)
    monkeypatch.setattr(sys, "stderr", stderr)
    return stdout, stderr


def test_resolve_capture_console(monkeypatch):
    monkeypatch.delenv("TRACKIO_CAPTURE_CONSOLE", raising=False)
    assert resolve_capture_console(None) is False
    assert resolve_capture_console(True) is True
    monkeypatch.setenv("TRACKIO_CAPTURE_CONSOLE", "1")
    assert resolve_capture_console(None) is True
    assert resolve_capture_console(False) is False
    monkeypatch.setenv("TRACKIO_CAPTURE_CONSOLE", "false")
    assert resolve_capture_console(None) is False


def test_redact_argv():
    assert redact_argv(
        [
            "python",
            "train.py",
            "--hub_token=hf_abc",
            "--api-key",
            "sk-123",
            "wandb.api_key=xyz",
            "--lr",
            "1e-3",
        ]
    ) == [
        "python",
        "train.py",
        f"--hub_token={REDACTED}",
        "--api-key",
        REDACTED,
        f"wandb.api_key={REDACTED}",
        "--lr",
        "1e-3",
    ]


def test_get_launch_command(monkeypatch):
    monkeypatch.setattr(
        sys,
        "orig_argv",
        ["/venv/bin/python3", "-m", "lerobot.train", "--steps", "100", "--name=a b"],
        raising=False,
    )
    assert get_launch_command() == "python3 -m lerobot.train --steps 100 '--name=a b'"

    monkeypatch.setattr(
        sys,
        "orig_argv",
        ["/venv/bin/python", "-m", "ipykernel_launcher", "-f", "kernel.json"],
        raising=False,
    )
    assert get_launch_command() is None


def test_capture_includes_logging_handlers_created_before_start(temp_dir, monkeypatch):
    stdout, stderr = use_fake_streams(monkeypatch)
    logger = logging.getLogger("trackio-test-console")
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    run = FakeRun()
    capture = ConsoleCapture(run, interval=60)
    try:
        capture.start()
        print("hello from print")
        logger.info("step 1 loss=0.5")
    finally:
        capture.stop()
        logger.removeHandler(handler)

    print("after stop")
    assert stdout.getvalue() == "hello from print\nafter stop\n"
    assert stderr.getvalue() == "INFO step 1 loss=0.5\n"
    assert "write" not in vars(stdout)
    output = read_console_output(run.project, run.name)
    assert output["enabled"] is True
    assert _lines(output["text"]) == ["hello from print", "INFO step 1 loss=0.5"]
    assert run.uploaded and run.uploaded[-1].name.startswith("console-")


def test_carriage_returns_keep_latest_progress_and_ansi_is_stripped(
    temp_dir, monkeypatch
):
    use_fake_streams(monkeypatch)
    run = FakeRun()
    capture = ConsoleCapture(run, interval=60)
    capture.start()
    try:
        sys.stderr.write("\r 10%|#")
        sys.stderr.write("\r 50%|#####")
        capture.flush()
        partial = read_console_output(run.project, run.name)["text"]
        sys.stderr.write("\r100%|##########\n")
        sys.stdout.write("\x1b[32mgreen\x1b[0m\r\n")
    finally:
        capture.stop()

    assert _lines(partial) == [" 50%|#####"]
    text = read_console_output(run.project, run.name)["text"]
    assert _lines(text) == ["100%|##########", "green"]


def test_chunks_rotate_and_total_size_is_capped(temp_dir, monkeypatch):
    use_fake_streams(monkeypatch)
    monkeypatch.setattr(console, "MAX_CHUNK_BYTES", 100)
    monkeypatch.setattr(console, "MAX_TOTAL_BYTES", 400)
    run = FakeRun()
    capture = ConsoleCapture(run, interval=60)
    capture.start()
    try:
        for i in range(20):
            print(f"line {i:02d} " + "x" * 20)
            capture.flush()
    finally:
        capture.stop()

    files = {path.name for path in run.uploaded}
    assert len(files) > 1
    text = read_console_output(run.project, run.name)["text"]
    lines = _lines(text)
    assert lines[0].startswith("line 00")
    assert lines[-1] == TRUNCATION_NOTICE
    assert len(lines) == len(set(lines))


def test_read_console_output_tail_and_missing(temp_dir, monkeypatch):
    use_fake_streams(monkeypatch)
    assert read_console_output("console-project", "no-such-run")["enabled"] is False
    assert read_console_output("console-project", "../..")["enabled"] is False

    run = FakeRun()
    capture = ConsoleCapture(run, interval=60)
    capture.start()
    try:
        for i in range(100):
            print(f"line {i}")
    finally:
        capture.stop()

    output = read_console_output(run.project, run.name, max_chars=200)
    assert output["truncated"] is True
    assert len(output["text"]) <= 200
    assert _lines(output["text"])[-1] == "line 99"
    assert output["text"].split(" ", 1)[0].endswith("Z")


def test_init_captures_console_and_command(temp_dir, monkeypatch):
    use_fake_streams(monkeypatch)
    monkeypatch.setattr(
        sys,
        "orig_argv",
        ["/usr/bin/python", "train.py", "--token", "secret", "--epochs", "3"],
        raising=False,
    )
    run = trackio.init(
        project="console-e2e",
        name="captured",
        capture_console=True,
        auto_log_cpu=False,
        auto_log_gpu=False,
    )
    print("epoch 1 done")
    trackio.log({"loss": 0.1})
    trackio.finish()

    config = SQLiteStorage.get_run_config("console-e2e", "captured")
    assert config["_Command"] == f"python train.py --token {REDACTED} --epochs 3"
    output = get_console_output("console-e2e", run_id=run.id)
    assert output["enabled"] is True
    assert "epoch 1 done" in _lines(output["text"])


def test_console_capture_is_off_by_default(temp_dir, monkeypatch):
    use_fake_streams(monkeypatch)
    monkeypatch.delenv("TRACKIO_CAPTURE_CONSOLE", raising=False)
    trackio.init(
        project="console-e2e",
        name="not-captured",
        auto_log_cpu=False,
        auto_log_gpu=False,
    )
    print("not stored")
    trackio.log({"loss": 0.1})
    trackio.finish()

    assert get_console_output("console-e2e", "not-captured") == {
        "enabled": False,
        "text": "",
        "truncated": False,
    }


def test_remote_run_uploads_console_files():
    queued = []
    run = SimpleNamespace(
        _is_local=False, _queue_upload=lambda *a, **k: queued.append((a, k))
    )
    Run._upload_console_file(run, "console-x.log")
    assert queued == [(("console-x.log",), {"step": None})]
