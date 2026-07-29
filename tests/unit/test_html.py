import io
from pathlib import Path

import pytest

from trackio import Html, Run
from trackio.media import TrackioHtml
from trackio.sqlite_storage import SQLiteStorage

PROJECT_NAME = "test_project"

FRAGMENT = "<h1>Hello</h1><p>Some text.</p>"
FULL_DOCUMENT = "<!doctype html><html><body><p>full</p></body></html>"


def test_html_resolves_sources(tmp_path):
    fragment = TrackioHtml(FRAGMENT)
    assert fragment._html.lstrip().lower().startswith("<!doctype")
    assert FRAGMENT in fragment._html

    assert TrackioHtml(FRAGMENT, inject=False)._html == FRAGMENT
    assert TrackioHtml(FULL_DOCUMENT)._html == FULL_DOCUMENT

    file_path = tmp_path / "report.html"
    file_path.write_text(FULL_DOCUMENT, encoding="utf-8")
    assert TrackioHtml(str(file_path))._html == FULL_DOCUMENT

    assert TrackioHtml(io.StringIO(FULL_DOCUMENT))._html == FULL_DOCUMENT
    assert TrackioHtml(io.BytesIO(FULL_DOCUMENT.encode("utf-8")))._html == FULL_DOCUMENT

    stream = io.StringIO()
    stream.write(FULL_DOCUMENT)
    assert TrackioHtml(stream)._html == FULL_DOCUMENT

    with pytest.raises(ValueError):
        TrackioHtml(123)


def test_html_logging(temp_dir):
    run = Run(
        url=None, project=PROJECT_NAME, client=None, name="run-html", space_id=None
    )
    run.log({"loss": 0.1, "report": Html(FRAGMENT, caption="report")})
    run.finish()

    logs = SQLiteStorage.get_logs(PROJECT_NAME, "run-html")
    entries = [
        entry
        for entry in logs
        if isinstance(entry.get("report"), dict)
        and entry["report"].get("_type") == TrackioHtml.TYPE
    ]
    assert len(entries) == 1
    assert entries[0]["report"]["caption"] == "report"

    file_path = entries[0]["report"]["file_path"]
    assert file_path.startswith(str(Path(PROJECT_NAME) / "run-html"))
    assert file_path.endswith(".html")
    saved = Path(temp_dir) / "media" / file_path
    assert saved.is_file()
    assert FRAGMENT in saved.read_text(encoding="utf-8")


def test_matplotlib_figure_logging(temp_dir):
    matplotlib = pytest.importorskip("matplotlib")
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots()
    ax.plot([1, 2, 3, 4])

    assert TrackioHtml.is_loggable_figure(fig)
    assert TrackioHtml.is_loggable_figure(plt)
    assert not TrackioHtml.is_loggable_figure(FRAGMENT)

    run = Run(
        url=None, project=PROJECT_NAME, client=None, name="run-mpl", space_id=None
    )
    run.log({"chart": fig})
    run.finish()
    plt.close(fig)

    logs = SQLiteStorage.get_logs(PROJECT_NAME, "run-mpl")
    entries = [
        entry
        for entry in logs
        if isinstance(entry.get("chart"), dict)
        and entry["chart"].get("_type") == TrackioHtml.TYPE
    ]
    assert len(entries) == 1
    saved = Path(temp_dir) / "media" / entries[0]["chart"]["file_path"]
    assert saved.is_file()
    assert "<svg" in saved.read_text(encoding="utf-8")


def test_matplotlib_animation_to_jshtml():
    matplotlib = pytest.importorskip("matplotlib")
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.animation import FuncAnimation

    fig, ax = plt.subplots()
    (line,) = ax.plot([], [])

    def update(frame):
        line.set_data([0, frame], [0, frame])
        return (line,)

    anim = FuncAnimation(fig, update, frames=2, blit=True)
    assert TrackioHtml.is_loggable_figure(anim)

    html = TrackioHtml(anim)
    plt.close(fig)
    assert "<script" in html._html.lower()


def test_plotly_figure_logging(temp_dir):
    go = pytest.importorskip("plotly.graph_objects")

    fig = go.Figure(data=go.Scatter(x=[1, 2, 3], y=[4, 5, 6]))
    assert TrackioHtml.is_loggable_figure(fig)

    run = Run(
        url=None, project=PROJECT_NAME, client=None, name="run-plotly", space_id=None
    )
    run.log({"plot": fig})
    run.finish()

    logs = SQLiteStorage.get_logs(PROJECT_NAME, "run-plotly")
    entries = [
        entry
        for entry in logs
        if isinstance(entry.get("plot"), dict)
        and entry["plot"].get("_type") == TrackioHtml.TYPE
    ]
    assert len(entries) == 1
    saved = Path(temp_dir) / "media" / entries[0]["plot"]["file_path"]
    assert saved.is_file()
    assert "plotly" in saved.read_text(encoding="utf-8").lower()
