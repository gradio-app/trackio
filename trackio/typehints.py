from typing import Any, TypedDict

from gradio import FileData


class LogEntry(TypedDict):
    project: str
    run: str
    metrics: dict[str, Any]
    step: int | None
    config: dict[str, Any] | None


class UploadEntry(TypedDict):
    project: str
    run: str | None
    step: int | None
    relative_path: str | None
    uploaded_file: FileData
