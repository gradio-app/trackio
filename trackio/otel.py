from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
    ExportTraceServiceRequest,
)
from opentelemetry.proto.trace.v1.trace_pb2 import Span

from trackio.sqlite_storage import SQLiteStorage

DEFAULT_OTEL_PROJECT = "otel-traces"
DEFAULT_OTEL_RUN = "otel"

_INPUT_MESSAGE_RE = re.compile(r"^llm\.input_messages\.(\d+)\.message\.(role|content)$")
_OUTPUT_MESSAGE_RE = re.compile(
    r"^llm\.output_messages\.(\d+)\.message\.(role|content)$"
)


def _bytes_to_hex(value: bytes) -> str:
    return value.hex()


def _timestamp_from_unix_nano(value: int) -> str:
    if not value:
        return datetime.now(timezone.utc).isoformat()
    return datetime.fromtimestamp(value / 1_000_000_000, timezone.utc).isoformat()


def _value_to_python(value: Any) -> Any:
    field = value.WhichOneof("value")
    if field is None:
        return None
    raw = getattr(value, field)
    if field == "array_value":
        return [_value_to_python(item) for item in raw.values]
    if field == "kvlist_value":
        return {item.key: _value_to_python(item.value) for item in raw.values}
    if field == "bytes_value":
        return _bytes_to_hex(raw)
    return raw


def _attributes_to_dict(attributes: Any) -> dict[str, Any]:
    return {attr.key: _value_to_python(attr.value) for attr in attributes}


def _jsonish(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    stripped = value.strip()
    if not stripped:
        return value
    if stripped[0] not in '[{"':
        return value
    try:
        return json.loads(stripped)
    except Exception:
        return value


def _content_from_value(value: Any) -> str:
    parsed = _jsonish(value)
    if isinstance(parsed, str):
        return parsed
    return json.dumps(parsed, ensure_ascii=False, default=str)


def _messages_from_indexed_attrs(
    attrs: dict[str, Any],
    pattern: re.Pattern[str],
    default_role: str,
) -> list[dict[str, Any]]:
    grouped: dict[int, dict[str, Any]] = {}
    for key, value in attrs.items():
        match = pattern.match(key)
        if not match:
            continue
        index = int(match.group(1))
        field = match.group(2)
        grouped.setdefault(index, {})[field] = value
    return [
        {
            "role": str(parts.get("role") or default_role),
            "content": _content_from_value(parts.get("content", "")),
        }
        for _, parts in sorted(grouped.items())
        if "content" in parts
    ]


def _message_content_from_mapping(value: dict[str, Any], fallback: str | None) -> str:
    if isinstance(value.get("task"), str):
        return value["task"]
    if isinstance(value.get("query"), str):
        return value["query"]
    if isinstance(value.get("prompt"), str):
        return value["prompt"]
    if isinstance(value.get("input"), str):
        return value["input"]
    if isinstance(value.get("args"), list) and value["args"]:
        return "\n".join(_content_from_value(item) for item in value["args"])
    if isinstance(value.get("kwargs"), dict) and value["kwargs"]:
        return json.dumps(value["kwargs"], ensure_ascii=False, default=str)
    if "memory_step" in value and fallback:
        return fallback
    return json.dumps(value, ensure_ascii=False, default=str)


def _messages_from_value(
    value: Any,
    role: str,
    fallback: str | None = None,
) -> list[dict[str, Any]]:
    parsed = _jsonish(value)
    if isinstance(parsed, list) and all(isinstance(item, dict) for item in parsed):
        messages = []
        for item in parsed:
            if "content" not in item and "message" not in item:
                continue
            messages.append(
                {
                    "role": str(item.get("role") or role),
                    "content": _content_from_value(
                        item.get("content", item.get("message", ""))
                    ),
                }
            )
        if messages:
            return messages
    if isinstance(parsed, dict):
        if "messages" in parsed:
            return _messages_from_value(parsed["messages"], role, fallback=fallback)
        return [
            {
                "role": role,
                "content": _message_content_from_mapping(parsed, fallback),
            }
        ]
    return [{"role": role, "content": _content_from_value(value)}]


def _span_messages(
    attrs: dict[str, Any], span_name: str | None = None
) -> list[dict[str, Any]]:
    messages = []
    messages.extend(_messages_from_indexed_attrs(attrs, _INPUT_MESSAGE_RE, "user"))
    if not messages and "input.value" in attrs:
        messages.extend(
            _messages_from_value(attrs["input.value"], "user", fallback=span_name)
        )
    messages.extend(
        _messages_from_indexed_attrs(attrs, _OUTPUT_MESSAGE_RE, "assistant")
    )
    if not any(message.get("role") == "assistant" for message in messages):
        if "output.value" in attrs:
            messages.extend(
                _messages_from_value(
                    attrs["output.value"],
                    "assistant",
                    fallback=span_name,
                )
            )
    return messages


def _span_kind_name(kind: int) -> str:
    try:
        return Span.SpanKind.Name(kind).replace("SPAN_KIND_", "").lower()
    except Exception:
        return str(kind)


def _span_status(span: Span) -> dict[str, Any]:
    status = {
        "code": span.status.code,
        "message": span.status.message,
    }
    try:
        status["name"] = span.status.StatusCode.Name(span.status.code)
    except Exception:
        pass
    return status


def _span_to_trace_payload(
    span: Span,
    resource_attrs: dict[str, Any],
    scope_attrs: dict[str, Any],
) -> tuple[str, dict[str, Any], str]:
    attrs = _attributes_to_dict(span.attributes)
    trace_id = _bytes_to_hex(span.trace_id)
    span_id = _bytes_to_hex(span.span_id)
    messages = _span_messages(attrs, span_name=span.name)
    if not messages:
        messages = [{"role": "system", "content": span.name or "OpenTelemetry span"}]

    metadata = {
        "source": "opentelemetry",
        "trace_id": trace_id,
        "span_id": span_id,
        "parent_span_id": _bytes_to_hex(span.parent_span_id)
        if span.parent_span_id
        else None,
        "name": span.name,
        "kind": _span_kind_name(span.kind),
        "status": _span_status(span),
        "start_time": _timestamp_from_unix_nano(span.start_time_unix_nano),
        "end_time": _timestamp_from_unix_nano(span.end_time_unix_nano),
        "attributes": attrs,
        "resource": resource_attrs,
        "scope": scope_attrs,
        "events": [
            {
                "name": event.name,
                "timestamp": _timestamp_from_unix_nano(event.time_unix_nano),
                "attributes": _attributes_to_dict(event.attributes),
            }
            for event in span.events
        ],
    }
    payload = {
        "_type": "trackio.trace",
        "messages": messages,
        "metadata": metadata,
    }
    return trace_id, payload, _timestamp_from_unix_nano(span.start_time_unix_nano)


def ingest_otlp_trace_bytes(
    body: bytes,
    *,
    project: str | None = None,
    run: str | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    request = ExportTraceServiceRequest()
    request.ParseFromString(body)

    logs_by_run: dict[tuple[str, str, str | None], dict[str, list[Any]]] = {}
    span_count = 0

    for resource_spans in request.resource_spans:
        resource_attrs = _attributes_to_dict(resource_spans.resource.attributes)
        resolved_project = (
            project
            or resource_attrs.get("trackio.project")
            or resource_attrs.get("project.name")
            or DEFAULT_OTEL_PROJECT
        )
        resolved_run = (
            run
            or resource_attrs.get("trackio.run")
            or resource_attrs.get("service.name")
            or DEFAULT_OTEL_RUN
        )
        resolved_run_id = (
            run_id
            or resource_attrs.get("trackio.run_id")
            or resource_attrs.get("service.instance.id")
        )

        for scope_spans in resource_spans.scope_spans:
            scope_attrs = {
                "name": scope_spans.scope.name,
                "version": scope_spans.scope.version,
                "attributes": _attributes_to_dict(scope_spans.scope.attributes),
            }
            for span in scope_spans.spans:
                trace_id, payload, timestamp = _span_to_trace_payload(
                    span,
                    resource_attrs=resource_attrs,
                    scope_attrs=scope_attrs,
                )
                key = (
                    str(resolved_project),
                    str(resolved_run),
                    str(resolved_run_id) if resolved_run_id is not None else None,
                )
                if key not in logs_by_run:
                    logs_by_run[key] = {
                        "metrics": [],
                        "steps": [],
                        "timestamps": [],
                        "log_ids": [],
                    }
                group = logs_by_run[key]
                step = len(group["metrics"])
                group["metrics"].append({"otel/span": payload})
                group["steps"].append(step)
                group["timestamps"].append(timestamp)
                group["log_ids"].append(
                    f"otel:{trace_id}:{_bytes_to_hex(span.span_id)}"
                )
                span_count += 1

    for (project_name, run_name, run_id_value), group in logs_by_run.items():
        SQLiteStorage.bulk_log(
            project=project_name,
            run=run_name,
            run_id=run_id_value,
            metrics_list=group["metrics"],
            steps=group["steps"],
            timestamps=group["timestamps"],
            log_ids=group["log_ids"],
            config={"_Source": "opentelemetry"},
        )

    return {
        "accepted_spans": span_count,
        "projects": sorted({key[0] for key in logs_by_run}),
        "runs": sorted({key[1] for key in logs_by_run}),
    }
