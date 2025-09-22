from dataclasses import dataclass
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
    run: str
    step: int | None
    uploaded_file: FileData


@dataclass
class MediaData:
    caption: str | None
    file_path: str
