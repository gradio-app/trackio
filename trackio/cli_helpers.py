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

    for a in alerts:
        ts = a.get("timestamp", "N/A")
        run = a.get("run", "N/A")
        level = (a.get("level") or "N/A").upper()
        title = a.get("title", "")
        text = a.get("text", "") or ""
        step = a.get("step", "N/A")
        line = f"[{level}] {title} | run={run} step={step} ts={ts}"
        if text:
            line += f"\n  {text}"
        data = a.get("data")
        if data:
            data_str = ", ".join(f"{k}={v}" for k, v in data.items())
            line += f"\n  data: {data_str}"
        output.append(line)

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

    run_w = max((len(e["run"]) for e in comparison), default=3)
    run_w = max(run_w, 3)
    status_w = 10

    col_ws = []
    for m in metric_names:
        vals = [e["metrics"].get(m) for e in comparison]
        val_w = max(
            (
                len(f"{v:.4f}" if isinstance(v, float) else str(v))
                for v in vals
                if v is not None
            ),
            default=3,
        )
        col_ws.append(max(len(m), val_w))

    header = f"  {'Run':<{run_w}} {'Status':<{status_w}}"
    for m, w in zip(metric_names, col_ws):
        header += f"  {m:<{w}}"
    output.append(header)
    sep_w = run_w + status_w + sum(w + 2 for w in col_ws) + 2
    output.append("  " + "-" * sep_w)

    for entry in comparison:
        line = f"  {entry['run']:<{run_w}} {(entry.get('status') or '?'):<{status_w}}"
        for m, w in zip(metric_names, col_ws):
            val = entry["metrics"].get(m)
            if val is not None:
                formatted = f"{val:.4f}" if isinstance(val, float) else str(val)
            else:
                formatted = "N/A"
            line += f"  {formatted:<{w}}"
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


def format_query_result(result: dict[str, Any]) -> str:
    """Format SQL query results in human-readable format."""
    columns = result.get("columns", [])
    rows = result.get("rows", [])
    row_count = result.get("row_count", 0)

    if not columns:
        return f"Query returned {row_count} row(s)."

    rendered_rows = []
    for row in rows:
        rendered_rows.append(
            [
                "" if row.get(column) is None else str(row.get(column))
                for column in columns
            ]
        )

    widths = []
    for idx, column in enumerate(columns):
        cell_width = max(
            (len(rendered_row[idx]) for rendered_row in rendered_rows), default=0
        )
        widths.append(max(len(column), cell_width))

    header = " | ".join(
        column.ljust(width) for column, width in zip(columns, widths, strict=False)
    )
    separator = "-+-".join("-" * width for width in widths)
    output = [f"Query returned {row_count} row(s).", header, separator]

    if not rendered_rows:
        output.append("(no rows)")
        return "\n".join(output)

    for rendered_row in rendered_rows:
        output.append(
            " | ".join(
                value.ljust(width)
                for value, width in zip(rendered_row, widths, strict=False)
            )
        )

    return "\n".join(output)


def error_exit(message: str, code: int = 1) -> None:
    """Print error message and exit."""
    print(f"Error: {message}", file=sys.stderr)
    sys.exit(code)
