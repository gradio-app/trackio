from __future__ import annotations

from typing import Any

from trackio.media import TrackioMedia


class Trace:
    """
    Conversational or agent-style trace payload.

    Traces store OpenAI-style messages plus optional metadata. Nested Trackio
    media objects inside messages or metadata are persisted and serialized
    alongside the trace.
    """

    TYPE = "trackio.trace"

    def __init__(self, messages: list[dict[str, Any]], metadata: dict | None = None):
        if not isinstance(messages, list) or not all(
            isinstance(message, dict) for message in messages
        ):
            raise TypeError("`messages` must be a list of dictionaries.")

        self.messages = [dict(message) for message in messages]
        self.metadata = dict(metadata) if metadata is not None else {}

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
        }
