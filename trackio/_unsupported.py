"""Placeholders for W&B feature classes that Trackio does not yet implement."""

from typing import Any


class _UnsupportedFeature:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise NotImplementedError(
            f"trackio.{type(self).__name__} is not implemented yet. "
            "If you need this feature, please open a GitHub issue in the Trackio "
            "repository: https://github.com/gradio-app/trackio/issues/new"
        )


class ArtifactTTL(_UnsupportedFeature):
    """Placeholder for artifact time-to-live policies."""


class Classes(_UnsupportedFeature):
    """Placeholder for class labels used in media annotations."""


class Config(_UnsupportedFeature):
    """Placeholder for the W&B configuration container."""


class EvalTable(_UnsupportedFeature):
    """Placeholder for evaluation tables."""


class Graph(_UnsupportedFeature):
    """Placeholder for model graphs."""


class JoinedTable(_UnsupportedFeature):
    """Placeholder for joining tables by a shared key."""


class Molecule(_UnsupportedFeature):
    """Placeholder for molecular structure visualizations."""


class Plotly(_UnsupportedFeature):
    """Placeholder for Plotly visualizations."""


class Settings(_UnsupportedFeature):
    """Placeholder for W&B SDK settings."""
