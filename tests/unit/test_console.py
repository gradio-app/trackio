import io
import logging
import sys
from pathlib import Path

import trackio
from trackio.console import REDACTED, redact_argv
from trackio.server import get_console_output
from trackio.sqlite_storage import SQLiteStorage


def _lines(text):
    return [line.split(" ", 1)[1] for line in text.splitlines()]


def test_redact_argv():
    assert redact_argv(
        ["python", "train.py", "--hub_token=hf_abc", "--api-key", "sk-1", "--lr", "1"]
    ) == [
        "python",
        "train.py",
        f"--hub_token={REDACTED}",
        "--api-key",
        REDACTED,
        "--lr",
        "1",
    ]


def test_init_captures_console_and_command(temp_dir, monkeypatch):
    monkeypatch.setattr(sys, "stdout", io.StringIO())
    monkeypatch.setattr(sys, "stderr", io.StringIO())
    monkeypatch.setattr(
        sys,
        "orig_argv",
        ["/usr/bin/python", "train.py", "--token", "secret", "--epochs", "3"],
        raising=False,
    )
    logger = logging.getLogger("trackio-test-console")
    handler = logging.StreamHandler(sys.stderr)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    try:
        run = trackio.init(
            project="console-e2e",
            name="captured",
            capture_console=True,
            auto_log_cpu=False,
            auto_log_gpu=False,
        )
        print("epoch 1 done")
        logger.info("loss=0.5")
        sys.stderr.write("\rprogress 50%")
        sys.stderr.write("\rprogress 100%\n")
        trackio.log({"loss": 0.1})
        trackio.finish()
    finally:
        logger.removeHandler(handler)

    config = SQLiteStorage.get_run_config("console-e2e", "captured")
    assert config["_Command"] == f"python train.py --token {REDACTED} --epochs 3"
    output = get_console_output("console-e2e", run_id=run.id)
    assert output["enabled"] is True
    lines = _lines(output["text"])
    assert lines[1:] == ["epoch 1 done", "loss=0.5", "progress 100%"]
    assert "write" not in vars(sys.stdout)


def test_console_capture_is_off_by_default_and_env_var_enables_it(
    temp_dir, monkeypatch
):
    monkeypatch.setattr(sys, "stdout", io.StringIO())
    monkeypatch.delenv("TRACKIO_CAPTURE_CONSOLE", raising=False)
    trackio.init(project="console-e2e", name="off", auto_log_cpu=False)
    print("not stored")
    trackio.finish()
    assert get_console_output("console-e2e", "off")["enabled"] is False

    monkeypatch.setenv("TRACKIO_CAPTURE_CONSOLE", "1")
    trackio.init(project="console-e2e", name="on", auto_log_cpu=False)
    print("stored")
    trackio.finish()
    assert "stored" in _lines(get_console_output("console-e2e", "on")["text"])


def test_console_output_is_scoped_to_run_id(temp_dir, monkeypatch):
    monkeypatch.setattr(sys, "stdout", io.StringIO())
    runs = []
    for message in ("first output", "second output"):
        run = trackio.init(
            project="console-e2e",
            name="same",
            capture_console=True,
            auto_log_cpu=False,
            auto_log_gpu=False,
        )
        print(message)
        trackio.log({"loss": 1})
        trackio.finish()
        runs.append(run)
    for index, run in enumerate(runs):
        output = get_console_output("console-e2e", run_id=run.id)
        assert (
            _lines(output["text"])[1:] == [["first output"], ["second output"]][index]
        )
    assert "first output" not in get_console_output("console-e2e", "same")["text"]
    assert (
        get_console_output("console-e2e", "same", run_id="missing")["enabled"] is False
    )


def test_console_capture_bounds_partial_utf8_lines(temp_dir, monkeypatch):
    from types import SimpleNamespace

    from trackio.console import TRUNCATION_NOTICE, ConsoleCapture

    monkeypatch.setattr("trackio.console.MAX_TOTAL_BYTES", 300)
    run = SimpleNamespace(
        project="console-e2e",
        name="bounded",
        id="bounded",
        _upload_console_file=lambda path: None,
    )
    capture = ConsoleCapture(run)
    capture._record("prefix ")
    capture.flush()
    capture._record("😀" * 1000)
    capture.flush()
    capture.stop()
    files = list((Path(temp_dir) / "media").rglob("console-*.log"))
    text = "".join(path.read_text() for path in files)
    assert sum(path.stat().st_size for path in files) <= 300
    assert "prefix " in text
    assert TRUNCATION_NOTICE in text
    assert "�" not in text
    capture._record("ignored\n")
    assert "ignored" not in "".join(capture._lines)


def test_console_stop_preserves_partial_after_rollover(temp_dir, monkeypatch):
    from types import SimpleNamespace

    from trackio.console import ConsoleCapture

    monkeypatch.setattr("trackio.console.MAX_CHUNK_BYTES", 100)
    run = SimpleNamespace(
        project="console-e2e",
        name="rollover",
        id="rollover",
        _upload_console_file=lambda path: None,
    )
    capture = ConsoleCapture(run)
    capture._record("x" * 100 + "\nfinal partial line")
    capture.flush()
    capture.stop()
    files = sorted((Path(temp_dir) / "media").rglob("console-*.log"))
    assert _lines("".join(path.read_text() for path in files)) == [
        "x" * 100,
        "final partial line",
    ]
