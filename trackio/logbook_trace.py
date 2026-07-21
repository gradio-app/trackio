from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

TRACE_SCHEMA_VERSION = 1
TRACE_CHUNK_SIZE = 200
TRACE_REGISTRY_FILE = "trace_sources.json"
TRACE_STATE_DIR = "traces"
WORKSPACE_BASELINE_DIR = "workspace_baselines"
WORKSPACE_SYNC_STATE_FILE = "workspace_bucket_state.json"
WORKSPACE_BUCKET_PREFIX = "workspace"
TRACE_DATASET_EXPORT_DIR = "trace_dataset"
IMPORTED_WORKSPACE_FILE = "imported_workspace.json"
MAX_WORKSPACE_ENTRIES = 50_000

WORKSPACE_TYPE_BY_EXT = {
    ".pt": "model",
    ".pth": "model",
    ".ckpt": "model",
    ".safetensors": "model",
    ".gguf": "model",
    ".onnx": "model",
    ".pkl": "model",
    ".joblib": "model",
    ".h5": "model",
    ".tflite": "model",
    ".pb": "model",
    ".npz": "dataset",
    ".npy": "dataset",
    ".parquet": "dataset",
    ".csv": "dataset",
    ".tsv": "dataset",
    ".arrow": "dataset",
    ".jsonl": "dataset",
    ".feather": "dataset",
    ".msgpack": "dataset",
}
WORKSPACE_SKIP_DIRS = {
    "__pycache__",
    "node_modules",
    "venv",
    "env",
    ".venv",
    "site-packages",
}


class TraceCaptureError(Exception):
    pass


# ---- secret scrubbing (applied to attached traces by default) ----

REDACTION_PLACEHOLDER = "«redacted»"

# High-confidence standalone secret tokens: the whole match is replaced.
_SCRUB_TOKEN_PATTERNS = (
    re.compile(r"hf_[A-Za-z0-9]{20,}"),  # Hugging Face user access token
    re.compile(r"AKIA[0-9A-Z]{16}"),  # AWS access key id
    re.compile(r"sk-(?:proj-)?[A-Za-z0-9_-]{20,}"),  # OpenAI-style secret key
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),  # GitHub token
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),  # Slack token
)

# ``Authorization: Bearer <token>`` / bare ``Bearer <token>``: redact the token.
_SCRUB_BEARER_PATTERN = re.compile(r"(?i)(bearer\s+)([A-Za-z0-9._~+/=-]{8,})")

# ``key = value`` / ``"key": "value"`` shaped secrets: redact only the value so
# the surrounding structure (and any JSON quoting) stays intact.
_SCRUB_KV_PATTERNS = (
    re.compile(
        r"(?i)\b(HF_TOKEN|HUGGING_FACE_HUB_TOKEN|HUGGINGFACEHUB_API_TOKEN"
        r"|HUGGINGFACE_TOKEN)\b(\s*[=:]\s*\"?)([^\s\"'&,}]+)"
    ),
    re.compile(
        r"(?i)\b(aws_secret_access_key)\b(\s*[=:]\s*\"?)([A-Za-z0-9/+=]{16,})"
    ),
    re.compile(
        r"(?i)\b(api[_-]?key|apikey|access[_-]?token|auth[_-]?token|token"
        r"|password|passwd|secret)\b(\"?\s*[=:]\s*\"?)([^\s\"'&,}]{4,})"
    ),
)


def scrub_text(text: str) -> tuple[str, int]:
    """Redact common secrets from ``text``.

    Returns the scrubbed text and the number of redactions performed. Patterns
    are line-safe (no multi-line spans) so this composes with line streaming.
    """
    count = 0

    def _full(match: "re.Match[str]") -> str:
        nonlocal count
        count += 1
        return REDACTION_PLACEHOLDER

    def _bearer(match: "re.Match[str]") -> str:
        nonlocal count
        if match.group(2) == REDACTION_PLACEHOLDER:
            return match.group(0)
        count += 1
        return match.group(1) + REDACTION_PLACEHOLDER

    def _value(match: "re.Match[str]") -> str:
        nonlocal count
        if match.group(3) == REDACTION_PLACEHOLDER:
            return match.group(0)
        count += 1
        return match.group(1) + match.group(2) + REDACTION_PLACEHOLDER

    for pattern in _SCRUB_TOKEN_PATTERNS:
        text = pattern.sub(_full, text)
    text = _SCRUB_BEARER_PATTERN.sub(_bearer, text)
    for pattern in _SCRUB_KV_PATTERNS:
        text = pattern.sub(_value, text)
    return text, count


def scrub_file(source: Path, dest: Path) -> int:
    """Stream ``source`` line-by-line into ``dest``, scrubbing secrets.

    Returns the total number of redactions. Streaming keeps memory bounded for
    large JSONL transcripts.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    with (
        source.open("r", encoding="utf-8", errors="surrogatepass") as reader,
        dest.open("w", encoding="utf-8", errors="surrogatepass") as writer,
    ):
        for line in reader:
            scrubbed, count = scrub_text(line)
            total += count
            writer.write(scrubbed)
    return total


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(value, indent=2, ensure_ascii=False)
    try:
        if path.read_text(encoding="utf-8") == rendered:
            return
    except OSError:
        pass
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(rendered)
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def _registry_path(proj: Path) -> Path:
    return proj / TRACE_REGISTRY_FILE


def _load_registry(proj: Path) -> dict:
    data = _read_json(_registry_path(proj), {})
    if not isinstance(data, dict):
        data = {}
    sessions = data.get("sessions")
    if not isinstance(sessions, list):
        sessions = []
    return {"schema_version": TRACE_SCHEMA_VERSION, "sessions": sessions}


def _save_registry(proj: Path, data: dict) -> None:
    _write_json(_registry_path(proj), data)


def _safe_id(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9._-]+", "-", value).strip("-.")
    return cleaned[:100] or f"session-{uuid.uuid4().hex[:12]}"


def _records(path: Path) -> list[dict]:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise TraceCaptureError(
            f"Trace file must be UTF-8 JSON or JSONL: {path}"
        ) from exc
    stripped = text.strip()
    if not stripped:
        return []
    try:
        document = json.loads(stripped)
    except json.JSONDecodeError:
        document = None
    if isinstance(document, list):
        return [item for item in document if isinstance(item, dict)]
    if isinstance(document, dict):
        for key in ("events", "messages", "items", "records"):
            nested = document.get(key)
            if isinstance(nested, list):
                return [item for item in nested if isinstance(item, dict)]
        return [document]
    if stripped.startswith("["):
        try:
            value = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise TraceCaptureError(f"Could not parse trace JSON: {path}") from exc
        if not isinstance(value, list):
            raise TraceCaptureError(
                "Trace JSON must contain an array of event objects."
            )
        return [item for item in value if isinstance(item, dict)]

    records = []
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            # An actively-written JSONL file may end with a partial record.
            if index == len(lines) - 1:
                continue
            records.append(
                {
                    "type": "trackio_parse_error",
                    "line": index + 1,
                    "message": "Malformed JSONL record",
                }
            )
            continue
        if isinstance(value, dict):
            records.append(value)
    return records


def _timestamp(record: dict) -> str | None:
    value = record.get("timestamp")
    if value is None and isinstance(record.get("payload"), dict):
        value = record["payload"].get("timestamp")
    if value is None and isinstance(record.get("message"), dict):
        value = record["message"].get("timestamp")
    return str(value) if value else None


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, list):
        parts = [_text(item) for item in value]
        return "\n".join(part for part in parts if part)
    if isinstance(value, dict):
        for key in ("text", "message", "content", "output"):
            if key in value:
                rendered = _text(value[key])
                if rendered:
                    return rendered
        return json.dumps(value, indent=2, ensure_ascii=False)
    return str(value)


def _json_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, indent=2, ensure_ascii=False)
    except TypeError:
        return str(value)


def _detect_provider(records: list[dict]) -> str:
    for record in records[:100]:
        if record.get("type") == "session_meta" and isinstance(
            record.get("payload"), dict
        ):
            return "codex"
        if (
            record.get("type") == "session"
            and record.get("id")
            and record.get("version") is not None
        ):
            return "pi"
        if "sessionId" in record or (
            record.get("type") in {"assistant", "user"}
            and isinstance(record.get("message"), dict)
        ):
            return "claude"
    return "generic"


def _session_id(records: list[dict], provider: str, source: Path) -> str:
    for record in records:
        if provider == "codex" and record.get("type") == "session_meta":
            payload = record.get("payload") or {}
            value = payload.get("id") or payload.get("session_id")
            if value:
                return _safe_id(str(value))
        if provider == "claude" and record.get("sessionId"):
            return _safe_id(str(record["sessionId"]))
        if provider == "pi" and record.get("type") == "session" and record.get("id"):
            return _safe_id(str(record["id"]))
        value = record.get("session_id") or record.get("sessionId")
        if value:
            return _safe_id(str(value))
    return _safe_id(source.stem)


def _content_blocks(content: Any) -> list[dict]:
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    if isinstance(content, dict):
        return [content]
    if isinstance(content, list):
        return [item for item in content if isinstance(item, dict)]
    return []


def _event(
    kind: str,
    *,
    timestamp: str | None,
    turn: int | None,
    text: str = "",
    title: str = "",
    **extra: Any,
) -> dict:
    value = {
        "kind": kind,
        "timestamp": timestamp,
        "turn": turn,
        "text": text,
        "title": title,
    }
    value.update({key: item for key, item in extra.items() if item not in (None, "")})
    return value


def _normalize_codex(records: list[dict]) -> tuple[dict, list[dict]]:
    meta: dict[str, Any] = {"provider": "Codex"}
    events: list[dict] = []
    turn = 0
    for record in records:
        outer_type = record.get("type")
        payload = record.get("payload")
        if not isinstance(payload, dict):
            payload = {}
        ts = _timestamp(record)
        if outer_type == "session_meta":
            meta.update(
                {
                    "id": payload.get("id") or payload.get("session_id"),
                    "started_at": ts or payload.get("timestamp"),
                    "cwd": payload.get("cwd"),
                }
            )
            continue
        if outer_type == "turn_context":
            meta["model"] = payload.get("model") or meta.get("model")
            continue
        payload_type = payload.get("type")
        if outer_type == "event_msg" and payload_type == "task_started":
            turn += 1
            continue
        if outer_type != "response_item":
            if outer_type == "event_msg" and payload_type in {
                "turn_aborted",
                "task_complete",
            }:
                events.append(
                    _event(
                        "status",
                        timestamp=ts,
                        turn=turn or None,
                        title=str(payload_type).replace("_", " ").title(),
                        status=payload_type,
                    )
                )
            continue
        if payload_type == "message":
            role = str(payload.get("role") or "")
            if role not in {"user", "assistant"}:
                continue
            text = "\n".join(
                part
                for part in (
                    _text(block.get("text") or block.get("content"))
                    for block in _content_blocks(payload.get("content"))
                    if block.get("type") not in {"input_image", "image"}
                )
                if part
            )
            if text:
                events.append(
                    _event(
                        role,
                        timestamp=ts,
                        turn=turn or None,
                        text=text,
                        title=role.title(),
                        phase=payload.get("phase"),
                    )
                )
        elif payload_type == "reasoning":
            summary = _text(payload.get("summary"))
            if summary:
                events.append(
                    _event(
                        "reasoning",
                        timestamp=ts,
                        turn=turn or None,
                        text=summary,
                        title="Thought",
                    )
                )
        elif payload_type in {"custom_tool_call", "function_call"}:
            tool_name = payload.get("name") or "Tool"
            tool_input = payload.get("input", payload.get("arguments"))
            events.append(
                _event(
                    "tool_call",
                    timestamp=ts,
                    turn=turn or None,
                    title=str(tool_name),
                    tool_name=tool_name,
                    call_id=payload.get("call_id") or payload.get("id"),
                    input=_json_text(tool_input),
                    status=payload.get("status"),
                )
            )
        elif payload_type in {"custom_tool_call_output", "function_call_output"}:
            events.append(
                _event(
                    "tool_result",
                    timestamp=ts,
                    turn=turn or None,
                    title="Output",
                    call_id=payload.get("call_id"),
                    output=_json_text(payload.get("output")),
                )
            )
    return meta, events


def _normalize_claude(records: list[dict]) -> tuple[dict, list[dict]]:
    meta: dict[str, Any] = {"provider": "Claude Code"}
    events: list[dict] = []
    turn = 0
    for record in records:
        ts = _timestamp(record)
        if record.get("sessionId") and not meta.get("id"):
            meta["id"] = record.get("sessionId")
        if record.get("cwd") and not meta.get("cwd"):
            meta["cwd"] = record.get("cwd")
        message = record.get("message")
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or record.get("type") or "")
        if message.get("model"):
            meta["model"] = message.get("model")
        blocks = _content_blocks(message.get("content"))
        has_user_text = role == "user" and any(
            block.get("type") == "text" for block in blocks
        )
        if has_user_text:
            turn += 1
        depth = 1 if record.get("isSidechain") else 0
        for block in blocks:
            block_type = block.get("type")
            if block_type == "text" and role in {"user", "assistant"}:
                text = _text(block.get("text"))
                if text:
                    events.append(
                        _event(
                            role,
                            timestamp=ts,
                            turn=turn or None,
                            text=text,
                            title=role.title(),
                            depth=depth,
                        )
                    )
            elif block_type in {"thinking", "reasoning"}:
                text = _text(block.get("thinking") or block.get("text"))
                if text:
                    events.append(
                        _event(
                            "reasoning",
                            timestamp=ts,
                            turn=turn or None,
                            text=text,
                            title="Thought",
                            depth=depth,
                        )
                    )
            elif block_type == "tool_use":
                events.append(
                    _event(
                        "tool_call",
                        timestamp=ts,
                        turn=turn or None,
                        title=str(block.get("name") or "Tool"),
                        tool_name=block.get("name"),
                        call_id=block.get("id"),
                        input=_json_text(block.get("input")),
                        depth=depth,
                    )
                )
            elif block_type == "tool_result":
                events.append(
                    _event(
                        "tool_result",
                        timestamp=ts,
                        turn=turn or None,
                        title="Output",
                        call_id=block.get("tool_use_id"),
                        output=_text(block.get("content")),
                        status="error" if block.get("is_error") else "success",
                        depth=depth,
                    )
                )
    return meta, events


def _normalize_generic(records: list[dict]) -> tuple[dict, list[dict]]:
    meta: dict[str, Any] = {"provider": "Agent"}
    events: list[dict] = []
    turn = 0
    for record in records:
        ts = _timestamp(record)
        depth = record.get("depth", record.get("subagent_depth", 0))
        role = str(record.get("role") or "").lower()
        event_type = str(record.get("type") or record.get("event") or "event")
        if event_type == "session":
            meta.update(
                {
                    "id": record.get("id"),
                    "provider": (
                        "Pi"
                        if record.get("version") is not None
                        else record.get("harness") or meta["provider"]
                    ),
                    "started_at": ts or record.get("started_at"),
                    "cwd": record.get("cwd"),
                }
            )
            continue
        if event_type in {"model_change", "model"}:
            meta["model"] = (
                record.get("model")
                or record.get("modelId")
                or record.get("model_id")
                or meta.get("model")
            )
            continue
        message = record.get("message")
        if isinstance(message, dict):
            message_role = str(message.get("role") or role).lower()
            if message.get("model"):
                meta["model"] = message["model"]
            blocks = _content_blocks(message.get("content"))
            has_user_text = message_role == "user" and any(
                block.get("type", "text") == "text" for block in blocks
            )
            if has_user_text:
                turn += 1
            reasoning = _text(
                message.get("reasoningContent") or message.get("reasoning_content")
            )
            if reasoning:
                events.append(
                    _event(
                        "reasoning",
                        timestamp=ts,
                        turn=turn or None,
                        text=reasoning,
                        title="Thought",
                        depth=depth,
                    )
                )
            for block in blocks:
                block_type = str(block.get("type") or "text")
                if block_type == "text" and message_role in {
                    "user",
                    "assistant",
                    "system",
                    "developer",
                }:
                    text = _text(block.get("text") or block.get("content"))
                    if text:
                        kind = (
                            message_role
                            if message_role in {"user", "assistant"}
                            else "status"
                        )
                        events.append(
                            _event(
                                kind,
                                timestamp=ts,
                                turn=turn or None,
                                text=text,
                                title=message_role.title(),
                                depth=depth,
                            )
                        )
                elif block_type in {"thinking", "reasoning"}:
                    text = _text(block.get("thinking") or block.get("text"))
                    if text:
                        events.append(
                            _event(
                                "reasoning",
                                timestamp=ts,
                                turn=turn or None,
                                text=text,
                                title="Thought",
                                depth=depth,
                            )
                        )
                elif block_type in {"toolCall", "tool_call", "tool_use"}:
                    events.append(
                        _event(
                            "tool_call",
                            timestamp=ts,
                            turn=turn or None,
                            title=str(block.get("name") or "Tool"),
                            tool_name=block.get("name"),
                            call_id=block.get("id") or block.get("toolCallId"),
                            input=_json_text(
                                block.get("arguments", block.get("input"))
                            ),
                            depth=depth,
                        )
                    )
                elif block_type in {"toolResult", "tool_result"}:
                    events.append(
                        _event(
                            "tool_result",
                            timestamp=ts,
                            turn=turn or None,
                            title="Output",
                            call_id=block.get("toolCallId") or block.get("tool_use_id"),
                            output=_text(block.get("content") or block.get("output")),
                            status="error" if block.get("isError") else "success",
                            depth=depth,
                        )
                    )
            for call in message.get("toolCalls") or []:
                if not isinstance(call, dict):
                    continue
                function = call.get("function") or {}
                events.append(
                    _event(
                        "tool_call",
                        timestamp=ts,
                        turn=turn or None,
                        title=str(function.get("name") or call.get("name") or "Tool"),
                        tool_name=function.get("name") or call.get("name"),
                        call_id=call.get("id"),
                        input=_json_text(
                            function.get("arguments", call.get("arguments"))
                        ),
                        depth=depth,
                    )
                )
            if message_role in {"tool", "toolresult", "tool_result"}:
                events.append(
                    _event(
                        "tool_result",
                        timestamp=ts,
                        turn=turn or None,
                        title="Output",
                        call_id=message.get("toolCallId")
                        or message.get("tool_call_id"),
                        output=_text(message.get("content")),
                        status="error" if message.get("isError") else "success",
                        depth=depth,
                    )
                )
            continue
        if role == "user" or event_type in {"user", "user_message"}:
            turn += 1
            value = _text(record.get("content", record.get("message")))
            if value:
                events.append(
                    _event(
                        "user",
                        timestamp=ts,
                        turn=turn,
                        text=value,
                        title="User",
                        depth=depth,
                    )
                )
            continue
        if role == "assistant" or event_type in {"assistant", "assistant_message"}:
            value = _text(record.get("content", record.get("message")))
            if value:
                events.append(
                    _event(
                        "assistant",
                        timestamp=ts,
                        turn=turn or None,
                        text=value,
                        title="Assistant",
                        depth=depth,
                    )
                )
            continue
        if event_type in {"thought", "thinking", "reasoning"}:
            value = _text(record.get("content", record.get("message")))
            if value:
                events.append(
                    _event(
                        "reasoning",
                        timestamp=ts,
                        turn=turn or None,
                        text=value,
                        title="Thought",
                        depth=depth,
                    )
                )
            continue
        tool_name = record.get("tool_name") or record.get("name")
        if tool_name and any(key in record for key in ("input", "arguments")):
            events.append(
                _event(
                    "tool_call",
                    timestamp=ts,
                    turn=turn or None,
                    title=str(tool_name),
                    tool_name=tool_name,
                    call_id=record.get("call_id") or record.get("id"),
                    input=_json_text(record.get("input", record.get("arguments"))),
                    depth=depth,
                )
            )
            continue
        if any(key in record for key in ("output", "result", "error")):
            value = record.get("output", record.get("result", record.get("error")))
            events.append(
                _event(
                    "tool_result" if record.get("call_id") else "status",
                    timestamp=ts,
                    turn=turn or None,
                    title="Output" if record.get("call_id") else event_type,
                    call_id=record.get("call_id"),
                    output=_json_text(value),
                    status="error" if "error" in record else record.get("status"),
                    depth=depth,
                )
            )
            continue
        events.append(
            _event(
                "status",
                timestamp=ts,
                turn=turn or None,
                title=event_type.replace("_", " ").title(),
                depth=depth,
            )
        )
    return meta, events


def _parse_time(value: str | int | float | None) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)) or (
        isinstance(value, str) and re.fullmatch(r"\d+(?:\.\d+)?", value)
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


def normalize_trace(path: Path) -> dict:
    records = _records(path)
    provider = _detect_provider(records)
    if provider == "codex":
        meta, events = _normalize_codex(records)
    elif provider == "claude":
        meta, events = _normalize_claude(records)
    else:
        meta, events = _normalize_generic(records)
        if provider == "pi":
            meta["provider"] = "Pi"

    session_id = _session_id(records, provider, path)
    timestamps = [_parse_time(event.get("timestamp")) for event in events]
    timestamps = [value for value in timestamps if value is not None]
    started = _parse_time(meta.get("started_at")) or (
        timestamps[0] if timestamps else None
    )
    ended = timestamps[-1] if timestamps else started
    for sequence, event in enumerate(events, start=1):
        event["id"] = f"event-{sequence}"
        event["sequence"] = sequence
        current = _parse_time(event.get("timestamp"))
        if started and current:
            event["elapsed_ms"] = max(
                0, int((current - started).total_seconds() * 1000)
            )
    duration_ms = (
        max(0, int((ended - started).total_seconds() * 1000))
        if started and ended
        else None
    )
    return {
        "schema_version": TRACE_SCHEMA_VERSION,
        "id": session_id,
        "provider": meta.get("provider") or provider.title(),
        "model": meta.get("model"),
        "started_at": started.isoformat() if started else None,
        "ended_at": ended.isoformat() if ended else None,
        "duration_ms": duration_ms,
        "event_count": len(events),
        "turn_count": max((event.get("turn") or 0 for event in events), default=0),
        "events": events,
    }


def _workspace_snapshot(root: Path) -> dict[str, dict]:
    snapshot: dict[str, dict] = {}
    scanned = 0
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = [
            name
            for name in dirnames
            if not name.startswith(".") and name not in WORKSPACE_SKIP_DIRS
        ]
        scanned += len(dirnames) + len(filenames)
        if scanned > MAX_WORKSPACE_ENTRIES:
            raise TraceCaptureError(
                f"Workspace scan exceeded {MAX_WORKSPACE_ENTRIES:,} entries."
            )
        for name in filenames:
            kind = WORKSPACE_TYPE_BY_EXT.get(Path(name).suffix.lower())
            if not kind:
                continue
            full = Path(dirpath) / name
            try:
                if full.is_symlink() or not full.is_file():
                    continue
                stat = full.stat()
                relative = full.relative_to(root).as_posix()
            except OSError:
                continue
            snapshot[relative] = {
                "size": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
                "modified_at": datetime.fromtimestamp(
                    stat.st_mtime, tz=timezone.utc
                ).isoformat(),
                "type": kind,
            }
    return snapshot


def _baseline_path(proj: Path, session_id: str) -> Path:
    return proj / WORKSPACE_BASELINE_DIR / f"{_safe_id(session_id)}.json"


def attach_trace(
    proj: Path,
    source_path: str | Path,
    title: str | None = None,
    scrub: bool = True,
) -> dict:
    source = Path(source_path).expanduser().resolve()
    if not source.is_file():
        raise TraceCaptureError(f"Trace file not found: {source}")
    normalized = normalize_trace(source)
    session_id = normalized["id"]
    registry = _load_registry(proj)
    existing = next(
        (
            item
            for item in registry["sessions"]
            if Path(item.get("source_path", "")) == source
        ),
        None,
    )
    if existing:
        session_id = existing["id"]
        existing["title"] = title or existing.get("title") or source.stem
        existing["provider"] = normalized["provider"]
        existing["scrub"] = scrub
        # Force a re-scrub/re-normalize even if the source is unchanged, so an
        # explicit re-attach with a different --scrub choice takes effect.
        _invalidate_trace_cache(proj, session_id)
    else:
        used = {item.get("id") for item in registry["sessions"]}
        base_id = session_id
        suffix = 2
        while session_id in used:
            session_id = _safe_id(f"{base_id[:90]}-{suffix}")
            suffix += 1
        entry = {
            "id": session_id,
            "title": title or source.stem,
            "source_path": str(source),
            "provider": normalized["provider"],
            "attached_at": _now_iso(),
            "scrub": scrub,
        }
        registry["sessions"].append(entry)
        baseline = {
            "schema_version": 1,
            "session_id": session_id,
            "root": str(proj.parent.resolve()),
            "files": _workspace_snapshot(proj.parent.resolve()),
        }
        _write_json(_baseline_path(proj, session_id), baseline)
    _save_registry(proj, registry)
    return refresh_trace(proj, session_id)


def _trace_output_dir(proj: Path, session_id: str) -> Path:
    return proj / "logbook" / "traces" / _safe_id(session_id)


def _invalidate_trace_cache(proj: Path, session_id: str) -> None:
    """Drop the cached source fingerprint so the next refresh recomputes."""
    index_path = _trace_output_dir(proj, session_id) / "index.json"
    index = _read_json(index_path, {})
    if isinstance(index, dict) and (
        "source_size" in index or "source_mtime_ns" in index
    ):
        index.pop("source_size", None)
        index.pop("source_mtime_ns", None)
        _write_json(index_path, index)


def _write_normalized_trace(
    proj: Path,
    entry: dict,
    normalized: dict,
    source_stat: os.stat_result | None = None,
) -> dict:
    session_id = entry["id"]
    normalized["id"] = session_id
    normalized["title"] = entry.get("title") or session_id
    normalized["attached_at"] = entry.get("attached_at")
    if source_stat is not None:
        normalized["source_size"] = source_stat.st_size
        normalized["source_mtime_ns"] = source_stat.st_mtime_ns
    output_dir = _trace_output_dir(proj, session_id)
    output_dir.mkdir(parents=True, exist_ok=True)
    chunks = []
    events = normalized.pop("events")
    for offset in range(0, len(events), TRACE_CHUNK_SIZE):
        part = events[offset : offset + TRACE_CHUNK_SIZE]
        filename = f"events-{offset // TRACE_CHUNK_SIZE:04d}.json"
        _write_json(output_dir / filename, {"events": part})
        chunks.append(
            {
                "file": f"traces/{_safe_id(session_id)}/{filename}",
                "count": len(part),
                "first_sequence": part[0]["sequence"] if part else None,
                "last_sequence": part[-1]["sequence"] if part else None,
            }
        )
    keep = {Path(chunk["file"]).name for chunk in chunks}
    for stale in output_dir.glob("events-*.json"):
        if stale.name not in keep:
            stale.unlink()
    index = {**normalized, "chunks": chunks, "source_available": True}
    _write_json(output_dir / "index.json", index)
    return index


def refresh_trace(proj: Path, session_id: str) -> dict:
    registry = _load_registry(proj)
    entry = next(
        (item for item in registry["sessions"] if item.get("id") == session_id), None
    )
    if not entry:
        raise TraceCaptureError(f"No attached trace with id '{session_id}'.")
    source = Path(entry["source_path"])
    output_dir = _trace_output_dir(proj, session_id)
    if not source.is_file():
        index = _read_json(output_dir / "index.json", {})
        if index:
            index["source_available"] = False
            _write_json(output_dir / "index.json", index)
            return index
        raise TraceCaptureError(f"Attached trace source is missing: {source}")
    raw_dir = proj / TRACE_STATE_DIR / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_suffix = (
        source.suffix if source.suffix.lower() in {".json", ".jsonl"} else ".jsonl"
    )
    raw_path = raw_dir / f"{_safe_id(session_id)}{raw_suffix}"
    scrub = bool(entry.get("scrub", True))
    existing = _read_json(output_dir / "index.json", {})
    source_stat = source.stat()
    if (
        existing
        and raw_path.is_file()
        and existing.get("source_size") == source_stat.st_size
        and existing.get("source_mtime_ns") == source_stat.st_mtime_ns
    ):
        return existing
    # The stored raw copy is what gets exported to the published trace dataset,
    # so scrubbing here guarantees secrets never leave in either the normalized
    # view or the raw JSONL.
    if scrub:
        redactions = scrub_file(source, raw_path)
        normalized = normalize_trace(raw_path)
    else:
        shutil.copy2(source, raw_path)
        normalized = normalize_trace(source)
        redactions = 0
    normalized["scrub"] = scrub
    normalized["scrub_redactions"] = redactions
    return _write_normalized_trace(proj, entry, normalized, source_stat=source_stat)


def remove_trace(proj: Path, session_id: str) -> None:
    registry = _load_registry(proj)
    before = len(registry["sessions"])
    registry["sessions"] = [
        item for item in registry["sessions"] if item.get("id") != session_id
    ]
    if len(registry["sessions"]) == before:
        raise TraceCaptureError(f"No attached trace with id '{session_id}'.")
    _save_registry(proj, registry)
    baseline = _baseline_path(proj, session_id)
    if baseline.exists():
        baseline.unlink()
    raw_dir = proj / TRACE_STATE_DIR / "raw"
    for raw in raw_dir.glob(f"{_safe_id(session_id)}.*"):
        raw.unlink()
    output_dir = _trace_output_dir(proj, session_id)
    if output_dir.exists():
        shutil.rmtree(output_dir)
    imported = _read_json(proj / IMPORTED_WORKSPACE_FILE, {})
    if isinstance(imported, dict):
        for item in imported.get("files") or []:
            if isinstance(item.get("sessions"), list):
                item["sessions"] = [
                    value for value in item["sessions"] if value != session_id
                ]
        imported["files"] = [
            item
            for item in imported.get("files") or []
            if item.get("sessions") or "sessions" not in item
        ]
        _write_json(proj / IMPORTED_WORKSPACE_FILE, imported)


def adopt_published_state(proj: Path) -> None:
    """Adopt published Trace/Workspace views when cloning a logbook Space."""
    traces = _read_json(proj / "logbook" / "traces" / "index.json", {})
    registry = _load_registry(proj)
    known = {item.get("id") for item in registry["sessions"]}
    current_snapshot: dict[str, dict] | None = None
    for session in traces.get("sessions") or []:
        session_id = session.get("id")
        if not session_id or session_id in known:
            continue
        registry["sessions"].append(
            {
                "id": session_id,
                "title": session.get("title") or session_id,
                "source_path": "",
                "provider": session.get("provider") or "Agent",
                "attached_at": session.get("attached_at") or _now_iso(),
                "imported": True,
            }
        )
        if current_snapshot is None:
            current_snapshot = _workspace_snapshot(proj.parent.resolve())
        _write_json(
            _baseline_path(proj, session_id),
            {
                "schema_version": 1,
                "session_id": session_id,
                "root": str(proj.parent.resolve()),
                "files": current_snapshot,
            },
        )
        known.add(session_id)
    _save_registry(proj, registry)

    workspace = _read_json(proj / "logbook" / "workspace.json", {})
    if isinstance(workspace, dict) and workspace.get("files"):
        imported_files = []
        for item in workspace["files"]:
            if not isinstance(item, dict) or not item.get("path"):
                continue
            imported_files.append(
                {
                    **item,
                    "local_url": None,
                    "imported": True,
                    "bucket_id": workspace.get("bucket_id"),
                }
            )
        _write_json(
            proj / IMPORTED_WORKSPACE_FILE,
            {**workspace, "files": imported_files},
        )


def _trace_summary(index: dict) -> dict:
    return {
        key: index.get(key)
        for key in (
            "id",
            "title",
            "provider",
            "model",
            "started_at",
            "ended_at",
            "duration_ms",
            "event_count",
            "turn_count",
            "source_available",
            "attached_at",
        )
    } | {"index_file": f"traces/{_safe_id(str(index.get('id', '')))}/index.json"}


def _workspace_manifest(
    proj: Path,
    registry: dict,
    bucket_id: str | None,
    hub_refs: list[dict] | None = None,
) -> dict:
    root = proj.parent.resolve()
    entries = registry["sessions"]
    imported = _read_json(proj / IMPORTED_WORKSPACE_FILE, {})
    imported_files = {
        item["path"]: {**item, "local_url": None, "imported": True}
        for item in imported.get("files") or []
        if isinstance(item, dict) and item.get("path")
    }
    files_by_path = dict(imported_files)
    metadata = _read_json(proj / "metadata.json", {})
    for tracked in metadata.get("local_path_artifacts") or []:
        try:
            source = Path(tracked["abs_path"]).resolve()
            relative = source.relative_to(root).as_posix()
            stat = source.stat()
        except (KeyError, OSError, ValueError):
            continue
        kind = tracked.get("artifact_type") or WORKSPACE_TYPE_BY_EXT.get(
            source.suffix.lower()
        )
        if not kind or not source.is_file():
            continue
        encoded = quote(relative, safe="/")
        bucket_path = f"{WORKSPACE_BUCKET_PREFIX}/{relative}"
        files_by_path[relative] = {
            "path": relative,
            "name": source.name,
            "type": kind,
            "size": stat.st_size,
            "modified_at": datetime.fromtimestamp(
                stat.st_mtime, tz=timezone.utc
            ).isoformat(),
            "sessions": [],
            "captured_by": "logbook-run",
            "local_url": f"/__trackio_workspace__/{encoded}",
            "bucket_url": (
                f"https://huggingface.co/buckets/{bucket_id}#"
                f"{WORKSPACE_BUCKET_PREFIX}/{encoded}"
                if bucket_id
                else None
            ),
            "download_url": (
                f"https://huggingface.co/buckets/{bucket_id}/resolve/"
                f"{quote(bucket_path, safe='')}"
                if bucket_id
                else None
            ),
        }
    current = _workspace_snapshot(root) if entries else {}
    trace_sources = {
        Path(entry["source_path"]).resolve()
        for entry in entries
        if entry.get("source_path")
    }
    baselines = {
        entry["id"]: _read_json(_baseline_path(proj, entry["id"]), {}).get("files", {})
        for entry in entries
    }
    for relative, info in sorted(current.items()):
        if (root / relative).resolve() in trace_sources:
            continue
        touched = []
        for entry in entries:
            old = baselines[entry["id"]].get(relative)
            if old is None or (old.get("size"), old.get("mtime_ns")) != (
                info["size"],
                info["mtime_ns"],
            ):
                touched.append(entry["id"])
        if not touched:
            continue
        encoded = quote(relative, safe="/")
        bucket_path = f"{WORKSPACE_BUCKET_PREFIX}/{relative}"
        files_by_path[relative] = {
            "path": relative,
            "name": Path(relative).name,
            "type": info["type"],
            "size": info["size"],
            "modified_at": info["modified_at"],
            "sessions": touched,
            "local_url": f"/__trackio_workspace__/{encoded}",
            "bucket_url": (
                f"https://huggingface.co/buckets/{bucket_id}#"
                f"{WORKSPACE_BUCKET_PREFIX}/{encoded}"
                if bucket_id
                else None
            ),
            "download_url": (
                f"https://huggingface.co/buckets/{bucket_id}/resolve/"
                f"{quote(bucket_path, safe='')}"
                if bucket_id
                else None
            ),
        }
    files = [files_by_path[path] for path in sorted(files_by_path)]
    manifest = {
        "schema_version": 1,
        "generated_at": _now_iso(),
        "root_name": root.name,
        "bucket_id": bucket_id or imported.get("bucket_id"),
        "file_count": len(files),
        "total_size": sum(item["size"] for item in files),
        "files": files,
        "hub_refs": hub_refs or [],
    }
    previous = _read_json(proj / "logbook" / "workspace.json", {})
    comparable = {
        key: value for key, value in manifest.items() if key != "generated_at"
    }
    previous_comparable = {
        key: value for key, value in previous.items() if key != "generated_at"
    }
    if comparable == previous_comparable and previous.get("generated_at"):
        manifest["generated_at"] = previous["generated_at"]
    return manifest


def refresh_all(
    proj: Path,
    bucket_id: str | None = None,
    hub_refs: list[dict] | None = None,
) -> dict:
    registry = _load_registry(proj)
    summaries = []
    for entry in registry["sessions"]:
        try:
            index = refresh_trace(proj, entry["id"])
        except TraceCaptureError:
            index = _read_json(_trace_output_dir(proj, entry["id"]) / "index.json", {})
            if not index:
                continue
            index["source_available"] = False
        summaries.append(_trace_summary(index))
    summaries.sort(
        key=lambda item: item.get("started_at") or item.get("attached_at") or "",
        reverse=True,
    )
    traces_index = {
        "schema_version": TRACE_SCHEMA_VERSION,
        "sessions": summaries,
    }
    _write_json(proj / "logbook" / "traces" / "index.json", traces_index)
    workspace = _workspace_manifest(proj, registry, bucket_id, hub_refs)
    _write_json(proj / "logbook" / "workspace.json", workspace)
    return {"traces": traces_index, "workspace": workspace}


def read_generated(proj: Path) -> dict:
    traces = _read_json(proj / "logbook" / "traces" / "index.json", {})
    workspace = _read_json(proj / "logbook" / "workspace.json", {})
    return {
        "traces": traces if isinstance(traces, dict) else {},
        "workspace": workspace if isinstance(workspace, dict) else {},
    }


def _sts_timestamp(value: str | None) -> int | None:
    parsed = _parse_time(value)
    return int(parsed.timestamp() * 1000) if parsed else None


def _sts_arguments(value: Any) -> str:
    if not isinstance(value, str):
        return json.dumps(value if value is not None else {})
    try:
        json.loads(value)
        return value
    except json.JSONDecodeError:
        return json.dumps({"input": value}, ensure_ascii=False)


def _is_hub_native_jsonl(path: Path, provider: str | None) -> bool:
    """Whether Hub's Agent Traces viewer accepts this JSONL without conversion."""
    if path.suffix.lower() != ".jsonl":
        return False
    if provider in {"Codex", "Claude Code", "Pi"}:
        return True
    try:
        with path.open(encoding="utf-8") as handle:
            first_line = next((line for line in handle if line.strip()), "")
        header = json.loads(first_line)
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(header, dict) or header.get("type") != "session":
        return False
    # Session Trace Simple Format requires harness + id. Pi's native format uses
    # a versioned session header and is also supported directly by the Hub.
    return bool(
        header.get("id")
        and (header.get("harness") or header.get("version") is not None)
    )


def _write_sts_trace(path: Path, index: dict, events: list[dict]) -> None:
    records = [
        {
            "type": "session",
            "harness": "trackio",
            "id": index["id"],
            "name": index.get("title") or index["id"],
        }
    ]
    for event in events:
        timestamp = _sts_timestamp(event.get("timestamp"))
        if event.get("kind") in {"user", "assistant"}:
            message = {
                "role": event["kind"],
                "content": event.get("text") or "",
            }
        elif event.get("kind") == "reasoning":
            message = {
                "role": "assistant",
                "content": "",
                "reasoningContent": event.get("text") or "",
            }
        elif event.get("kind") == "tool_call":
            message = {
                "role": "assistant",
                "content": "",
                "toolCalls": [
                    {
                        "id": event.get("call_id") or event.get("id"),
                        "function": {
                            "name": event.get("tool_name")
                            or event.get("title")
                            or "tool",
                            "arguments": _sts_arguments(event.get("input")),
                        },
                    }
                ],
            }
        elif event.get("kind") == "tool_result":
            message = {
                "role": "tool",
                "content": event.get("output") or event.get("text") or "",
            }
            if event.get("call_id"):
                message["toolCallId"] = event["call_id"]
        else:
            message = {
                "role": "system",
                "content": event.get("title") or event.get("status") or "Status",
            }
        if timestamp is not None:
            message["timestamp"] = timestamp
        if message["role"] == "assistant" and index.get("model"):
            message["model"] = index["model"]
        records.append({"type": "message", "message": message})
    path.write_text(
        "\n".join(json.dumps(record, ensure_ascii=False) for record in records) + "\n",
        encoding="utf-8",
    )


def prepare_agent_trace_dataset(proj: Path) -> tuple[Path, int]:
    """Build a Hub Agent Traces dataset directory from attached sessions."""
    refresh_all(proj)
    export_dir = proj / TRACE_DATASET_EXPORT_DIR
    if export_dir.exists():
        shutil.rmtree(export_dir)
    export_dir.mkdir(parents=True)
    registry = _load_registry(proj)
    exported = 0
    for entry in registry["sessions"]:
        session_id = entry["id"]
        index = _read_json(_trace_output_dir(proj, session_id) / "index.json", {})
        if not index:
            continue
        raw_files = list(
            (proj / TRACE_STATE_DIR / "raw").glob(f"{_safe_id(session_id)}.*")
        )
        raw = raw_files[0] if raw_files else None
        destination = export_dir / f"{_safe_id(session_id)}.jsonl"
        if raw is not None and _is_hub_native_jsonl(raw, index.get("provider")):
            shutil.copy2(raw, destination)
        else:
            events = []
            for chunk in index.get("chunks") or []:
                chunk_data = _read_json(proj / "logbook" / chunk["file"], {})
                events.extend(chunk_data.get("events") or [])
            _write_sts_trace(destination, index, events)
        exported += 1
    (export_dir / "README.md").write_text(
        "---\n"
        "viewer_mode: traces\n"
        "pretty_name: Trackio Agent Traces\n"
        "tags:\n- agent-traces\n- format:agent-traces\n- traces\n- trackio\n"
        "configs:\n"
        "- config_name: default\n"
        "  default: true\n"
        "  data_files:\n"
        "  - split: train\n"
        "    path:\n"
        "    - '*.jsonl'\n"
        "---\n\n"
        "# Agent traces\n\nAgent sessions published from a Trackio Logbook.\n",
        encoding="utf-8",
    )
    return export_dir, exported


def sync_trace_dataset(
    proj: Path,
    dataset_id: str,
    *,
    private: bool,
    token: str | None = None,
) -> str:
    import huggingface_hub  # noqa: PLC0415

    export_dir, count = prepare_agent_trace_dataset(proj)
    if not count:
        raise TraceCaptureError("No attached traces are available to publish.")
    huggingface_hub.create_repo(
        dataset_id,
        repo_type="dataset",
        private=private,
        exist_ok=True,
        token=token,
    )
    huggingface_hub.update_repo_settings(
        dataset_id,
        repo_type="dataset",
        private=private,
        token=token,
    )
    huggingface_hub.upload_folder(
        repo_id=dataset_id,
        repo_type="dataset",
        folder_path=export_dir,
        commit_message="Update Trackio agent traces",
        delete_patterns="*.jsonl",
        token=token,
    )
    return f"https://huggingface.co/datasets/{dataset_id}"


def sync_workspace_bucket(
    proj: Path,
    bucket_id: str,
    private: bool,
    token: str | None = None,
) -> dict:
    import huggingface_hub  # noqa: PLC0415

    state = refresh_all(proj, bucket_id=bucket_id)
    workspace = state["workspace"]
    huggingface_hub.create_bucket(
        bucket_id, private=private, exist_ok=True, token=token
    )
    bucket_info = huggingface_hub.HfApi(token=token).bucket_info(bucket_id)
    if bucket_info.private != private:
        visibility = "private" if bucket_info.private else "public"
        requested = "private" if private else "public"
        raise TraceCaptureError(
            f"Workspace bucket '{bucket_id}' is already {visibility}; "
            f"it cannot be republished as {requested}."
        )
    desired = {
        f"{WORKSPACE_BUCKET_PREFIX}/{item['path']}": str(
            (proj.parent / item["path"]).resolve()
        )
        for item in workspace["files"]
        if item.get("local_url")
    }
    retained_remote = {
        f"{WORKSPACE_BUCKET_PREFIX}/{item['path']}"
        for item in workspace["files"]
        if item.get("imported") and item.get("bucket_id") == bucket_id
    }
    fingerprints = {
        remote_path: {
            "size": Path(local_path).stat().st_size,
            "mtime_ns": Path(local_path).stat().st_mtime_ns,
        }
        for remote_path, local_path in desired.items()
    }
    sync_state_path = proj / WORKSPACE_SYNC_STATE_FILE
    previous = _read_json(sync_state_path, {})
    previous_files = (
        previous.get("files", {}) if previous.get("bucket_id") == bucket_id else {}
    )
    remote = {
        item.path
        for item in huggingface_hub.list_bucket_tree(
            bucket_id,
            prefix=WORKSPACE_BUCKET_PREFIX,
            recursive=True,
            token=token,
        )
        if getattr(item, "type", None) == "file" and getattr(item, "path", None)
    }
    additions = [
        (local, remote_path)
        for remote_path, local in desired.items()
        if remote_path not in remote
        or previous_files.get(remote_path) != fingerprints[remote_path]
    ]
    deletions = sorted(remote - set(desired) - retained_remote)
    if additions or deletions:
        huggingface_hub.batch_bucket_files(
            bucket_id,
            add=additions or None,
            delete=deletions or None,
            token=token or huggingface_hub.utils.get_token(),
        )
    _write_json(
        sync_state_path,
        {"bucket_id": bucket_id, "synced_at": _now_iso(), "files": fingerprints},
    )
    return workspace


def resolve_workspace_file(proj: Path, relative_path: str) -> Path | None:
    manifest = _read_json(proj / "logbook" / "workspace.json", {})
    allowed = {item.get("path") for item in manifest.get("files", [])}
    if relative_path not in allowed:
        return None
    root = proj.parent.resolve()
    candidate = (root / relative_path).resolve()
    if not candidate.is_relative_to(root) or not candidate.is_file():
        return None
    return candidate
