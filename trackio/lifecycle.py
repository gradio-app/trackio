"""Normalize the lifecycle values a run records as metrics.

A run's status and timings are logged as ordinary metric rows rather than as
run-level columns. Reading them per run costs a request each, so both storage
providers answer for a whole project at once and share this shaping so the two
cannot drift apart.
"""

from __future__ import annotations

from typing import Any

LIFECYCLE_KEYS = (
    "run/status",
    "run/started_at",
    "run/finished_at",
    "run/error_type",
    "run/error_message",
)


def lifecycle_row(values: dict[str, Any]) -> dict[str, Any]:
    """Keep the lifecycle fields of one metric row, dropping everything else."""
    return {key: values[key] for key in LIFECYCLE_KEYS if key in values}
