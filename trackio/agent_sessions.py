"""Agent session serialization for the Hugging Face Hub's trace viewer.

The Hub renders `.jsonl` agent sessions in a dedicated trace viewer, for both
Datasets and Storage Buckets. This module is the single place Trackio produces
that format: the logbook's attached agent sessions and the `traces` table both
serialize through it.

Trackio emits **Pi's session format** (version 3), which the Hub supports
natively. The Hub also documents a Session Trace Simple Format (STS), but as of
this writing files written to that spec are not rendered by the viewer — a
controlled test (same bucket, same folder, one variable) showed a Codex-native
and a Pi-format session rendering while a spec-compliant STS session displayed
as raw JSONL, and none of the public datasets tagged `format:agent-traces` use
STS. Pi's format is also the better fit: `id`/`parentId`, token `usage`, `cost`,
and `isError` all have native homes, where STS had none.

A session file is a header line followed by one entry per line:

    {"type":"session","version":3,"id":"...","timestamp":"...","cwd":"..."}
    {"type":"message","id":"...","parentId":null,"timestamp":"...",
     "message":{"role":"user","content":[{"type":"text","text":"..."}]}}

Entries chain through `parentId`. Message content is a list of typed blocks
(`text`, `thinking`, `toolCall`); tool results are their own message with
`role: "toolResult"`, a `toolCallId`, a `toolName`, and an optional `isError`.

Format reference:
https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/session-format.md
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HARNESS = "trackio"
SESSION_VERSION = 3
SESSION_NAME_MAX_CHARS = 120

# Formats the Hub renders without conversion.
HUB_NATIVE_PROVIDERS = {"Codex", "Claude Code", "Pi"}

# Pi roles. Trackio's OpenAI-style `system` maps onto `developer`, which is what
# the sessions that render in the viewer use.
ROLE_BY_OPENAI_ROLE = {
    "system": "developer",
    "developer": "developer",
    "user": "user",
    "assistant": "assistant",
}

_NUMERIC_RE = re.compile(r"\d+(?:\.\d+)?")
_UNSAFE_ID_RE = re.compile(r"[^a-zA-Z0-9._-]+")


def parse_time(value: str | int | float | None) -> datetime | None:
    """Parse an ISO-8601 string or an epoch number (seconds or milliseconds)."""
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)) or (
        isinstance(value, str) and _NUMERIC_RE.fullmatch(value)
    ):
        numeric = float(value)
        if numeric > 10_000_000_000:
            numeric /= 1000
        try:
            return datetime.fromtimestamp(numeric, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def iso_z(value: str | int | float | None) -> str | None:
    """An ISO-8601 UTC timestamp with the `Z` suffix Pi sessions use."""
    parsed = parse_time(value)
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return (
        parsed.astimezone(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def entry_id(*parts: Any) -> str:
    """A stable 8-character entry id, matching the width Pi sessions use."""
    seed = ":".join(str(part) for part in parts)
    return hashlib.sha1(seed.encode("utf-8")).hexdigest()[:8]


def safe_id(value: str) -> str:
    """A filesystem- and bucket-safe form of an identifier."""
    cleaned = _UNSAFE_ID_RE.sub("-", str(value)).strip("-.")
    return cleaned[:100] or f"session-{uuid.uuid4().hex[:12]}"


def is_hub_native_jsonl(path: Path, provider: str | None = None) -> bool:
    """Whether the Hub's trace viewer renders this file without conversion.

    Only the harness-native formats qualify. A session header carrying a
    `harness` but no `version` is STS, which the viewer does not render, so it
    still needs converting.
    """
    if path.suffix.lower() != ".jsonl":
        return False
    if provider in HUB_NATIVE_PROVIDERS:
        return True
    try:
        with path.open(encoding="utf-8") as handle:
            first_line = next((line for line in handle if line.strip()), "")
        header = json.loads(first_line)
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(header, dict):
        return False
    if header.get("type") == "session" and header.get("version") is not None:
        return True
    # Codex sessions open with a `session_meta` envelope rather than `session`.
    return header.get("type") == "session_meta" and isinstance(
        header.get("payload"), dict
    )


def session_header(
    session_id: str,
    timestamp: str | None = None,
    name: str | None = None,
    cwd: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    header: dict[str, Any] = {
        "type": "session",
        "version": SESSION_VERSION,
        "id": str(session_id),
        "timestamp": iso_z(timestamp) or iso_z(datetime.now(timezone.utc)),
        "cwd": cwd or "/",
        "harness": HARNESS,
    }
    if name:
        header["name"] = name
    header.update({key: value for key, value in extra.items() if value is not None})
    return header


def dumps(records: list[dict[str, Any]]) -> str:
    return (
        "\n".join(json.dumps(record, ensure_ascii=False) for record in records) + "\n"
    )


def write_session(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dumps(records), encoding="utf-8")


def content_text(value: Any) -> str:
    """Flatten an OpenAI-style `content` value to text.

    Content may be a plain string, a list of typed blocks, or a serialized
    Trackio media object. Non-text blocks keep a readable placeholder rather
    than being dropped, so the viewer shows that something was there.
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = [content_text(item) for item in value]
        return "\n".join(part for part in parts if part)
    if isinstance(value, dict):
        media_type = value.get("_type")
        if isinstance(media_type, str) and media_type.startswith("trackio."):
            label = media_type.split(".", 1)[1]
            caption = value.get("caption") or value.get("file_path") or ""
            return f"[{label}{': ' + str(caption) if caption else ''}]"
        for key in ("text", "content", "output", "value"):
            if isinstance(value.get(key), str):
                return value[key]
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def text_block(text: str) -> dict[str, Any]:
    return {"type": "text", "text": text}


def thinking_block(text: str) -> dict[str, Any]:
    return {"type": "thinking", "thinking": text}


def tool_call_block(call_id: str, name: str, arguments: Any) -> dict[str, Any]:
    """A `toolCall` block. Unlike STS, `arguments` stays a real object."""
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except json.JSONDecodeError:
            arguments = {"input": arguments}
    if not isinstance(arguments, dict):
        arguments = {} if arguments is None else {"input": arguments}
    return {
        "type": "toolCall",
        "id": str(call_id),
        "name": str(name or "tool"),
        "arguments": arguments,
    }


class _Chain:
    """Accumulates entries, chaining each to the one before via `parentId`."""

    def __init__(self, session_id: str, default_timestamp: str | None):
        self.session_id = session_id
        self.default_timestamp = default_timestamp
        self.records: list[dict[str, Any]] = []
        self._parent: str | None = None

    def add(self, entry: dict[str, Any], timestamp: str | None = None) -> str:
        entry["parentId"] = self._parent
        entry["timestamp"] = iso_z(timestamp) or self.default_timestamp
        self._parent = entry["id"]
        self.records.append(entry)
        return entry["id"]

    def message(
        self, index: Any, message: dict[str, Any], timestamp: str | None = None
    ) -> str:
        return self.add(
            {
                "type": "message",
                "id": entry_id(self.session_id, "msg", index),
                "message": message,
            },
            timestamp,
        )


def span_usage(span: dict[str, Any]) -> dict[str, Any] | None:
    """Pi's `usage` block from a Trackio span's `usage` and `cost_usd`."""
    usage = span.get("usage") or {}
    raw_input = usage.get("input_tokens", usage.get("prompt_tokens"))
    raw_output = usage.get("output_tokens", usage.get("completion_tokens"))
    cost = span.get("cost_usd")
    if raw_input is None and raw_output is None and cost is None:
        return None
    try:
        input_tokens = int(raw_input or 0)
        output_tokens = int(raw_output or 0)
    except (TypeError, ValueError):
        input_tokens = output_tokens = 0
    total = usage.get("total_tokens") or (input_tokens + output_tokens)
    block: dict[str, Any] = {
        "input": input_tokens,
        "output": output_tokens,
        "cacheRead": int(usage.get("cache_read_input_tokens") or 0),
        "cacheWrite": int(usage.get("cache_creation_input_tokens") or 0),
        "totalTokens": total,
    }
    if cost is not None:
        try:
            block["cost"] = {
                "input": 0,
                "output": 0,
                "cacheRead": 0,
                "cacheWrite": 0,
                "total": float(cost),
            }
        except (TypeError, ValueError):
            pass
    return block


def _span_is_error(span: dict[str, Any]) -> bool:
    status = str(span.get("status") or "").lower()
    return status in {"error", "failed"} or bool(span.get("error"))


def _message_is_error(message: dict[str, Any]) -> bool:
    if message.get("is_error") is True or message.get("isError") is True:
        return True
    if message.get("error"):
        return True
    return str(message.get("status") or "").lower() in {"error", "failed"}


def _generation_output_text(span: dict[str, Any]) -> str:
    output = span.get("output")
    if isinstance(output, dict):
        for key in ("text", "content", "message", "output"):
            if output.get(key) is not None:
                return content_text(output[key])
    return content_text(output)


def _span_sort_key(indexed_span: tuple[int, dict[str, Any]]) -> tuple[float, int]:
    index, span = indexed_span
    started = parse_time(span.get("start_time") or span.get("startTime"))
    return (started.timestamp() if started else float("inf"), index)


def _ordered_spans(spans: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
    indexed = [
        (index, span)
        for index, span in enumerate(spans)
        if str(span.get("kind") or "").lower() == kind
    ]
    return [span for _, span in sorted(indexed, key=_span_sort_key)]


def _session_name(records: list[dict[str, Any]], fallback: str) -> str:
    """Title for the session: the request, when there is one."""
    for wanted_role in ("user", None):
        for record in records:
            message = record.get("message") or {}
            role = str(message.get("role") or "")
            if wanted_role is not None and role != wanted_role:
                continue
            text = " ".join(content_text(message.get("content")).split())
            if text:
                return text[:SESSION_NAME_MAX_CHARS]
    return fallback


def _messages_to_entries(
    chain: _Chain,
    messages: list[dict[str, Any]],
    generations: list[dict[str, Any]],
    tool_spans: list[dict[str, Any]],
) -> None:
    """Emit message entries, enriched with what the spans know.

    Spans supply what the message layer cannot: token usage and cost on the
    generation that produced each assistant turn, and failure status on a tool
    result. Tool call ids and span ids come from different namespaces, so a
    result is matched to its span by call id first and by order second.
    """
    tool_names: dict[str, str] = {}
    tool_span_by_id = {str(span.get("id")): span for span in tool_spans}
    remaining_tool_spans = list(tool_spans)
    generation_index = 0

    for index, message in enumerate(messages):
        role = str(message.get("role") or "assistant").lower()
        timestamp = message.get("timestamp") or message.get("created_at")

        if role == "tool":
            call_id = str(
                message.get("tool_call_id")
                or message.get("toolCallId")
                or f"call-{index}"
            )
            span = tool_span_by_id.get(call_id)
            if span is None and remaining_tool_spans:
                span = remaining_tool_spans[0]
            if span is not None and span in remaining_tool_spans:
                remaining_tool_spans.remove(span)
            result: dict[str, Any] = {
                "role": "toolResult",
                "toolCallId": call_id,
                "toolName": tool_names.get(call_id)
                or str((span or {}).get("name") or "tool"),
                "content": [text_block(content_text(message.get("content")))],
            }
            if _message_is_error(message) or (
                span is not None and _span_is_error(span)
            ):
                result["isError"] = True
            chain.message(index, result, timestamp)
            continue

        blocks: list[dict[str, Any]] = []
        reasoning = (
            message.get("reasoning_content")
            or message.get("reasoningContent")
            or message.get("reasoning")
        )
        if reasoning:
            blocks.append(thinking_block(content_text(reasoning)))
        text = content_text(message.get("content"))
        if text:
            blocks.append(text_block(text))

        calls = list(message.get("tool_calls") or message.get("toolCalls") or [])
        if message.get("function_call"):
            calls.append({"function": message["function_call"]})
        for call_index, call in enumerate(calls):
            if not isinstance(call, dict):
                continue
            function = (
                call.get("function") if isinstance(call.get("function"), dict) else call
            )
            call_id = str(call.get("id") or f"call-{index}-{call_index}")
            name = str(function.get("name") or "tool")
            tool_names[call_id] = name
            blocks.append(tool_call_block(call_id, name, function.get("arguments")))

        entry_message: dict[str, Any] = {
            "role": ROLE_BY_OPENAI_ROLE.get(role, "assistant"),
            "content": blocks,
        }
        if entry_message["role"] == "assistant":
            # Pair the Nth assistant turn with the Nth generation span rather
            # than repeating one span's totals on every turn, which would make
            # the viewer double-count tokens and cost.
            if generation_index < len(generations):
                usage = span_usage(generations[generation_index])
                if usage:
                    entry_message["usage"] = usage
                generation_index += 1
        chain.message(index, entry_message, timestamp)


def _spans_to_entries(
    chain: _Chain, spans: list[dict[str, Any]], generations: list[dict[str, Any]]
) -> None:
    """Emit entries for a trace that carries spans but no messages."""
    ordered = sorted(
        ((index, span) for index, span in enumerate(spans) if isinstance(span, dict)),
        key=_span_sort_key,
    )
    for index, span in ordered:
        kind = str(span.get("kind") or "span").lower()
        timestamp = span.get("start_time") or span.get("startTime")
        if kind == "generation":
            message: dict[str, Any] = {
                "role": "assistant",
                "content": [text_block(_generation_output_text(span))],
            }
            usage = span_usage(span)
            if usage:
                message["usage"] = usage
            chain.message(f"span-{index}", message, timestamp)
        elif kind == "tool":
            call_id = str(span.get("id") or f"span-tool-{index}")
            name = str(span.get("name") or "tool")
            chain.message(
                f"span-{index}-call",
                {
                    "role": "assistant",
                    "content": [tool_call_block(call_id, name, span.get("input"))],
                },
                timestamp,
            )
            result: dict[str, Any] = {
                "role": "toolResult",
                "toolCallId": call_id,
                "toolName": name,
                "content": [
                    text_block(content_text(span.get("error") or span.get("output")))
                ],
            }
            if _span_is_error(span):
                result["isError"] = True
            chain.message(f"span-{index}-result", result, timestamp)
        else:
            chain.message(
                f"span-{index}",
                {
                    "role": "developer",
                    "content": [text_block(str(span.get("name") or kind))],
                },
                timestamp,
            )


def trace_to_records(
    trace: dict[str, Any], project: str | None = None
) -> list[dict[str, Any]]:
    """Serialize one Trackio trace row into a Pi-format agent session.

    The entries form the linear conversation the viewer renders, enriched from
    the spans with model, token usage, cost, and failure status. The full span
    tree — hierarchy, `duration_ms`, per-span `metadata`, and the `kind` of
    non-tool spans — stays in SQLite, which remains authoritative for every
    Trackio reader.
    """
    messages = [m for m in (trace.get("messages") or []) if isinstance(m, dict)]
    spans = [s for s in (trace.get("spans") or []) if isinstance(s, dict)]
    generations = _ordered_spans(spans, "generation")
    tool_spans = _ordered_spans(spans, "tool")

    trace_id = str(trace.get("id") or uuid.uuid4().hex)
    timestamp = iso_z(trace.get("timestamp"))
    chain = _Chain(trace_id, timestamp)

    model = next(
        (str(span["model"]) for span in generations if span.get("model")),
        None,
    )
    if model:
        chain.add(
            {
                "type": "model_change",
                "id": entry_id(trace_id, "model"),
                "modelId": model,
            },
            trace.get("timestamp"),
        )

    if messages:
        _messages_to_entries(chain, messages, generations, tool_spans)
    else:
        _spans_to_entries(chain, spans, generations)

    header = session_header(
        trace_id,
        timestamp=trace.get("timestamp"),
        name=_session_name(chain.records, trace_id),
        cwd=f"/{project}" if project else "/",
        trackio={
            "project": project,
            "run_id": trace.get("run_id"),
            "run_name": trace.get("run_name"),
            "step": trace.get("step"),
            "key": trace.get("key"),
            "trace_index": trace.get("trace_index"),
            "metadata": trace.get("metadata") or {},
        },
    )
    return [header, *chain.records]


def trace_session_filename(trace_id: Any) -> str:
    return f"{safe_id(str(trace_id))}.jsonl"
