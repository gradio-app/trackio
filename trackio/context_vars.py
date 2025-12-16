import contextvars
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from trackio.run import Run

current_run: contextvars.ContextVar["Run | None"] = contextvars.ContextVar(
    "current_run", default=None
)
current_project: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "current_project", default=None
)
current_server: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "current_server", default=None
)
current_space_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "current_space_id", default=None
)
current_share_server: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "current_share_server", default=None
)
