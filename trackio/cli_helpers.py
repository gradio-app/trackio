import json
import sys
from typing import Any

from trackio import references


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


def format_artifacts(artifacts: list[dict], project: str | None = None) -> str:
    """Format a project's artifacts in human-readable format."""
    if not artifacts:
        return "No artifacts found."

    title = f"Artifacts in '{project}'" if project else "Artifacts"
    output = [f"{title}:"]
    for art in artifacts:
        latest = art.get("latest_version")
        version = f"v{latest}" if latest is not None else "(no versions)"
        aliases = art.get("aliases") or []
        alias_str = f" [{', '.join(aliases)}]" if aliases else ""
        output.append(
            f"  - {art['name']} ({art.get('type', '?')}) "
            f"latest={version}{alias_str} "
            f"versions={art.get('num_versions', 0)}"
        )
        if art.get("description"):
            output.append(f"      {art['description']}")
    return "\n".join(output)


def format_artifact(record: dict) -> str:
    """Format a single resolved artifact version in human-readable format."""
    lines = [
        f"Artifact: {record['name']} (v{record['version']})",
        f"  type:        {record.get('type')}",
    ]
    if record.get("description"):
        lines.append(f"  description: {record['description']}")
    aliases = record.get("aliases") or []
    if aliases:
        lines.append(f"  aliases:     {', '.join(aliases)}")
    if record.get("metadata"):
        lines.append(f"  metadata:    {record['metadata']}")
    lines.append(f"  size:        {record.get('size_bytes')} bytes")
    lines.append(f"  digest:      {record.get('manifest_digest')}")
    manifest = record.get("manifest") or []
    lines.append(f"  files ({len(manifest)}):")
    for entry in manifest:
        if references.is_reference_entry(entry):
            lines.append(f"    - {entry['path']} -> {entry['ref']} (reference)")
        else:
            lines.append(f"    - {entry['path']} ({entry['size']} bytes)")
    return "\n".join(lines)


def format_registry_collections(registry: str, collections: list[dict]) -> str:
    """Format the collections in an artifact registry."""
    if not collections:
        return f"No collections found in registry '{registry}'."

    output = [f"Collections in registry '{registry}':"]
    for collection in collections:
        latest = collection.get("latest_version")
        latest_display = f"v{latest}" if latest is not None else "(empty)"
        output.append(
            f"  - {collection['name']} ({collection['type']}) "
            f"latest={latest_display} versions={collection['num_links']}"
        )
        if collection.get("description"):
            output.append(f"      {collection['description']}")
    return "\n".join(output)


def format_registry_collection(registry: str, collection: dict) -> str:
    """Format one registry collection and its linked versions."""
    output = [
        f"Collection: {registry}/{collection['name']}",
        f"  type:        {collection['type']}",
        f"  versions:    {collection['num_links']}",
    ]
    if collection.get("description"):
        output.append(f"  description: {collection['description']}")
    if not collection["links"]:
        output.append("  No linked versions.")
        return "\n".join(output)

    output.append("  Linked versions:")
    for link in collection["links"]:
        aliases = link.get("aliases") or []
        alias_display = f" [{', '.join(aliases)}]" if aliases else ""
        output.append(
            f"    - v{link['collection_version']} -> "
            f"{link['source_project']}/{link['source_artifact']}"
            f":v{link['source_version']}{alias_display}"
        )
    return "\n".join(output)


def format_registry_events(events: list[dict]) -> str:
    """Format a registry audit log."""
    if not events:
        return "No registry events found."
    return "\n".join(
        f"{event['ts']} | {event['kind']} | "
        f"{json.dumps(event['payload'], sort_keys=True)}"
        for event in events
    )


def format_spaces(spaces: list[dict]) -> str:
    """Format HF Spaces in human-readable format."""
    if not spaces:
        return "No Trackio Spaces found."

    output = ["Trackio Spaces:"]
    for space in spaces:
        visibility = "private" if space.get("private") else "public"
        output.append(f"  - {space['id']} ({visibility})")
        if space.get("url"):
            output.append(f"    {space['url']}")

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


def format_sweeps(sweeps: list[dict], project: str | None = None) -> str:
    """Format a project's sweeps in human-readable format."""
    if not sweeps:
        return "No sweeps found."

    title = f"Sweeps in '{project}'" if project else "Sweeps"
    output = [f"{title}:"]
    for s in sweeps:
        name = f" · {s['name']}" if s.get("name") else ""
        best = (
            f" best={s['best_metric_value']:g}"
            if s.get("best_metric_value") is not None
            else ""
        )
        output.append(
            f"  - {s['sweep_id']}{name} ({s['method']}, {s['state']}) "
            f"trials={s.get('num_trials', 0)}{best}"
        )
    return "\n".join(output)


def format_sweep_summary(sweep: dict) -> str:
    """Format a single sweep in human-readable format."""
    lines = [
        f"Sweep: {sweep['sweep_id']}",
    ]
    if sweep.get("name"):
        lines.append(f"  name:    {sweep['name']}")
    lines.append(f"  method:  {sweep['method']}")
    state = sweep["state"]
    if sweep.get("finish_reason"):
        state += f" ({sweep['finish_reason']})"
    lines.append(f"  state:   {state}")
    if sweep.get("metric_name"):
        lines.append(
            f"  metric:  {sweep['metric_name']} ({sweep.get('metric_goal', 'minimize')})"
        )
    lines.append(f"  created: {sweep.get('created_at')}")
    counts = sweep.get("trial_counts") or {}
    counts_str = (
        ", ".join(f"{state}={count}" for state, count in sorted(counts.items()))
        or "none"
    )
    lines.append(f"  trials:  {sweep.get('num_trials', 0)} ({counts_str})")
    if sweep.get("best_metric_value") is not None:
        lines.append(
            f"  best:    {sweep['best_metric_value']:g} "
            f"(run_id={sweep.get('best_run_id')})"
        )
    return "\n".join(lines)


def format_sweep_trials(trials: list[dict]) -> str:
    """Format sweep trials in human-readable format."""
    if not trials:
        return "No trials found."

    output = [f"Found {len(trials)} trial(s):\n"]
    output.append("Trial | State | Metric | Run ID | Params")
    output.append("-" * 80)
    for t in trials:
        metric = "" if t.get("metric_value") is None else f"{t['metric_value']:g}"
        run_id = t.get("run_id") or ""
        params = json.dumps(t.get("params", {}), sort_keys=True)
        output.append(
            f"{t['trial_id']} | {t['state']} | {metric} | {run_id} | {params}"
        )
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
