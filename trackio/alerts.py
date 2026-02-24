import json
import logging
import urllib.error
import urllib.request
from enum import Enum

logger = logging.getLogger(__name__)


class AlertLevel(str, Enum):
    INFO = "info"
    WARN = "warn"
    ERROR = "error"


ALERT_LEVEL_ORDER = {
    AlertLevel.INFO: 0,
    AlertLevel.WARN: 1,
    AlertLevel.ERROR: 2,
}

ALERT_COLORS = {
    AlertLevel.INFO: "\033[94m",
    AlertLevel.WARN: "\033[93m",
    AlertLevel.ERROR: "\033[91m",
}
RESET_COLOR = "\033[0m"

LEVEL_EMOJI = {
    AlertLevel.INFO: "ℹ️",
    AlertLevel.WARN: "⚠️",
    AlertLevel.ERROR: "🚨",
}


def format_alert_terminal(
    level: AlertLevel, title: str, text: str | None, step: int | None
) -> str:
    color = ALERT_COLORS.get(level, "")
    step_str = f" (step {step})" if step is not None else ""
    if text:
        return f"{color}[TRACKIO {level.value.upper()}]{RESET_COLOR} {title}: {text}{step_str}"
    return f"{color}[TRACKIO {level.value.upper()}]{RESET_COLOR} {title}{step_str}"


def _is_slack_url(url: str) -> bool:
    return "hooks.slack.com" in url


def _is_discord_url(url: str) -> bool:
    return "discord.com/api/webhooks" in url or "discordapp.com/api/webhooks" in url


def _build_slack_payload(
    level: AlertLevel,
    title: str,
    text: str | None,
    project: str,
    run: str,
    step: int | None,
) -> dict:
    emoji = LEVEL_EMOJI.get(level, "")
    step_str = f"  •  Step {step}" if step is not None else ""
    header = f"{emoji} *[{level.value.upper()}] {title}*"
    context = f"Project: {project}  •  Run: {run}{step_str}"
    blocks = [
        {"type": "section", "text": {"type": "mrkdwn", "text": header}},
    ]
    if text:
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": text}})
    blocks.append(
        {"type": "context", "elements": [{"type": "mrkdwn", "text": context}]}
    )
    return {"blocks": blocks}


def _build_discord_payload(
    level: AlertLevel,
    title: str,
    text: str | None,
    project: str,
    run: str,
    step: int | None,
) -> dict:
    color_map = {
        AlertLevel.INFO: 3447003,
        AlertLevel.WARN: 16776960,
        AlertLevel.ERROR: 15158332,
    }
    emoji = LEVEL_EMOJI.get(level, "")
    step_str = f"  •  Step {step}" if step is not None else ""
    embed = {
        "title": f"{emoji} [{level.value.upper()}] {title}",
        "color": color_map.get(level, 0),
        "footer": {"text": f"Project: {project}  •  Run: {run}{step_str}"},
    }
    if text:
        embed["description"] = text
    return {"embeds": [embed]}


def _build_generic_payload(
    level: AlertLevel,
    title: str,
    text: str | None,
    project: str,
    run: str,
    step: int | None,
    timestamp: str | None,
) -> dict:
    return {
        "level": level.value,
        "title": title,
        "text": text,
        "project": project,
        "run": run,
        "step": step,
        "timestamp": timestamp,
    }


def parse_alert_level(level: AlertLevel | str) -> AlertLevel:
    if isinstance(level, AlertLevel):
        return level
    normalized = level.lower().strip()
    try:
        return AlertLevel(normalized)
    except ValueError as e:
        allowed = ", ".join(lvl.value for lvl in AlertLevel)
        raise ValueError(
            f"Invalid alert level '{level}'. Expected one of: {allowed}."
        ) from e


def resolve_webhook_min_level(
    webhook_min_level: AlertLevel | str | None,
) -> AlertLevel | None:
    if webhook_min_level is None:
        return None
    return parse_alert_level(webhook_min_level)


def should_send_webhook(
    level: AlertLevel, webhook_min_level: AlertLevel | None
) -> bool:
    if webhook_min_level is None:
        return True
    return ALERT_LEVEL_ORDER[level] >= ALERT_LEVEL_ORDER[webhook_min_level]


def send_webhook(
    url: str,
    level: AlertLevel,
    title: str,
    text: str | None,
    project: str,
    run: str,
    step: int | None,
    timestamp: str | None = None,
) -> None:
    if _is_slack_url(url):
        payload = _build_slack_payload(level, title, text, project, run, step)
    elif _is_discord_url(url):
        payload = _build_discord_payload(level, title, text, project, run, step)
    else:
        payload = _build_generic_payload(
            level, title, text, project, run, step, timestamp
        )

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}
    )
    try:
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        logger.warning(f"Failed to send webhook to {url}: {e}")
