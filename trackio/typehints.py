from typing import Any, TypedDict

from gradio import FileData


class LogEntry(TypedDict):
    project: str
    run_id: int
    metrics: dict[str, Any]
    step: int | None


class UploadEntry(TypedDict):
    project: str
    run_id: int
    step: int | None
    uploaded_file: FileData
