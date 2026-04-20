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
    if summary.get("status"):
        output.append(f"Status: {summary['status']}")
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


def format_snapshot(snapshot: dict[str, list[dict]]) -> str:
    """Format a metrics snapshot in human-readable format."""
    if not snapshot:
        return "No metrics found in the specified range."

    output = []
    for metric_name, values in sorted(snapshot.items()):
        output.append(f"\n{metric_name}:")
        output.append("  Step | Timestamp | Value")
        output.append("  " + "-" * 48)
        for v in values:
            step = v.get("step", "N/A")
            ts = v.get("timestamp", "N/A")
            val = v.get("value", "N/A")
            output.append(f"  {step} | {ts} | {val}")

    return "\n".join(output)


def format_alerts(alerts: list[dict]) -> str:
    """Format alerts in human-readable format."""
    if not alerts:
        return "No alerts found."

    output = [f"Found {len(alerts)} alert(s):\n"]
    output.append("Timestamp | Run | Level | Title | Text | Step")
    output.append("-" * 80)

    for a in alerts:
        ts = a.get("timestamp", "N/A")
        run = a.get("run", "N/A")
        level = a.get("level", "N/A").upper()
        title = a.get("title", "")
        text = a.get("text", "") or ""
        step = a.get("step", "N/A")
        output.append(f"{ts} | {run} | {level} | {title} | {text} | {step}")

    return "\n".join(output)


def format_best(
    project: str,
    metric: str,
    minimize: bool,
    mode: str,
    ranking: list[dict],
) -> str:
    direction = "minimize" if minimize else "maximize"
    output = [f"Project: {project}"]
    output.append(f"Metric: {metric} ({direction}, mode={mode})")
    output.append(f"Best run: {ranking[0]['run']} = {ranking[0]['value']}")
    output.append(f"\nRanking ({len(ranking)} runs):")
    output.append(f"  {'#':<4} {'Run':<30} {'Value':<15} {'Step':<10}")
    output.append("  " + "-" * 60)
    for i, r in enumerate(ranking, 1):
        output.append(
            f"  {i:<4} {r['run']:<30} {r['value']:<15} {r.get('step', 'N/A'):<10}"
        )
    return "\n".join(output)


def format_compare(
    project: str,
    metric_names: list[str],
    comparison: list[dict],
) -> str:
    output = [f"Project: {project}"]
    output.append(
        f"Comparing {len(comparison)} runs across {len(metric_names)} metrics\n"
    )

    header = f"  {'Run':<25} {'Status':<10}"
    for m in metric_names:
        header += f" {m:<15}"
    output.append(header)
    output.append("  " + "-" * (35 + 15 * len(metric_names)))

    for entry in comparison:
        line = f"  {entry['run']:<25} {(entry.get('status') or '?'):<10}"
        for m in metric_names:
            val = entry["metrics"].get(m)
            if val is not None:
                line += f" {val:<15.4f}" if isinstance(val, float) else f" {val!s:<15}"
            else:
                line += f" {'N/A':<15}"
        output.append(line)
    return "\n".join(output)


def format_summary(summary: dict) -> str:
    output = [f"Project: {summary['project']}"]
    output.append(f"Total runs: {summary['num_runs']}")
    output.append(f"Total alerts: {summary['total_alerts']}")

    if summary.get("metric"):
        output.append(f"Primary metric: {summary['metric']}")

    output.append("\nRuns:")
    for r in summary["runs"]:
        status = r.get("status") or "?"
        line = f"  {r['run']} [{status}] - {r['num_logs']} logs, last_step={r.get('last_step', 'N/A')}"
        if summary.get("metric") and r.get("metric_value") is not None:
            line += f", {summary['metric']}={r['metric_value']}"
        output.append(line)

        if r.get("config"):
            cfg_str = ", ".join(f"{k}={v}" for k, v in r["config"].items())
            output.append(f"    config: {cfg_str}")

    return "\n".join(output)


def error_exit(message: str, code: int = 1) -> None:
    """Print error message and exit."""
    print(f"Error: {message}", file=sys.stderr)
    sys.exit(code)
