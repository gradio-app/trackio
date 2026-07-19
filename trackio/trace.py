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


class VerifiersTrace(Trace):
    """A queryable projection plus the complete native Verifiers trace record.

    Trackio intentionally does not import Verifiers. ``record`` may be a JSON
    mapping, a Verifiers ``Trace`` (``to_record``), or another Pydantic-like
    object exposing ``model_dump``.
    """

    TYPE = "trackio.verifiers_trace"

    def __init__(
        self,
        record: Any,
        messages: list[dict[str, Any]] | None = None,
        metadata: dict | None = None,
    ):
        native = self._record_mapping(record)
        trace_id = native.get("id")
        schema_version = native.get("version")
        if not isinstance(trace_id, str) or not trace_id:
            raise TypeError("Verifiers trace record requires a non-empty string `id`.")
        if not isinstance(schema_version, int) or isinstance(schema_version, bool):
            raise TypeError("Verifiers trace record requires an integer `version`.")

        display_messages = messages if messages is not None else self._final_branch(native)
        auto_metadata = self._metadata(native)
        super().__init__(display_messages, {**auto_metadata, **dict(metadata or {})})
        self.record = native
        self.trace_id = trace_id
        self.schema_version = schema_version

    @staticmethod
    def _record_mapping(record: Any) -> dict[str, Any]:
        if hasattr(record, "to_record"):
            record = record.to_record()
        elif hasattr(record, "model_dump"):
            record = record.model_dump(mode="json", exclude_none=True)
        if not isinstance(record, dict):
            raise TypeError("`record` must be a mapping or a Verifiers trace object.")
        return dict(record)

    @staticmethod
    def _final_branch(record: dict[str, Any]) -> list[dict[str, Any]]:
        nodes = record.get("nodes", [])
        if not isinstance(nodes, list) or not nodes:
            return []
        parents = {
            node.get("parent")
            for node in nodes
            if isinstance(node, dict) and isinstance(node.get("parent"), int)
        }
        leaves = [index for index in range(len(nodes)) if index not in parents]
        current = leaves[-1] if leaves else len(nodes) - 1
        path: list[int] = []
        seen: set[int] = set()
        while 0 <= current < len(nodes) and current not in seen:
            seen.add(current)
            path.append(current)
            node = nodes[current]
            parent = node.get("parent") if isinstance(node, dict) else None
            if not isinstance(parent, int):
                break
            current = parent
        messages = []
        for index in reversed(path):
            node = nodes[index]
            message = node.get("message") if isinstance(node, dict) else None
            if isinstance(message, dict):
                messages.append(dict(message))
        return messages

    @staticmethod
    def _metadata(record: dict[str, Any]) -> dict[str, Any]:
        agent = record.get("agent") or {}
        task = record.get("task") or {}
        task_data = (task.get("data") or {}) if isinstance(task, dict) else {}
        rewards = record.get("rewards") or {}
        errors = record.get("errors") or []
        last_error = errors[-1] if isinstance(errors, list) and errors else None
        last_call = next(
            (
                call
                for call in reversed(record.get("calls") or [])
                if isinstance(call, dict) and not call.get("error")
            ),
            None,
        )
        truncating_stops = {
            "max_turns",
            "max_input_tokens",
            "max_output_tokens",
            "max_total_tokens",
            "context_length",
            "harness_timeout",
        }
        return {
            "trace_id": record["id"],
            "trace_schema_version": record["version"],
            "model": agent.get("model") if isinstance(agent, dict) else None,
            "task_type": task.get("type") if isinstance(task, dict) else None,
            "task_index": task_data.get("idx") if isinstance(task_data, dict) else None,
            "reward": sum(rewards.values()) if isinstance(rewards, dict) else 0.0,
            "stop_condition": record.get("stop_condition"),
            "is_completed": bool(record.get("is_completed")),
            "is_truncated": record.get("stop_condition") in truncating_stops
            or bool(last_call and last_call.get("finish_reason") == "length"),
            "error_type": last_error.get("type") if isinstance(last_error, dict) else None,
        }

    def _to_dict(self, project: str, run: str, step: int = 0) -> dict[str, Any]:
        return {
            "_type": self.TYPE,
            "external_id": self.trace_id,
            "schema_version": self.schema_version,
            "messages": self._serialize_nested_value(self.messages, project, run, step),
            "metadata": self._serialize_nested_value(self.metadata, project, run, step),
            "payload": self._serialize_nested_value(self.record, project, run, step),
        }
