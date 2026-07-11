from pathlib import Path

from trackio.frontend_server import _render_index_html

_HTML = """<!DOCTYPE html>
<html><head>
<meta charset="UTF-8" />
<link rel="icon" type="image/png" href="/static/trackio/trackio_logo_light.png" />
<script type="module" crossorigin src="/assets/index-abc123.js"></script>
<link rel="stylesheet" crossorigin href="/assets/index-abc123.css">
</head><body><div id="app"></div></body></html>
"""


def _write_html(tmp_path: Path) -> Path:
    path = tmp_path / "index.html"
    path.write_text(_HTML, encoding="utf-8")
    return path


def test_render_index_html_no_root_path_leaves_absolute_refs(tmp_path):
    out = _render_index_html(_write_html(tmp_path))
    assert 'src="/assets/index-abc123.js"' in out
    assert 'href="/assets/index-abc123.css"' in out
    assert 'href="/static/trackio/trackio_logo_light.png"' in out
    assert "window.__trackio_base" not in out


def test_render_index_html_with_root_path_prefixes_refs(tmp_path):
    out = _render_index_html(_write_html(tmp_path), root_path="/dashboard")
    assert 'src="/dashboard/assets/index-abc123.js"' in out
    assert 'href="/dashboard/assets/index-abc123.css"' in out
    assert 'href="/dashboard/static/trackio/trackio_logo_light.png"' in out
    assert 'window.__trackio_base = "/dashboard";' in out


def test_render_index_html_live_reload_endpoint_is_prefixed(tmp_path):
    out = _render_index_html(_write_html(tmp_path), root_path="/dashboard")
    assert '"/dashboard/__trackio/frontend_version"' in out


def test_render_index_html_live_reload_endpoint_unprefixed_by_default(tmp_path):
    out = _render_index_html(_write_html(tmp_path))
    assert '"/__trackio/frontend_version"' in out
