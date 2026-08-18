from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from trackio import cas

RUN_ID_ENV = "TRACKIO_LOGBOOK_RUN_ID"
RUN_DIR_ENV = "TRACKIO_LOGBOOK_RUN_DIR"
EVENT_DIR_ENV = "TRACKIO_LOGBOOK_EVENT_DIR"
WORKING_DIR_ENV = "TRACKIO_LOGBOOK_WORKING_DIR"

SCHEMA_VERSION = 1
SAFE_ENV_VALUES = (
    "CUDA_VISIBLE_DEVICES",
    "NVIDIA_VISIBLE_DEVICES",
    "OMP_NUM_THREADS",
    "MKL_NUM_THREADS",
    "PYTHONHASHSEED",
    "TOKENIZERS_PARALLELISM",
)
PRIVATE_PATH_PARTS = {".aws", ".config", ".gnupg", ".ssh", "keychains"}
PRIVATE_FILE_NAMES = {
    ".env",
    ".netrc",
    ".npmrc",
    ".pypirc",
    "credentials",
    "credentials.json",
    "secrets.json",
    "stored_tokens",
    "token",
}
INTERNAL_PATH_PARTS = {".cache", ".git", ".trackio", "__pycache__"}
ENVIRONMENT_PATH_PARTS = {"site-packages", "dist-packages"}
SYSTEM_PATH_PREFIXES = tuple(
    Path(path) for path in ("/System", "/Library", "/usr", "/bin", "/sbin", "/etc")
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_safe(value: Any) -> Any:
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        if isinstance(value, dict):
            return {str(key): _json_safe(item) for key, item in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [_json_safe(item) for item in value]
        return repr(value)


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(f"{path.name}.partial.{uuid.uuid4().hex}")
    try:
        partial.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(partial, path)
    finally:
        partial.unlink(missing_ok=True)


def record_sdk_event(kind: str, **payload: Any) -> None:
    """Record a semantic Trackio event when running under ``logbook run``.

    Events use one atomically-created file each. This remains safe when training
    launches multiple Python processes and never edits curated Logbook pages.
    The parent ``logbook run`` process projects the events after the command
    exits.
    """

    event_dir = os.environ.get(EVENT_DIR_ENV)
    run_id = os.environ.get(RUN_ID_ENV)
    if not event_dir or not run_id:
        return
    try:
        target = Path(event_dir)
        target.mkdir(parents=True, exist_ok=True)
        event = {
            "schema_version": SCHEMA_VERSION,
            "kind": kind,
            "run_id": run_id,
            "timestamp": _now_iso(),
            "pid": os.getpid(),
            **{key: _json_safe(value) for key, value in payload.items()},
        }
        name = f"sdk-{time.time_ns()}-{os.getpid()}-{uuid.uuid4().hex}.json"
        _atomic_json(target / name, event)
    except Exception:
        # Provenance is deliberately non-fatal to the training workload. The
        # parent records the missing SDK provider in capture diagnostics.
        return


def _run_git(cwd: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(cwd), *args],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            errors="replace",
            timeout=10,
        )
        return result.stdout.rstrip()
    except (OSError, subprocess.SubprocessError):
        return None


def _git_snapshot(cwd: Path, run_dir: Path) -> dict[str, Any] | None:
    root_text = _run_git(cwd, "rev-parse", "--show-toplevel")
    if not root_text:
        return None
    root = Path(root_text).resolve()
    commit = _run_git(root, "rev-parse", "HEAD")
    status = _run_git(root, "status", "--porcelain=v1", "--untracked-files=all")
    branch = _run_git(root, "branch", "--show-current")
    remote = _run_git(root, "remote", "get-url", "origin")
    diff = _run_git(root, "diff", "--binary", "HEAD", "--")
    diff_file = None
    diff_digest = None
    diff_size = None
    if diff:
        diff_file = run_dir / "git.patch"
        diff_file.write_text(diff + "\n", encoding="utf-8")
        diff_digest, diff_size = cas.hash_file(diff_file)
    return {
        "root": str(root),
        "commit": commit,
        "branch": branch,
        "remote": remote,
        "dirty": bool(status),
        "status": status.splitlines() if status else [],
        "patch": diff_file.name if diff_file else None,
        "patch_digest": diff_digest,
        "patch_size": diff_size,
    }


def evidence_root(proj: Path) -> Path:
    return proj / "run-evidence"


def _blob_path(root: Path, digest: str) -> Path:
    return root / "blobs" / "sha256" / digest[:2] / digest


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _logical_path(path: Path, cwd: Path) -> str:
    try:
        return path.relative_to(cwd).as_posix()
    except ValueError:
        return path.as_posix()


def _capture_file(root: Path, path: Path, cwd: Path, role: str) -> dict[str, Any]:
    resolved = path.resolve()
    digest, size = cas.hash_file(resolved)
    target = _blob_path(root, digest)
    cas.stage_blob_from_file(resolved, digest, target)
    return {
        "path": _logical_path(resolved, cwd),
        "original_path": str(resolved),
        "role": role,
        "digest": digest,
        "size": size,
        "storage": "captured",
        "blob_path": str(target),
    }


def _path_omission(path: Path, cwd: Path, python_prefixes: list[Path]) -> str | None:
    lowered = {part.lower() for part in path.parts}
    if PRIVATE_PATH_PARTS & lowered or path.name.lower() in PRIVATE_FILE_NAMES:
        return "sensitive-path-policy"
    if INTERNAL_PATH_PARTS & lowered:
        return "trackio-or-vcs-internal"
    if any(_is_within(path, prefix) for prefix in python_prefixes):
        return "python-environment"
    if ENVIRONMENT_PATH_PARTS & lowered:
        return "python-environment"
    if path.as_posix().startswith(("/dev/", "/proc/", "/sys/")):
        return "operating-system-virtual-file"
    if any(_is_within(path, prefix) for prefix in SYSTEM_PATH_PREFIXES):
        return "operating-system-file"
    return None


def _read_events(event_dir: Path) -> tuple[list[dict], list[str]]:
    events: list[dict] = []
    warnings: list[str] = []
    for path in sorted(event_dir.glob("*.json")):
        try:
            event = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(event, dict):
                events.append(event)
        except (OSError, ValueError) as exc:
            warnings.append(f"Could not read {path.name}: {exc}")
    for path in sorted(event_dir.glob("python-*.jsonl")):
        try:
            with path.open(encoding="utf-8") as stream:
                for line_number, line in enumerate(stream, 1):
                    try:
                        event = json.loads(line)
                        if isinstance(event, dict):
                            events.append(event)
                    except ValueError as exc:
                        warnings.append(
                            f"Could not parse {path.name}:{line_number}: {exc}"
                        )
        except OSError as exc:
            warnings.append(f"Could not read {path.name}: {exc}")
    events.sort(
        key=lambda event: (str(event.get("timestamp", "")), event.get("pid", 0))
    )
    return events, warnings


def _sitecustomize_source() -> str:
    # Self-contained by design: it also works when the child interpreter uses a
    # different environment where Trackio is not importable.
    return '''\
import json as _json
import importlib.metadata as _metadata
import os as _os
import platform as _platform
import sys as _sys
import time as _time

_event_dir = _os.environ.get("TRACKIO_LOGBOOK_EVENT_DIR")
_run_id = _os.environ.get("TRACKIO_LOGBOOK_RUN_ID")
_seen = set()
_fd = None
try:
    _packages = sorted(
        {
            (dist.metadata.get("Name") or "", dist.version)
            for dist in _metadata.distributions()
            if dist.metadata.get("Name")
        }
    )
except Exception:
    _packages = []
try:
    if _event_dir and _run_id:
        _os.makedirs(_event_dir, exist_ok=True)
        _event_path = _os.path.join(
            _event_dir, f"python-{_os.getpid()}-{_time.time_ns()}.jsonl"
        )
        _fd = _os.open(
            _event_path, _os.O_WRONLY | _os.O_CREAT | _os.O_APPEND, 0o600
        )
except Exception:
    _fd = None

def _emit(kind, **payload):
    if _fd is None:
        return
    try:
        event = {
            "schema_version": 1,
            "kind": kind,
            "run_id": _run_id,
            "timestamp": _time.time_ns(),
            "pid": _os.getpid(),
            **payload,
        }
        _os.write(_fd, (_json.dumps(event, ensure_ascii=False) + "\\n").encode())
    except Exception:
        pass

def _audit(event, args):
    try:
        if event == "open" and args:
            raw_path = args[0]
            if not isinstance(raw_path, (str, bytes, _os.PathLike)):
                return
            path = _os.path.abspath(_os.fsdecode(raw_path))
            mode = args[1] if len(args) > 1 else None
            flags = args[2] if len(args) > 2 else 0
            writing = bool(
                isinstance(mode, str) and any(mark in mode for mark in "wax+")
            )
            if isinstance(flags, int):
                writing = writing or bool(
                    flags
                    & (
                        _os.O_WRONLY
                        | _os.O_RDWR
                        | _os.O_CREAT
                        | _os.O_TRUNC
                        | _os.O_APPEND
                    )
                )
            operation = "write" if writing else "read"
            key = (operation, path)
            if key not in _seen:
                _seen.add(key)
                _emit("file_access", operation=operation, path=path)
        elif event == "import" and args:
            name = args[0] if isinstance(args[0], str) else None
            filename = args[1] if len(args) > 1 and isinstance(args[1], str) else None
            key = ("import", name, filename)
            if name and key not in _seen:
                _seen.add(key)
                _emit("module_import", module=name, path=filename)
        elif event in {"os.rename", "os.replace"} and len(args) > 1:
            raw_path = args[1]
            if isinstance(raw_path, (str, bytes, _os.PathLike)):
                path = _os.path.abspath(_os.fsdecode(raw_path))
                key = ("write", path)
                if key not in _seen:
                    _seen.add(key)
                    _emit("file_access", operation="write", path=path)
    except Exception:
        pass

try:
    _sys.addaudithook(_audit)
    _emit(
        "python_runtime",
        executable=_sys.executable,
        version=_sys.version,
        prefix=_sys.prefix,
        base_prefix=getattr(_sys, "base_prefix", _sys.prefix),
        platform=_platform.platform(),
        machine=_platform.machine(),
        implementation=_platform.python_implementation(),
        sys_path=list(_sys.path),
        packages=_packages,
    )
except Exception:
    pass
'''


class RunEvidence:
    def __init__(self, proj: Path, run_id: str, run_dir: Path, record: dict):
        self.proj = proj
        self.root = evidence_root(proj)
        self.run_id = run_id
        self.run_dir = run_dir
        self.event_dir = run_dir / "events"
        self.record = record

    @classmethod
    def start(cls, proj: Path, command: list[str], cwd: Path) -> "RunEvidence":
        run_id = uuid.uuid4().hex
        root = evidence_root(proj)
        run_dir = root / "runs" / run_id
        event_dir = run_dir / "events"
        event_dir.mkdir(parents=True, exist_ok=False)
        (run_dir / "stdout.log").touch(mode=0o600)
        (run_dir / "stderr.log").touch(mode=0o600)
        record = {
            "schema_version": SCHEMA_VERSION,
            "run_id": run_id,
            "state": "running",
            "evidence_status": "collecting",
            "command": list(command),
            "cwd": str(cwd.resolve()),
            "started_at": _now_iso(),
            "execution": {
                "platform": platform.platform(),
                "python": sys.version,
                "executable": sys.executable,
                "environment": {
                    "names": sorted(os.environ),
                    "safe_values": {
                        key: os.environ[key]
                        for key in SAFE_ENV_VALUES
                        if key in os.environ
                    },
                },
            },
            "git": _git_snapshot(cwd, run_dir),
            "providers": {
                "filesystem_snapshot": {"status": "enabled"},
                "python_audit": {"status": "pending"},
                "trackio_sdk": {"status": "pending"},
            },
            "inputs": [],
            "outputs": [],
            "trackio": {"runs": [], "artifact_inputs": [], "artifact_outputs": []},
            "warnings": [],
            "limitations": [
                "Native subprocess and non-Python file reads are not observed; "
                "filesystem output snapshots remain active as a fallback.",
                "The filesystem fallback recognizes supported model/data extensions; "
                "arbitrary extensions require the Python audit provider.",
                "Network responses are not captured automatically.",
                "Environment variable names are recorded, but only reproducibility-safe "
                "values are retained to avoid capturing secrets.",
                "Known credential files and private/cache directories are never copied; "
                "sensitive accesses are recorded only as omitted paths.",
            ],
        }
        evidence = cls(proj, run_id, run_dir, record)
        evidence._write()
        return evidence

    def _write(self) -> None:
        _atomic_json(self.run_dir / "run.json", self.record)

    def fail_to_start(self, error: str) -> None:
        self.record.update(
            {
                "state": "failed_to_start",
                "evidence_status": "degraded",
                "ended_at": _now_iso(),
                "warnings": [
                    *self.record.get("warnings", []),
                    f"Command could not start: {error}",
                ],
            }
        )
        self._write()
        shutil.rmtree(self.run_dir / "python-hook", ignore_errors=True)

    @property
    def stdout_path(self) -> Path:
        return self.run_dir / "stdout.log"

    @property
    def stderr_path(self) -> Path:
        return self.run_dir / "stderr.log"

    def child_environment(self) -> dict[str, str]:
        hook_dir = self.run_dir / "python-hook"
        hook_dir.mkdir(parents=True, exist_ok=True)
        (hook_dir / "sitecustomize.py").write_text(
            _sitecustomize_source(), encoding="utf-8"
        )
        env = os.environ.copy()
        old_pythonpath = env.get("PYTHONPATH")
        env["PYTHONPATH"] = os.pathsep.join(
            [str(hook_dir), *([old_pythonpath] if old_pythonpath else [])]
        )
        env[RUN_ID_ENV] = self.run_id
        env[RUN_DIR_ENV] = str(self.run_dir)
        env[EVENT_DIR_ENV] = str(self.event_dir)
        env[WORKING_DIR_ENV] = self.record["cwd"]
        return env

    def _stage_paths(
        self,
        paths: set[Path],
        role: str,
        python_prefixes: list[Path],
    ) -> list[dict[str, Any]]:
        cwd = Path(self.record["cwd"])
        captured: list[dict[str, Any]] = []
        seen: set[str] = set()
        for path in sorted(paths, key=lambda item: str(item)):
            try:
                resolved = path.resolve()
            except OSError:
                resolved = path.absolute()
            key = str(resolved)
            if key in seen:
                continue
            seen.add(key)
            omission = _path_omission(resolved, cwd, python_prefixes)
            if omission:
                if omission not in {
                    "trackio-or-vcs-internal",
                    "python-environment",
                    "operating-system-file",
                    "operating-system-virtual-file",
                }:
                    captured.append(
                        {
                            "path": _logical_path(resolved, cwd),
                            "original_path": key,
                            "role": role,
                            "storage": "ignored",
                            "reason": omission,
                        }
                    )
                continue
            try:
                if not resolved.is_file() or resolved.is_symlink():
                    continue
                entry = _capture_file(self.root, resolved, cwd, role)
                if role == "output" and entry["size"] == 0:
                    continue
                captured.append(entry)
            except (OSError, ValueError) as exc:
                captured.append(
                    {
                        "path": _logical_path(resolved, cwd),
                        "original_path": key,
                        "role": role,
                        "storage": "failed",
                        "error": str(exc),
                    }
                )
        return captured

    def finalize(
        self,
        *,
        exit_code: int,
        duration_s: float,
        fallback_outputs: list[tuple[str, int]],
        code_paths: list[str],
        filesystem_snapshot_status: str,
    ) -> dict:
        events, warnings = _read_events(self.event_dir)
        if filesystem_snapshot_status not in {"complete", "disabled"}:
            warnings.append(
                "Filesystem output snapshot was incomplete: "
                f"{filesystem_snapshot_status}"
            )
        runtimes = [event for event in events if event.get("kind") == "python_runtime"]
        sdk_events = [event for event in events if str(event.get("kind", "")).startswith("trackio_")]
        accesses = [event for event in events if event.get("kind") == "file_access"]

        python_prefixes = []
        for runtime in runtimes:
            for key in ("prefix", "base_prefix"):
                if runtime.get(key):
                    python_prefixes.append(Path(runtime[key]).resolve())

        read_paths = {
            Path(event["path"])
            for event in accesses
            if event.get("operation") == "read" and event.get("path")
        }
        write_paths = {
            Path(event["path"])
            for event in accesses
            if event.get("operation") == "write" and event.get("path")
        }
        write_paths.update(Path(path) for path, _size in fallback_outputs)
        code = {Path(path) for path in code_paths}
        read_paths.update(code)
        read_paths.difference_update(write_paths)

        inputs = self._stage_paths(read_paths, "input", python_prefixes)
        outputs = self._stage_paths(write_paths, "output", python_prefixes)
        code_keys = {str(path.resolve()) for path in code}
        for entry in inputs:
            if entry.get("original_path") in code_keys:
                entry["role"] = "code"

        trackio_runs: list[dict] = []
        artifact_inputs: list[dict] = []
        artifact_outputs: list[dict] = []
        seen_trackio_runs: set[tuple] = set()
        for event in sdk_events:
            kind = event.get("kind")
            if kind == "trackio_run_started":
                key = (event.get("project"), event.get("trackio_run_id"))
                if key not in seen_trackio_runs:
                    seen_trackio_runs.add(key)
                    trackio_runs.append(event)
            elif kind == "trackio_artifact_input":
                artifact_inputs.append(event)
            elif kind == "trackio_artifact_output":
                artifact_outputs.append(event)

        stdout_digest, stdout_size = cas.hash_file(self.stdout_path)
        stderr_digest, stderr_size = cas.hash_file(self.stderr_path)
        failed = [
            entry
            for entry in [*inputs, *outputs]
            if entry.get("storage") == "failed"
        ]
        self.record.update(
            {
                "state": "succeeded" if exit_code == 0 else "failed",
                "evidence_status": "degraded" if failed or warnings else "complete_with_limitations",
                "ended_at": _now_iso(),
                "duration_s": round(duration_s, 3),
                "exit_code": exit_code,
                "logs": {
                    "stdout": {
                        "path": "stdout.log",
                        "digest": stdout_digest,
                        "size": stdout_size,
                    },
                    "stderr": {
                        "path": "stderr.log",
                        "digest": stderr_digest,
                        "size": stderr_size,
                    },
                },
                "providers": {
                    "filesystem_snapshot": {"status": filesystem_snapshot_status},
                    "python_audit": {
                        "status": "complete" if runtimes else "unavailable",
                        "processes": len({event.get("pid") for event in runtimes}),
                        "accesses": len(accesses),
                    },
                    "trackio_sdk": {
                        "status": "complete" if sdk_events else "not_used",
                        "events": len(sdk_events),
                    },
                },
                "inputs": inputs,
                "outputs": outputs,
                "trackio": {
                    "runs": trackio_runs,
                    "artifact_inputs": artifact_inputs,
                    "artifact_outputs": artifact_outputs,
                },
                "python": {
                    "runtimes": runtimes,
                    "imports": [
                        event for event in events if event.get("kind") == "module_import"
                    ],
                },
                "warnings": [*self.record.get("warnings", []), *warnings],
            }
        )
        self._write()
        shutil.rmtree(self.run_dir / "python-hook", ignore_errors=True)
        return self.record
