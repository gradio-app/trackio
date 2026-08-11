import io
import sys
from pathlib import Path
from typing import Any

from trackio.media.media import TrackioMedia
from trackio.utils import _emit_nonfatal_warning

_BASE_STYLE = (
    ":root{color-scheme:light dark;}"
    "body{margin:0;padding:12px;"
    "font-family:system-ui,-apple-system,sans-serif;}"
    "img,svg{max-width:100%;height:auto;}"
)


class TrackioHtml(TrackioMedia):
    """
    Initializes an Html object.

    Example:
        ```python
        import trackio

        trackio.init(project="my-project")

        # Raw HTML
        trackio.log({"report": trackio.Html("<h1>Results</h1>")})

        # Plotly figure
        import plotly.express as px

        fig = px.line(x=[1, 2, 3], y=[4, 5, 6])
        trackio.log({"plot": trackio.Html(fig)})

        # Matplotlib figure
        import matplotlib.pyplot as plt

        plt.plot([1, 2, 3, 4])
        trackio.log({"chart": trackio.Html(plt)})
        ```

    Args:
        data (`str`, `Path`, file-like, Plotly figure, or Matplotlib figure):
            Raw HTML, a path to an `.html` file, a file-like object, or a Plotly
            or Matplotlib figure.
        inject (`bool`, *optional*):
            Wrap HTML fragments in a styled document. Default is `True`.
        data_is_not_path (`bool`, *optional*):
            Accepted for `wandb.Html` compatibility but ignored.
        caption (`str`, *optional*):
            A string caption for the HTML.
    """

    TYPE = "trackio.html"

    def __init__(
        self,
        data: Any,
        inject: bool = True,
        data_is_not_path: bool = False,
        caption: str | None = None,
    ):
        if data_is_not_path:
            _emit_nonfatal_warning(
                "`data_is_not_path` is ignored; trackio auto-detects file paths "
                "vs. raw HTML."
            )
        super().__init__(value=None, caption=caption)
        self._format = "html"
        self._html = self._maybe_wrap(self._resolve_html(data), inject)

    @staticmethod
    def is_plotly_figure(obj: Any) -> bool:
        module = sys.modules.get("plotly.basedatatypes")
        return module is not None and isinstance(obj, module.BaseFigure)

    @staticmethod
    def is_matplotlib_figure(obj: Any) -> bool:
        module = sys.modules.get("matplotlib.figure")
        return module is not None and isinstance(obj, module.Figure)

    @staticmethod
    def is_matplotlib_animation(obj: Any) -> bool:
        module = sys.modules.get("matplotlib.animation")
        return module is not None and isinstance(obj, module.Animation)

    @staticmethod
    def is_pyplot_module(obj: Any) -> bool:
        return obj is sys.modules.get("matplotlib.pyplot")

    @staticmethod
    def is_loggable_figure(obj: Any) -> bool:
        return (
            TrackioHtml.is_plotly_figure(obj)
            or TrackioHtml.is_matplotlib_animation(obj)
            or TrackioHtml.is_pyplot_module(obj)
            or TrackioHtml.is_matplotlib_figure(obj)
        )

    @staticmethod
    def _resolve_html(data: Any) -> str:
        if TrackioHtml.is_plotly_figure(data):
            return data.to_html(full_html=True, include_plotlyjs="cdn")
        if TrackioHtml.is_matplotlib_animation(data):
            return data.to_jshtml()
        if TrackioHtml.is_pyplot_module(data):
            return TrackioHtml._matplotlib_figure_to_svg(data.gcf())
        if TrackioHtml.is_matplotlib_figure(data):
            return TrackioHtml._matplotlib_figure_to_svg(data)
        if hasattr(data, "read"):
            if hasattr(data, "seek"):
                data.seek(0)
            content = data.read()
            if isinstance(content, bytes):
                content = content.decode("utf-8")
            return content
        if isinstance(data, (str, Path)):
            path = Path(data)
            try:
                is_html_file = (
                    path.suffix.lower() in (".html", ".htm") and path.is_file()
                )
            except (OSError, ValueError):
                is_html_file = False
            if is_html_file:
                return path.read_text(encoding="utf-8")
            return str(data)
        raise ValueError(
            f"Invalid data type for Html, expected str, Path, file-like object, or "
            f"a Plotly/Matplotlib figure, got {type(data)}"
        )

    @staticmethod
    def _matplotlib_figure_to_svg(figure: Any) -> str:
        buffer = io.StringIO()
        figure.savefig(buffer, format="svg", bbox_inches="tight")
        svg = buffer.getvalue()
        return svg[svg.index("<svg") :]

    @staticmethod
    def _maybe_wrap(html: str, inject: bool) -> str:
        if not inject:
            return html
        stripped = html.lstrip().lower()
        if stripped.startswith("<!doctype") or stripped.startswith("<html"):
            return html
        return (
            '<!doctype html><html><head><meta charset="utf-8">'
            f"<style>{_BASE_STYLE}</style></head><body>{html}</body></html>"
        )

    def _save_media(self, file_path: Path):
        file_path.write_text(self._html, encoding="utf-8")
