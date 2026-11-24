import subprocess
import sys
import textwrap
import time

import pytest

import trackio
from trackio import run as run_module
from trackio.run import Run

INIT_AND_LOG = """
    trackio.init(project="demo", name="run")
    trackio.log({"loss": 1.0})
"""

EXIT_SCRIPTS = {
    "main_thread": INIT_AND_LOG,
    "asyncio_run": """
    import asyncio

    async def main():
        trackio.init(project="demo", name="run")
        trackio.log({"loss": 1.0})

    asyncio.run(main())
    """,
    "worker_thread": """
    import threading

    def work():
        trackio.init(project="demo", name="run")
        trackio.log({"loss": 1.0})

    thread = threading.Thread(target=work)
    thread.start()
    thread.join()
    """,
}


@pytest.mark.parametrize("context", sorted(EXIT_SCRIPTS))
def test_logs_are_flushed_at_exit_without_finish(tmp_path, monkeypatch, context):
    monkeypatch.setenv("TRACKIO_DIR", str(tmp_path))
    script = "import trackio\n" + textwrap.dedent(EXIT_SCRIPTS[context])
    subprocess.run([sys.executable, "-c", script], check=True, capture_output=True)

    count = subprocess.run(
        [
            sys.executable,
            "-c",
            "from trackio.sqlite_storage import SQLiteStorage;"
            "print(len(SQLiteStorage.get_logs('demo', 'run')))",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert count.stdout.strip() == "1"


def test_exit_hook_finishes_each_unfinished_run_once(temp_dir, monkeypatch):
    monkeypatch.setattr(trackio, "_active_runs", [])
    finished = []
    first = trackio.init(project="demo", name="first")
    monkeypatch.setattr(first, "finish", lambda: finished.append("first"))
    trackio.context_vars.current_run.set(None)
    second = trackio.init(project="demo", name="second")
    real_finish = second.finish
    real_finish()
    monkeypatch.setattr(second, "finish", lambda: finished.append("second"))

    trackio._cleanup_current_run()
    trackio._cleanup_current_run()

    assert finished == ["first"]
    first._stop_flag.set()


class _DownClient:
    def __init__(self):
        self.calls = 0

    def predict(self, *args, **kwargs):
        self.calls += 1
        raise ConnectionError("server unreachable")


def test_remote_sender_does_not_spin_after_stop_and_exits_when_abandoned(
    temp_dir, monkeypatch
):
    monkeypatch.setattr(run_module, "BATCH_SEND_INTERVAL", 0.05)
    client = _DownClient()
    run = Run(
        url="user/space",
        project="demo",
        client=client,
        name="run",
        space_id="user/space",
    )
    run.log({"loss": 1.0})
    deadline = time.time() + 5
    while client.calls == 0 and time.time() < deadline:
        time.sleep(0.01)
    assert client.calls > 0

    run._stop_flag.set()
    before = client.calls
    time.sleep(0.5)
    assert run._client_thread.is_alive()
    assert 0 < client.calls - before <= 30

    run._sender_abandoned.set()
    run._client_thread.join(timeout=5)
    assert not run._client_thread.is_alive()
