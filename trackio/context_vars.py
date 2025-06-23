import contextvars
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from trackio.run import Run
    from trackio.sqlite_storage import CommitScheduler, DummyCommitScheduler

current_run: contextvars.ContextVar["Run | None"] = contextvars.ContextVar(
    "current_run", default=None
)
current_project: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "current_project", default=None
)
current_server: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "current_server", default=None
)
current_scheduler: contextvars.ContextVar[
    "CommitScheduler | DummyCommitScheduler | None"
] = contextvars.ContextVar("current_scheduler", default=None)
