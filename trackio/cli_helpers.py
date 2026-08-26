import json
import re
import sys
from datetime import datetime, timezone
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


def format_duration_ms(value: Any) -> str:
    """Render a millisecond duration the way the trace dashboard does."""
    if value is None or value == "":
        return "-"
    try:
        ms = float(value)
    except (TypeError, ValueError):
        return "-"
    if ms < 1000:
        return f"{round(ms)}ms"
    if ms < 60_000:
        return f"{ms / 1000:.2f}s" if ms < 10_000 else f"{ms / 1000:.1f}s"
    minutes = int(ms // 60_000)
    seconds = round((ms % 60_000) / 1000)
    return f"{minutes}m {seconds}s"


def format_cost_usd(value: Any) -> str:
    if value is None or value == "":
        return "-"
    try:
        cost = float(value)
    except (TypeError, ValueError):
        return "-"
    if cost == 0:
        return "$0"
    if cost < 0.0001:
        return "<$0.0001"
    if cost < 0.01:
        return f"${cost:.4f}"
    return f"${cost:.2f}"


_ISO_FRACTION_RE = re.compile(r"\.(\d+)")


def parse_span_timestamp(value: Any) -> datetime | None:
    """Parse a span timestamp, tolerating any number of fractional digits.

    `datetime.fromisoformat` accepts only 3 or 6 fractional digits before
    Python 3.11, and instrumentation commonly emits fewer (or a `Z` suffix),
    so those are normalized first. Naive timestamps are assumed to be UTC so
    that spans from mixed sources stay comparable.
    """
    if not value:
        return None
    text = str(value).strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    text = _ISO_FRACTION_RE.sub(
        lambda match: "." + (match.group(1) + "000000")[:6], text, count=1
    )
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _span_duration_ms(span: dict) -> float | None:
    explicit = span.get("duration_ms")
    if explicit is not None:
        try:
            return max(0.0, float(explicit))
        except (TypeError, ValueError):
            pass
    started = parse_span_timestamp(span.get("start_time"))
    ended = parse_span_timestamp(span.get("end_time"))
    if started is None or ended is None:
        return None
    return max(0.0, (ended - started).total_seconds() * 1000)


def _span_is_error(span: dict) -> bool:
    status = str(span.get("status") or "").lower()
    return status in {"error", "failed"} or bool(span.get("error"))


def trace_rollup(trace: dict) -> dict:
    """Latency, cost, token, and status totals for one trace."""
    spans = trace.get("spans") or []
    starts, ends, durations = [], [], []
    cost = 0.0
    has_cost = False
    input_tokens = output_tokens = 0
    has_usage = has_error = False

    for span in spans:
        if not isinstance(span, dict):
            continue
        for field, sink in (("start_time", starts), ("end_time", ends)):
            parsed = parse_span_timestamp(span.get(field))
            if parsed is not None:
                sink.append(parsed)
        duration = _span_duration_ms(span)
        if duration is not None:
            durations.append(duration)
        span_cost = span.get("cost_usd")
        if span_cost is not None:
            try:
                cost += float(span_cost)
                has_cost = True
            except (TypeError, ValueError):
                pass
        usage = span.get("usage") or {}
        for key, add in (("input_tokens", "in"), ("output_tokens", "out")):
            value = usage.get(key)
            if value is None:
                continue
            try:
                if add == "in":
                    input_tokens += int(value)
                else:
                    output_tokens += int(value)
                has_usage = True
            except (TypeError, ValueError):
                pass
        if _span_is_error(span):
            has_error = True

    metadata = trace.get("metadata") or {}
    if starts and ends:
        duration_ms = max(0.0, (max(ends) - min(starts)).total_seconds() * 1000)
    elif durations:
        duration_ms = max(durations)
    else:
        duration_ms = metadata.get("duration_ms") or metadata.get("latency_ms")

    all_success = bool(spans) and all(
        str(span.get("status") or "").lower() == "success"
        for span in spans
        if isinstance(span, dict)
    )
    metadata_status = metadata.get("status")
    status = (
        "error"
        if has_error
        else (
            metadata_status
            if isinstance(metadata_status, str) and metadata_status
            else ("success" if all_success else None)
        )
    )
    return {
        "duration_ms": duration_ms,
        "cost_usd": cost if has_cost else metadata.get("cost_usd"),
        "input_tokens": input_tokens if has_usage else None,
        "output_tokens": output_tokens if has_usage else None,
        "status": status,
        "span_count": len(spans),
    }


def short_trace_id(trace_id: Any) -> str:
    """Shorten a stored trace id for display, as the dashboard does.

    Stored ids are `run_id:log_id:key[:index]`; the `log_id` (plus the list
    index, when the key held several traces) identifies the trace on its own.
    """
    text = str(trace_id or "")
    parts = text.split(":")
    if len(parts) < 3:
        return text
    short = parts[1]
    last = parts[-1]
    if len(parts) >= 4 and last.lstrip("-").isdigit():
        return f"{short}:{last}"
    return short


def trace_id_matches(trace: dict, wanted: str) -> bool:
    stored = str(trace.get("id") or "")
    return wanted in (stored, short_trace_id(stored))


def _first_message_text(trace: dict, role: str) -> str:
    for message in trace.get("messages") or []:
        if not isinstance(message, dict) or message.get("role") != role:
            continue
        content = message.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and isinstance(part.get("text"), str):
                    return part["text"]
    return ""


def format_traces(traces: list[dict]) -> str:
    """Format a trace index in human-readable format."""
    if not traces:
        return "No traces found."

    output = [f"Found {len(traces)} trace(s):\n"]
    output.append("ID | Run | Step | Status | Latency | Cost | Ops | Request")
    output.append("-" * 100)
    for trace in traces:
        rollup = trace_rollup(trace)
        request = _first_message_text(trace, "user").replace("\n", " ")
        if len(request) > 48:
            request = request[:45] + "..."
        output.append(
            " | ".join(
                [
                    short_trace_id(trace.get("id")) or "-",
                    str(trace.get("run", "-")),
                    str(trace.get("step", "-")),
                    rollup["status"] or "-",
                    format_duration_ms(rollup["duration_ms"]),
                    format_cost_usd(rollup["cost_usd"]),
                    str(rollup["span_count"]),
                    request or "-",
                ]
            )
        )
    return "\n".join(output)


def _ordered_span_tree(spans: list[dict]) -> list[tuple[int, dict]]:
    """Depth-annotated spans, parents before children, siblings by start time."""
    normalized = [span for span in spans if isinstance(span, dict)]
    by_id: dict[str, dict] = {}
    for index, span in enumerate(normalized):
        span_id = str(span.get("id") or f"span-{index + 1}")
        by_id.setdefault(span_id, span)

    children: dict[int, list[dict]] = {}
    roots: list[dict] = []
    for span in normalized:
        parent_id = span.get("parent_id")
        parent = by_id.get(str(parent_id)) if parent_id else None
        if parent is None or parent is span:
            roots.append(span)
        else:
            children.setdefault(id(parent), []).append(span)

    def sort_key(span: dict) -> tuple:
        started = parse_span_timestamp(span.get("start_time"))
        return (
            0 if started else 1,
            started.timestamp() if started else 0.0,
            normalized.index(span),
        )

    rows: list[tuple[int, dict]] = []
    seen: set[int] = set()

    def walk(span: dict, depth: int) -> None:
        if id(span) in seen:
            return
        seen.add(id(span))
        rows.append((depth, span))
        for child in sorted(children.get(id(span), []), key=sort_key):
            walk(child, depth + 1)

    for root in sorted(roots, key=sort_key):
        walk(root, 0)
    for span in normalized:
        walk(span, 0)
    return rows


def format_trace(trace: dict) -> str:
    """Format a single trace, including its span tree, in human-readable format."""
    rollup = trace_rollup(trace)
    output = [f"Trace {short_trace_id(trace.get('id')) or '-'}"]
    output.append(f"  Full id:  {trace.get('id', '-')}")
    output.append(f"  Run:      {trace.get('run', '-')}")
    output.append(f"  Step:     {trace.get('step', '-')}")
    output.append(
        f"  Logged:   {trace.get('timestamp', '-')} (key: {trace.get('key', '-')})"
    )
    output.append(
        f"  Totals:   {rollup['status'] or 'no status'} | "
        f"{format_duration_ms(rollup['duration_ms'])} | "
        f"{format_cost_usd(rollup['cost_usd'])} | "
        f"{rollup['input_tokens'] if rollup['input_tokens'] is not None else '-'} in / "
        f"{rollup['output_tokens'] if rollup['output_tokens'] is not None else '-'} out tokens | "
        f"{rollup['span_count']} operation(s)"
    )
    metadata = trace.get("metadata") or {}
    if metadata:
        rendered = ", ".join(
            f"{key}={value}"
            for key, value in metadata.items()
            if not isinstance(value, (dict, list))
        )
        if rendered:
            output.append(f"  Metadata: {rendered}")

    spans = trace.get("spans") or []
    if spans:
        output.append("\nExecution:")
        for depth, span in _ordered_span_tree(spans):
            indent = "  " * (depth + 1)
            bits = [format_duration_ms(_span_duration_ms(span))]
            if span.get("model"):
                bits.append(str(span["model"]))
            usage = span.get("usage") or {}
            if (
                usage.get("input_tokens") is not None
                or usage.get("output_tokens") is not None
            ):
                bits.append(
                    f"{usage.get('input_tokens', 0)}->{usage.get('output_tokens', 0)} tok"
                )
            if span.get("cost_usd") is not None:
                bits.append(format_cost_usd(span.get("cost_usd")))
            marker = "ERROR " if _span_is_error(span) else ""
            output.append(
                f"{indent}{marker}{span.get('name', span.get('kind', 'span'))} "
                f"[{span.get('kind', 'span')}]  {'  '.join(bits)}"
            )
            error = span.get("error")
            if error:
                detail = error if isinstance(error, str) else json.dumps(error)
                output.append(f"{indent}  -> {detail[:160]}")
    else:
        output.append("\nExecution: no spans logged for this trace.")

    messages = trace.get("messages") or []
    if messages:
        output.append("\nConversation:")
        for message in messages:
            if not isinstance(message, dict):
                continue
            role = message.get("role", "message")
            content = message.get("content")
            if not isinstance(content, str):
                content = json.dumps(content) if content is not None else ""
            content = content.replace("\n", " ")
            if len(content) > 160:
                content = content[:157] + "..."
            output.append(f"  {role}: {content}")
    return "\n".join(output)


def format_trace_summary(result: dict[str, Any]) -> str:
    """Format the per-operation trace rollup in human-readable format."""
    rows = result.get("rows") or []
    if not rows:
        return "No trace spans found."
    columns = result.get("columns") or []
    return format_query_result(
        {"columns": columns, "rows": rows, "row_count": len(rows)}
    )
