from typing import Any, TypedDict

from gradio_client import FileData


class LogEntry(TypedDict, total=False):
    project: str
    run: str
    run_id: str | None
    metrics: dict[str, Any]
    step: int | None
    config: dict[str, Any] | None
    log_id: str | None


class SystemLogEntry(TypedDict, total=False):
    project: str
    run: str
    run_id: str | None
    metrics: dict[str, Any]
    timestamp: str
    log_id: str | None


class AlertEntry(TypedDict, total=False):
    project: str
    run: str
    run_id: str | None
    title: str
    text: str | None
    level: str
    step: int | None
    timestamp: str
    alert_id: str | None


class UploadEntry(TypedDict):
    project: str
    run: str | None
    run_id: str | None
    step: int | None
    relative_path: str | None
    uploaded_file: FileData
