import io
import logging
import sys

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
