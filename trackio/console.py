import sys
import threading
from pathlib import Path

STREAM_NAMES = (
    "stdout",
    "stderr",
)


def log_paths(log_dir: Path) -> tuple[Path, ...]:
    return tuple(log_dir / f"{name}.log" for name in STREAM_NAMES)


class ConsoleCapture:
    """
    Process-wide capture of console output into per-run `stdout.log` and
    `stderr.log` files. The `write` method of the current `sys.stdout` and
    `sys.stderr` objects is patched in place rather than replacing the streams,
    so handlers created before capture started (e.g. `logging.basicConfig()`)
    are captured too. Only one run captures at a time: attaching a new run
    redirects output to its files, and detaching only takes effect for the run
    that is currently attached.
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._logs: dict = {}
        self._paths: tuple[Path, ...] | None = None
        self._patched: dict = {}

    def attach(self, log_dir: Path) -> tuple[Path, ...]:
        paths = log_paths(log_dir)
        logs = {
            name: path.open("a", encoding="utf-8", errors="replace", buffering=1)
            for name, path in zip(STREAM_NAMES, paths)
        }
        with self._lock:
            self._close_logs()
            self._logs = logs
            self._paths = paths
            for name in STREAM_NAMES:
                self._patch(name)
        return paths

    def detach(self, paths: tuple[Path, ...]) -> None:
        with self._lock:
            if paths != self._paths:
                return
            self._close_logs()
            self._paths = None
            for name in STREAM_NAMES:
                self._unpatch(name)

    def write(self, name: str, text) -> None:
        if not isinstance(text, str):
            return
        with self._lock:
            log = self._logs.get(name)
            if log is None:
                return
            try:
                log.write(text)
            except (OSError, ValueError):
                pass

    def _close_logs(self) -> None:
        for log in self._logs.values():
            try:
                log.close()
            except OSError:
                pass
        self._logs = {}

    def _patch(self, name: str) -> None:
        stream = getattr(sys, name)
        patched = self._patched.get(name)
        if patched is not None and patched[0] is stream:
            return
        self._unpatch(name)
        try:
            original_write = stream.write

            def write(text):
                written = original_write(text)
                self.write(name, text)
                return written

            def writelines(lines):
                for line in lines:
                    write(line)

            stream.write = write
            stream.writelines = writelines
        except (AttributeError, TypeError):
            return
        self._patched[name] = (stream, write, writelines)

    def _unpatch(self, name: str) -> None:
        patched = self._patched.pop(name, None)
        if patched is None:
            return
        stream, write, writelines = patched
        attributes = getattr(stream, "__dict__", {})
        for attribute, value in (("write", write), ("writelines", writelines)):
            if attributes.get(attribute) is value:
                delattr(stream, attribute)


_capture = ConsoleCapture()


def attach(log_dir: Path) -> tuple[Path, ...]:
    return _capture.attach(log_dir)


def detach(paths: tuple[Path, ...]) -> None:
    _capture.detach(paths)
