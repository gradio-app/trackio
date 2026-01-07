import json
import sys
from typing import Any


def format_json(data: Any) -> str:
    """Format data as JSON."""
    return json.dumps(data, indent=2)


def format_list(items: list[str], title: str | None = None) -> str:
    """Format a list of items in human-readable format."""
    if not items:
        return f"No {title.lower() if title else 'items'} found."

    output = []
    if title:
        output.append(f"{title}:")

    for item in items:
        output.append(f"  - {item}")

    return "\n".join(output)


def format_project_summary(summary: dict) -> str:
    """Format project summary in human-readable format."""
    output = [f"Project: {summary['project']}"]
    output.append(f"Number of runs: {summary['num_runs']}")

    if summary["runs"]:
        output.append("\nRuns:")
        for run in summary["runs"]:
            output.append(f"  - {run}")
    else:
        output.append("\nNo runs found.")

    if summary.get("last_activity"):
        output.append(f"\nLast activity (max step): {summary['last_activity']}")

    return "\n".join(output)


def format_run_summary(summary: dict) -> str:
    """Format run summary in human-readable format."""
    output = [f"Project: {summary['project']}"]
    output.append(f"Run: {summary['run']}")
    output.append(f"Number of logs: {summary['num_logs']}")

    if summary.get("last_step") is not None:
        output.append(f"Last step: {summary['last_step']}")

    if summary.get("metrics"):
        output.append("\nMetrics:")
        for metric in summary["metrics"]:
            output.append(f"  - {metric}")
    else:
        output.append("\nNo metrics found.")

    config = summary.get("config")
    if config:
        output.append("\nConfig:")
        config_display = {k: v for k, v in config.items() if not k.startswith("_")}
        if config_display:
            for key, value in config_display.items():
                output.append(f"  {key}: {value}")
        else:
            output.append("  (no config)")
    else:
        output.append("\nConfig: (no config)")

    return "\n".join(output)


def format_metric_values(values: list[dict]) -> str:
    """Format metric values in human-readable format."""
    if not values:
        return "No metric values found."

    output = [f"Found {len(values)} value(s):\n"]
    output.append("Step | Timestamp | Value")
    output.append("-" * 50)

    for value in values:
        step = value.get("step", "N/A")
        timestamp = value.get("timestamp", "N/A")
        val = value.get("value", "N/A")
        output.append(f"{step} | {timestamp} | {val}")

    return "\n".join(output)


def format_system_metrics(metrics: list[dict]) -> str:
    """Format system metrics in human-readable format."""
    if not metrics:
        return "No system metrics found."

    output = [f"Found {len(metrics)} system metric entry/entries:\n"]

    for i, entry in enumerate(metrics):
        timestamp = entry.get("timestamp", "N/A")
        output.append(f"\nEntry {i + 1} (Timestamp: {timestamp}):")
        for key, value in entry.items():
            if key != "timestamp":
                output.append(f"  {key}: {value}")

    return "\n".join(output)


def format_system_metric_names(names: list[str]) -> str:
    """Format system metric names in human-readable format."""
    return format_list(names, "System Metrics")


def error_exit(message: str, code: int = 1) -> None:
    """Print error message and exit."""
    print(f"Error: {message}", file=sys.stderr)
    sys.exit(code)
