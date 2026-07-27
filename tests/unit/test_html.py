import io
from pathlib import Path

import pytest

from trackio import Html, Run
from trackio.media import TrackioHtml
from trackio.sqlite_storage import SQLiteStorage

PROJECT_NAME = "test_project"

FRAGMENT = "<h1>Hello</h1><p>Some text.</p>"
FULL_DOCUMENT = "<!doctype html><html><body><p>full</p></body></html>"


def test_html_alias():
    assert Html is TrackioHtml


def test_html_save(temp_dir):
    html = TrackioHtml(FRAGMENT)
    html._save(PROJECT_NAME, "test_run", 0)

    expected_rel_dir = Path(PROJECT_NAME) / "test_run" / "0"
    assert str(html._get_relative_file_path()).startswith(str(expected_rel_dir))
    absolute_path = html._get_absolute_file_path()
    assert str(absolute_path).endswith(".html")
    assert absolute_path.is_file()
    assert FRAGMENT in absolute_path.read_text(encoding="utf-8")


def test_html_serialization(temp_dir):
    html = TrackioHtml(FRAGMENT, caption="a caption")
    html._save(PROJECT_NAME, "test_run", 0)
    value = html._to_dict()

    assert value.get("_type") == TrackioHtml.TYPE
    assert value.get("file_path") == str(html._get_relative_file_path())
    assert value.get("caption") == "a caption"


def test_html_inject_wraps_fragment():
    html = TrackioHtml(FRAGMENT)
    assert html._html.lstrip().lower().startswith("<!doctype")
    assert FRAGMENT in html._html


def test_html_inject_false_passes_through():
    html = TrackioHtml(FRAGMENT, inject=False)
    assert html._html == FRAGMENT


def test_html_full_document_not_double_wrapped():
    html = TrackioHtml(FULL_DOCUMENT)
    assert html._html == FULL_DOCUMENT


def test_html_reads_html_file(tmp_path):
    file_path = tmp_path / "report.html"
    file_path.write_text(FULL_DOCUMENT, encoding="utf-8")

    html = TrackioHtml(str(file_path))
    assert html._html == FULL_DOCUMENT


def test_html_from_text_file_like_object():
    html = TrackioHtml(io.StringIO(FULL_DOCUMENT))
    assert html._html == FULL_DOCUMENT


def test_html_from_bytes_file_like_object():
    html = TrackioHtml(io.BytesIO(FULL_DOCUMENT.encode("utf-8")))
    assert html._html == FULL_DOCUMENT


def test_html_from_file_like_object_not_at_start():
    stream = io.StringIO()
    stream.write(FULL_DOCUMENT)
    html = TrackioHtml(stream)
    assert html._html == FULL_DOCUMENT


def test_html_invalid_type():
    with pytest.raises(ValueError):
        TrackioHtml(123)


def test_html_string_with_null_byte_not_treated_as_path():
    data = "weird\x00name.html"
    html = TrackioHtml(data, inject=False)
    assert html._html == data


def test_data_is_not_path_ignored_but_warns():
    with pytest.warns(UserWarning, match="data_is_not_path"):
        html = TrackioHtml(FRAGMENT, data_is_not_path=True, inject=False)
    assert html._html == FRAGMENT


def test_is_loggable_figure_false_for_plain():
    assert not TrackioHtml.is_loggable_figure("string")
    assert not TrackioHtml.is_loggable_figure(1)
    assert not TrackioHtml.is_loggable_figure({"a": 1})
    assert not TrackioHtml.is_loggable_figure(TrackioHtml(FRAGMENT))


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
    assert entries[0]["report"]["file_path"].endswith(".html")


def test_matplotlib_figure_logging(temp_dir):
    matplotlib = pytest.importorskip("matplotlib")
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots()
    ax.plot([1, 2, 3, 4])

    assert TrackioHtml.is_loggable_figure(fig)
    assert TrackioHtml.is_loggable_figure(plt)

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
    file_path = entries[0]["chart"]["file_path"]
    assert file_path.endswith(".html")
    saved = Path(temp_dir) / "media" / file_path
    assert saved.is_file()
    assert "<svg" in saved.read_text(encoding="utf-8")


def test_pyplot_module_to_svg():
    matplotlib = pytest.importorskip("matplotlib")
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.figure()
    plt.plot([1, 2, 3])
    html = TrackioHtml(plt)
    plt.close("all")
    assert "<svg" in html._html


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


def test_plotly_figure_to_html():
    go = pytest.importorskip("plotly.graph_objects")

    fig = go.Figure(data=go.Scatter(x=[1, 2, 3], y=[4, 5, 6]))
    assert TrackioHtml.is_loggable_figure(fig)

    html = TrackioHtml(fig)
    assert "plotly" in html._html.lower()


def test_plotly_figure_logging(temp_dir):
    go = pytest.importorskip("plotly.graph_objects")

    fig = go.Figure(data=go.Scatter(x=[1, 2, 3], y=[4, 5, 6]))
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
    file_path = entries[0]["plot"]["file_path"]
    assert file_path.endswith(".html")
    saved = Path(temp_dir) / "media" / file_path
    assert saved.is_file()
    assert "plotly" in saved.read_text(encoding="utf-8").lower()
