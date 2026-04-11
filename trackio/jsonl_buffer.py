from __future__ import annotations

import os
from pathlib import Path

import orjson

from trackio.utils import TRACKIO_DIR, serialize_values

BUFFER_DIR = TRACKIO_DIR / "pending"


def _buffer_path(project: str, kind: str) -> Path:
    safe = "".join(c for c in project if c.isalnum() or c in ("-", "_")).rstrip()
    if not safe:
        safe = "default"
    return BUFFER_DIR / f"{safe}_{kind}.jsonl"


def _append(path: Path, entries: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "ab") as f:
        for entry in entries:
            f.write(orjson.dumps(entry) + b"\n")


def _read_all(path: Path) -> list[dict]:
    if not path.exists():
        return []
    entries = []
    with open(path, "rb") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    entries.append(orjson.loads(line))
                except Exception:
                    continue
    return entries


def _clear(path: Path) -> None:
    try:
        os.remove(path)
    except FileNotFoundError:
        pass


def append_logs(project: str, logs: list[dict], space_id: str) -> None:
    path = _buffer_path(project, "logs")
    entries = []
    for entry in logs:
        row = {
            "project": entry["project"],
            "run": entry["run"],
            "metrics": serialize_values(entry["metrics"]),
            "step": entry.get("step"),
            "log_id": entry.get("log_id"),
            "space_id": space_id,
        }
        if entry.get("config"):
            row["config"] = serialize_values(entry["config"])
        entries.append(row)
    _append(path, entries)


def append_system_logs(project: str, logs: list[dict], space_id: str) -> None:
    path = _buffer_path(project, "system_logs")
    entries = []
    for entry in logs:
        entries.append(
            {
                "project": entry["project"],
                "run": entry["run"],
                "metrics": serialize_values(entry["metrics"]),
                "timestamp": entry.get("timestamp"),
                "log_id": entry.get("log_id"),
                "space_id": space_id,
            }
        )
    _append(path, entries)


def append_uploads(project: str, uploads: list[dict], space_id: str) -> None:
    path = _buffer_path(project, "uploads")
    entries = []
    for entry in uploads:
        file_data = entry.get("uploaded_file")
        file_path = ""
        if isinstance(file_data, dict):
            file_path = file_data.get("path", "")
        elif hasattr(file_data, "path"):
            file_path = str(file_data.path)
        else:
            file_path = str(file_data)
        entries.append(
            {
                "project": entry["project"],
                "run": entry.get("run"),
                "step": entry.get("step"),
                "file_path": file_path,
                "relative_path": entry.get("relative_path"),
                "space_id": space_id,
            }
        )
    _append(path, entries)


def append_alerts(project: str, alerts: list[dict]) -> None:
    path = _buffer_path(project, "alerts")
    entries = []
    for entry in alerts:
        entries.append(
            {
                "project": entry["project"],
                "run": entry["run"],
                "title": entry["title"],
                "text": entry.get("text"),
                "level": entry["level"],
                "step": entry.get("step"),
                "timestamp": entry.get("timestamp"),
                "alert_id": entry.get("alert_id"),
            }
        )
    _append(path, entries)


def get_pending_logs(project: str) -> list[dict] | None:
    entries = _read_all(_buffer_path(project, "logs"))
    if not entries:
        return None
    logs = []
    for row in entries:
        logs.append(
            {
                "project": row["project"],
                "run": row["run"],
                "metrics": row["metrics"],
                "step": row.get("step"),
                "log_id": row.get("log_id"),
                "config": row.get("config"),
            }
        )
    return {"logs": logs, "space_id": entries[0].get("space_id")}


def get_pending_system_logs(project: str) -> list[dict] | None:
    entries = _read_all(_buffer_path(project, "system_logs"))
    if not entries:
        return None
    logs = []
    for row in entries:
        logs.append(
            {
                "project": row["project"],
                "run": row["run"],
                "metrics": row["metrics"],
                "timestamp": row.get("timestamp"),
                "log_id": row.get("log_id"),
            }
        )
    return {"logs": logs, "space_id": entries[0].get("space_id")}


def get_pending_uploads(project: str) -> list[dict] | None:
    entries = _read_all(_buffer_path(project, "uploads"))
    if not entries:
        return None
    uploads = []
    for row in entries:
        uploads.append(
            {
                "project": row["project"],
                "run": row.get("run"),
                "step": row.get("step"),
                "file_path": row["file_path"],
                "relative_path": row.get("relative_path"),
            }
        )
    return {"uploads": uploads, "space_id": entries[0].get("space_id")}


def clear_logs(project: str) -> None:
    _clear(_buffer_path(project, "logs"))


def clear_system_logs(project: str) -> None:
    _clear(_buffer_path(project, "system_logs"))


def clear_uploads(project: str) -> None:
    _clear(_buffer_path(project, "uploads"))


def clear_alerts(project: str) -> None:
    _clear(_buffer_path(project, "alerts"))


def has_pending_data(project: str) -> bool:
    for kind in ("logs", "system_logs", "uploads", "alerts"):
        path = _buffer_path(project, kind)
        if path.exists() and path.stat().st_size > 0:
            return True
    return False
