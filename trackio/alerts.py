from dataclasses import dataclass, field
from enum import Enum
from typing import Callable


class AlertLevel(str, Enum):
    INFO = "info"
    WARN = "warn"
    ERROR = "error"


ALERT_COLORS = {
    AlertLevel.INFO: "\033[94m",
    AlertLevel.WARN: "\033[93m",
    AlertLevel.ERROR: "\033[91m",
}
RESET_COLOR = "\033[0m"


@dataclass
class AlertCondition:
    condition: Callable[[dict], bool]
    title: str | Callable[[dict], str]
    text: str | Callable[[dict], str] | None
    level: AlertLevel = AlertLevel.WARN
    _last_state: bool = field(default=False, repr=False)

    def resolve_title(self, metrics: dict) -> str:
        return self.title(metrics) if callable(self.title) else self.title

    def resolve_text(self, metrics: dict) -> str | None:
        if self.text is None:
            return None
        return self.text(metrics) if callable(self.text) else self.text


def format_alert_terminal(
    level: AlertLevel, title: str, text: str | None, step: int | None
) -> str:
    color = ALERT_COLORS.get(level, "")
    step_str = f" (step {step})" if step is not None else ""
    if text:
        return f"{color}[TRACKIO {level.value.upper()}]{RESET_COLOR} {title}: {text}{step_str}"
    return f"{color}[TRACKIO {level.value.upper()}]{RESET_COLOR} {title}{step_str}"
