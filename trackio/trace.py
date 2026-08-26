from __future__ import annotations

from typing import Any

from trackio.media import TrackioMedia


class Trace:
    """
    Initializes a Trace object.

    Traces capture a conversational or agent-style request: OpenAI-style messages,
    optional metadata, and optional execution spans. Spans are dictionaries that
    describe model generations, tool calls, or other operations. Nested Trackio
    media objects inside messages, metadata, or spans are persisted and serialized
    alongside the trace.

    Args:
        messages (`list[dict[str, Any]]`):
            OpenAI-style messages, e.g. `{"role": "user", "content": "..."}`.
            Assistant messages may include `tool_calls`, and tool results may
            include `tool_call_id`; when no `spans` are provided, the dashboard
            pairs those into tool operations.
        metadata (`dict`, *optional*):
            Trace-level metadata, e.g. `session_id` or `environment`. The keys
            `status`, `duration_ms`, `latency_ms`, and `cost_usd` are used by the
            dashboard as trace-level fallbacks when spans do not supply them.
        spans (`list[dict[str, Any]]`, *optional*):
            Execution spans describing what produced the response. Each span is a
            dictionary keyed by `id`, `name`, and `kind` (`"span"`, `"generation"`,
            or `"tool"`), plus optional `parent_id`, `start_time`, `end_time`,
            `duration_ms`, `status`, `error`, `input`, `output`, `model`, `usage`,
            `cost_usd`, and `metadata`.
    """

    TYPE = "trackio.trace"

    def __init__(
        self,
        messages: list[dict[str, Any]],
        metadata: dict | None = None,
        spans: list[dict[str, Any]] | None = None,
    ):
        if not isinstance(messages, list) or not all(
            isinstance(message, dict) for message in messages
        ):
            raise TypeError("`messages` must be a list of dictionaries.")
        if spans is not None and (
            not isinstance(spans, list)
            or not all(isinstance(span, dict) for span in spans)
        ):
            raise TypeError("`spans` must be a list of dictionaries.")

        self.messages = [dict(message) for message in messages]
        self.metadata = dict(metadata) if metadata is not None else {}
        self.spans = [dict(span) for span in spans] if spans is not None else []

    def _serialize_nested_value(
        self, value: Any, project: str, run: str, step: int
    ) -> Any:
        if isinstance(value, TrackioMedia):
            value._save(project, run, step)
            return value._to_dict()
        if isinstance(value, dict):
            return {
                key: self._serialize_nested_value(item, project, run, step)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [
                self._serialize_nested_value(item, project, run, step) for item in value
            ]
        return value

    def _to_dict(self, project: str, run: str, step: int = 0) -> dict[str, Any]:
        return {
            "_type": self.TYPE,
            "messages": self._serialize_nested_value(self.messages, project, run, step),
            "metadata": self._serialize_nested_value(self.metadata, project, run, step),
            "spans": self._serialize_nested_value(self.spans, project, run, step),
        }
