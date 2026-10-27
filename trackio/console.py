import hashlib
import os
import re
import shlex
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from trackio.media import get_project_media_path
from trackio.utils import project_media_dir

if TYPE_CHECKING:
    from trackio.run import Run

CAPTURE_CONSOLE_ENV_VAR = "TRACKIO_CAPTURE_CONSOLE"
CONSOLE_FILE_PREFIX = "console-"
CONSOLE_FILE_SUFFIX = ".log"
FLUSH_INTERVAL = 10.0
MAX_CHUNK_BYTES = 1_000_000
MAX_TOTAL_BYTES = 20_000_000
DEFAULT_MAX_CHARS = 200_000
REDACTED = "REDACTED"
TRUNCATION_NOTICE = (
    "[trackio] Console output limit reached. Further output is not captured."
)

_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
_NEWLINE_RE = re.compile(r"\r?\n")
_SECRET_NAME_RE = re.compile(
    r"token|secret|passw|api[_-]?key|access[_-]?key|private[_-]?key", re.IGNORECASE
)
_NOTEBOOK_MARKERS = ("ipykernel", "colab_kernel_launcher")


def resolve_capture_console(capture_console: bool | None) -> bool:
    if capture_console is not None:
        return capture_console
    value = os.environ.get(CAPTURE_CONSOLE_ENV_VAR, "")
    return value.strip().lower() in ("1", "true", "yes", "on")


def redact_argv(argv: list[str]) -> list[str]:
    redacted = []
    redact_next = False
    for arg in argv:
        if redact_next:
            redacted.append(REDACTED)
            redact_next = False
            continue
        name, sep, _ = arg.partition("=")
        if sep and _SECRET_NAME_RE.search(name):
            redacted.append(f"{name}={REDACTED}")
            continue
        if arg.startswith("-") and _SECRET_NAME_RE.search(arg):
            redact_next = True
        redacted.append(arg)
    return redacted


def get_launch_command() -> str | None:
    argv = list(getattr(sys, "orig_argv", None) or [sys.executable, *sys.argv])
    if len(argv) < 2 or any(m in arg for arg in argv for m in _NOTEBOOK_MARKERS):
        return None
    argv[0] = Path(argv[0]).name or argv[0]
    return shlex.join(redact_argv(argv))


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _console_identity(run_id: str) -> str:
    return hashlib.sha256(run_id.encode("utf-8")).hexdigest()


class ConsoleCapture:
    """Wraps the `write` method of the existing `sys.stdout` and `sys.stderr`
    objects instead of replacing them, so logging handlers created before
    `trackio.init()` are captured too."""

    def __init__(self, run: "Run", interval: float = FLUSH_INTERVAL):
        self._run = run
        self._interval = interval
        self._lock = threading.RLock()
        self._patched: list[tuple[Any, Any, bool, Any]] = []
        self._session = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
        self._chunk_index = 0
        self._lines: list[str] = []
        self._chunk_bytes = 0
        self._total_bytes = 0
        self._partial = ""
        self._partial_time = ""
        self._dirty = True
        self._truncated = False
        self._stopped = False
        self._stop_flag = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        for stream in (sys.stdout, sys.stderr):
            self._patch(stream)
        self.flush()
        self._thread = threading.Thread(target=self._flush_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_flag.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        self._restore()
        with self._lock:
            self._stopped = True
            if self._partial:
                self._commit_line()
        self.flush()

    def _patch(self, stream: Any) -> None:
        if stream is None or any(s is stream for s, *_ in self._patched):
            return
        original = stream.write
        had_instance_attr = "write" in getattr(stream, "__dict__", {})

        def write(text):
            result = original(text)
            self._record(text)
            return result

        try:
            stream.write = write
        except (AttributeError, TypeError):
            return
        self._patched.append((stream, original, had_instance_attr, write))

    def _restore(self) -> None:
        for stream, original, had_instance_attr, wrapper in reversed(self._patched):
            try:
                if getattr(stream, "__dict__", {}).get("write") is not wrapper:
                    continue
                if had_instance_attr:
                    stream.write = original
                else:
                    del stream.write
            except Exception:
                pass
        self._patched = []

    def _record(self, text: Any) -> None:
        if not isinstance(text, str) or not text:
            return
        now = _timestamp()
        with self._lock:
            if self._stopped or self._truncated:
                return
            segments = _NEWLINE_RE.split(_ANSI_ESCAPE_RE.sub("", text))
            for i, segment in enumerate(segments):
                if "\r" in segment:
                    self._partial = ""
                    segment = segment.rsplit("\r", 1)[1]
                    self._partial_time = now
                if segment:
                    if not self._partial:
                        self._partial_time = now
                    remaining = max(
                        0,
                        self._remaining_bytes()
                        - len(
                            f"{self._partial_time} {self._partial}\n".encode("utf-8")
                        ),
                    )
                    encoded = segment[: remaining + 1].encode("utf-8")
                    self._partial += encoded[:remaining].decode(
                        "utf-8", errors="ignore"
                    )
                    if len(encoded) > remaining:
                        self._commit_line()
                        self._truncate()
                        break
                if i < len(segments) - 1:
                    self._commit_line()
                    if self._truncated:
                        break
            self._dirty = True

    def _remaining_bytes(self) -> int:
        notice = f"{_timestamp()} {TRUNCATION_NOTICE}\n"
        return MAX_TOTAL_BYTES - self._total_bytes - len(notice.encode("utf-8"))

    def _append_line(self, line: str) -> None:
        size = len(line.encode("utf-8"))
        self._lines.append(line)
        self._chunk_bytes += size
        self._total_bytes += size
        self._dirty = True

    def _truncate(self) -> None:
        if self._truncated:
            return
        self._partial = ""
        self._partial_time = ""
        self._append_line(f"{_timestamp()} {TRUNCATION_NOTICE}\n")
        self._truncated = True

    def _commit_line(self) -> None:
        line = f"{self._partial_time or _timestamp()} {self._partial}\n"
        self._partial = ""
        self._partial_time = ""
        if len(line.encode("utf-8")) > self._remaining_bytes():
            self._truncate()
        else:
            self._append_line(line)

    def _flush_loop(self) -> None:
        while not self._stop_flag.wait(self._interval):
            try:
                self.flush()
            except Exception as e:
                self._run._warn_once(
                    "console-flush",
                    f"trackio could not save console output for run '{self._run.name}': {e}.",
                )

    def flush(self) -> None:
        with self._lock:
            if not self._dirty:
                return
            content = "".join(self._lines)
            index = self._chunk_index
            if self._chunk_bytes >= MAX_CHUNK_BYTES:
                self._chunk_index += 1
                self._lines = []
                self._chunk_bytes = 0
            elif self._partial:
                content += f"{self._partial_time} {self._partial}\n"
            self._dirty = False
        path = self._write_chunk(index, content)
        self._run._upload_console_file(path)

    def _write_chunk(self, index: int, content: str) -> Path:
        directory = get_project_media_path(self._run.project, run=self._run.name)
        name = f"{CONSOLE_FILE_PREFIX}{self._session}-{_console_identity(self._run.id)}-{index:04d}{CONSOLE_FILE_SUFFIX}"
        path = directory / name
        tmp_path = directory / f".{name}.tmp"
        tmp_path.write_text(content, encoding="utf-8")
        os.replace(tmp_path, path)
        return path


def read_console_output(
    project: str,
    run: str,
    run_id: str | None = None,
    max_chars: int | None = DEFAULT_MAX_CHARS,
) -> dict[str, Any]:
    media_root = project_media_dir(project).resolve()
    run_dir = (media_root / run).resolve()
    if not run_dir.is_relative_to(media_root) or run_dir == media_root:
        return {"enabled": False, "text": "", "truncated": False}
    identity = _console_identity(run_id) if run_id is not None else "*"
    files = sorted(
        run_dir.glob(f"{CONSOLE_FILE_PREFIX}*-{identity}-*{CONSOLE_FILE_SUFFIX}")
    )
    if files and run_id is None:
        identity = files[-1].name.rsplit("-", 2)[1]
        files = [path for path in files if path.name.rsplit("-", 2)[1] == identity]
    if not files:
        return {"enabled": False, "text": "", "truncated": False}
    text = "".join(f.read_text(encoding="utf-8", errors="replace") for f in files)
    truncated = max_chars is not None and len(text) > max_chars
    if truncated:
        text = text[-max_chars:]
        text = text[text.find("\n") + 1 :]
    return {"enabled": True, "text": text, "truncated": truncated}
