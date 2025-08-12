from typing import Any, TypedDict


class LogEntry(TypedDict):
    project: str
    run: str
    metrics: dict[str, Any]
    step: int | None
