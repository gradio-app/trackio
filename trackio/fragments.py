"""Append-only JSONL fragments used as a durable fallback for metric logging.

Fragments are immutable JSONL files, one writer (process) per subdirectory, so
concurrent training processes never contend on a shared file. They are written
either to a Hugging Face Bucket inbox (when a Space is unreachable) or to a
local inbox directory (when SQLite is unsafe, e.g. on network filesystems), and
are later imported into the project SQLite database by the process that owns it
(the Space or the dashboard server). Records carry the same ``log_id``/
``alert_id`` UUIDs as the HTTP logging endpoints, and imports use
``INSERT OR IGNORE``, so importing a fragment is idempotent: fragments are
deleted only after a successful import, and re-importing after a crash is
harmless.
"""

import tempfile
import threading
import uuid
from pathlib import Path
from typing import Any

import huggingface_hub
import orjson

from trackio import utils
from trackio.typehints import AlertEntry, LogEntry, SystemLogEntry

FRAGMENT_VERSION = 1
INBOX_DIR_NAME = "inbox"
BUCKET_INBOX_PREFIX = "trackio/inbox"
BUCKET_MEDIA_PREFIX = "trackio/media"

METRIC_KIND = "metric"
SYSTEM_METRIC_KIND = "system_metric"
ALERT_KIND = "alert"
KINDS = {METRIC_KIND, SYSTEM_METRIC_KIND, ALERT_KIND}


def local_inbox_dir() -> Path:
    return utils.TRACKIO_DIR / INBOX_DIR_NAME


def metric_record(entry: LogEntry | dict) -> dict:
    return {
        "v": FRAGMENT_VERSION,
        "kind": METRIC_KIND,
        "project": entry["project"],
        "run": entry["run"],
        "run_id": entry.get("run_id"),
        "metrics": utils.serialize_values(entry.get("metrics") or {}),
        "step": entry.get("step"),
        "timestamp": entry.get("timestamp"),
        "config": utils.serialize_values(entry.get("config"))
        if entry.get("config")
        else None,
        "log_id": entry.get("log_id"),
    }


def system_metric_record(entry: SystemLogEntry | dict) -> dict:
    return {
        "v": FRAGMENT_VERSION,
        "kind": SYSTEM_METRIC_KIND,
        "project": entry["project"],
        "run": entry["run"],
        "run_id": entry.get("run_id"),
        "metrics": utils.serialize_values(entry.get("metrics") or {}),
        "timestamp": entry.get("timestamp"),
        "log_id": entry.get("log_id"),
    }


def alert_record(entry: AlertEntry | dict) -> dict:
    return {
        "v": FRAGMENT_VERSION,
        "kind": ALERT_KIND,
        "project": entry["project"],
        "run": entry["run"],
        "run_id": entry.get("run_id"),
        "title": entry["title"],
        "text": entry.get("text"),
        "level": entry.get("level"),
        "step": entry.get("step"),
        "timestamp": entry.get("timestamp"),
        "alert_id": entry.get("alert_id"),
    }


def bucket_media_path(
    project: str,
    run: str | None,
    step: int | None,
    relative_path: str | None,
    filename: str,
) -> str:
    parts = [BUCKET_MEDIA_PREFIX, utils.canonical_project_name(project)]
    if run:
        parts.append(run)
        if step is not None:
            parts.append(str(step))
    else:
        parts.append("files")
        if relative_path:
            parts.append(str(relative_path))
    parts.append(filename)
    return "/".join(parts)


class FragmentWriter:
    """Writes immutable JSONL fragments for a single writer (process)."""

    def __init__(self, writer_id: str | None = None):
        self.writer_id = writer_id or uuid.uuid4().hex[:16]
        self._seq = 0
        self._lock = threading.Lock()

    def _next_fragment_name(self) -> str:
        with self._lock:
            name = f"{self._seq:08d}.jsonl"
            self._seq += 1
        return name

    @staticmethod
    def serialize_records(records: list[dict]) -> bytes:
        return b"".join(orjson.dumps(record) + b"\n" for record in records)

    def write_local(
        self, records: list[dict], inbox_dir: Path | None = None
    ) -> Path | None:
        if not records:
            return None
        inbox = inbox_dir or local_inbox_dir()
        writer_dir = inbox / self.writer_id
        fragment_path = writer_dir / self._next_fragment_name()
        data = self.serialize_records(records)
        for attempt in range(3):
            writer_dir.mkdir(parents=True, exist_ok=True)
            try:
                with tempfile.NamedTemporaryFile(
                    mode="wb", dir=writer_dir, suffix=".tmp", delete=False
                ) as tmp:
                    tmp.write(data)
                    tmp_path = Path(tmp.name)
                tmp_path.replace(fragment_path)
                return fragment_path
            except FileNotFoundError:
                if attempt == 2 or writer_dir.exists():
                    raise

    def write_to_bucket(self, records: list[dict], bucket_id: str) -> str | None:
        if not records:
            return None
        remote_path = (
            f"{BUCKET_INBOX_PREFIX}/{self.writer_id}/{self._next_fragment_name()}"
        )
        huggingface_hub.batch_bucket_files(
            bucket_id,
            add=[(self.serialize_records(records), remote_path)],
            token=huggingface_hub.utils.get_token(),
        )
        return remote_path


def parse_fragment_bytes(data: bytes) -> list[dict]:
    records = []
    for line in data.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = orjson.loads(line)
        except orjson.JSONDecodeError:
            continue
        if isinstance(record, dict) and record.get("kind") in KINDS:
            records.append(record)
    return records


def _group_by_run(records: list[dict]) -> dict[tuple, list[dict]]:
    grouped: dict[tuple, list[dict]] = {}
    for record in records:
        key = (record.get("project"), record.get("run"), record.get("run_id"))
        grouped.setdefault(key, []).append(record)
    return grouped


def import_records(records: list[dict]) -> int:
    from trackio.sqlite_storage import SQLiteStorage  # noqa: PLC0415

    metric_records = [r for r in records if r.get("kind") == METRIC_KIND]
    system_records = [r for r in records if r.get("kind") == SYSTEM_METRIC_KIND]
    alert_records = [r for r in records if r.get("kind") == ALERT_KIND]
    imported = 0

    for (project, run, run_id), group in _group_by_run(metric_records).items():
        if not project or not run:
            continue
        config = next((r["config"] for r in group if r.get("config")), None)
        has_timestamps = all(r.get("timestamp") for r in group)
        SQLiteStorage.bulk_log(
            project=project,
            run=run,
            run_id=run_id,
            metrics_list=[r.get("metrics") or {} for r in group],
            steps=[r.get("step") for r in group],
            timestamps=[r["timestamp"] for r in group] if has_timestamps else None,
            config=config,
            log_ids=[r.get("log_id") for r in group],
        )
        imported += len(group)

    for (project, run, run_id), group in _group_by_run(system_records).items():
        if not project or not run:
            continue
        has_timestamps = all(r.get("timestamp") for r in group)
        SQLiteStorage.bulk_log_system(
            project=project,
            run=run,
            run_id=run_id,
            metrics_list=[r.get("metrics") or {} for r in group],
            timestamps=[r["timestamp"] for r in group] if has_timestamps else None,
            log_ids=[r.get("log_id") for r in group],
        )
        imported += len(group)

    for (project, run, run_id), group in _group_by_run(alert_records).items():
        if not project or not run:
            continue
        has_timestamps = all(r.get("timestamp") for r in group)
        SQLiteStorage.bulk_alert(
            project=project,
            run=run,
            run_id=run_id,
            titles=[r.get("title") or "" for r in group],
            texts=[r.get("text") for r in group],
            levels=[r.get("level") or "WARN" for r in group],
            steps=[r.get("step") for r in group],
            timestamps=[r["timestamp"] for r in group] if has_timestamps else None,
            alert_ids=[r.get("alert_id") for r in group],
        )
        imported += len(group)

    return imported


def import_inbox_dir(inbox_dir: Path | None = None) -> int:
    inbox = inbox_dir or local_inbox_dir()
    if not inbox.exists():
        return 0
    imported = 0
    for fragment_path in sorted(inbox.rglob("*.jsonl")):
        try:
            data = fragment_path.read_bytes()
        except OSError:
            continue
        records = parse_fragment_bytes(data)
        if records:
            imported += import_records(records)
        try:
            fragment_path.unlink()
        except OSError:
            pass
    for writer_dir in inbox.glob("*"):
        if writer_dir.is_dir():
            try:
                writer_dir.rmdir()
            except OSError:
                pass
    return imported


def list_bucket_inbox_paths(bucket_id: str) -> list[str]:
    try:
        items = huggingface_hub.list_bucket_tree(
            bucket_id,
            prefix=BUCKET_INBOX_PREFIX,
            recursive=True,
            token=huggingface_hub.utils.get_token(),
        )
    except Exception:
        return []
    return sorted(
        item.path
        for item in items
        if getattr(item, "type", None) == "file"
        and getattr(item, "path", "").endswith(".jsonl")
    )


def import_inbox_from_bucket(bucket_id: str) -> int:
    paths = list_bucket_inbox_paths(bucket_id)
    if not paths:
        return 0
    imported = 0
    consumed: list[str] = []
    with tempfile.TemporaryDirectory() as tmp_dir:
        for i, remote_path in enumerate(paths):
            local_path = Path(tmp_dir) / f"{i}.jsonl"
            try:
                huggingface_hub.download_bucket_files(
                    bucket_id,
                    files=[(remote_path, str(local_path))],
                    token=huggingface_hub.utils.get_token(),
                )
                records = parse_fragment_bytes(local_path.read_bytes())
            except Exception:
                continue
            if records:
                imported += import_records(records)
            consumed.append(remote_path)
    if consumed:
        try:
            huggingface_hub.batch_bucket_files(
                bucket_id,
                delete=consumed,
                token=huggingface_hub.utils.get_token(),
            )
        except Exception:
            pass
    return imported


def _add_files_to_bucket(bucket_id: str, additions: list[tuple[str, str]]) -> None:
    if additions:
        huggingface_hub.batch_bucket_files(
            bucket_id,
            add=additions,
            token=huggingface_hub.utils.get_token(),
        )


def upload_media_files_to_bucket(bucket_id: str, uploads: list[dict[str, Any]]) -> None:
    _add_files_to_bucket(
        bucket_id,
        [
            (
                str(p),
                bucket_media_path(
                    project=upload["project"],
                    run=upload.get("run"),
                    step=upload.get("step"),
                    relative_path=upload.get("relative_path"),
                    filename=p.name,
                ),
            )
            for upload in uploads
            if (p := Path(upload["file_path"])).exists()
        ],
    )


def upload_artifact_blobs_to_bucket(
    bucket_id: str, uploads: list[dict[str, Any]]
) -> None:
    _add_files_to_bucket(
        bucket_id,
        [
            (str(p), f"trackio/{p.relative_to(utils.TRACKIO_DIR).as_posix()}")
            for upload in uploads
            if (p := Path(upload["file_path"])).exists()
        ],
    )
