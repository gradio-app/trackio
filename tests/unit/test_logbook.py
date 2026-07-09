import json
import sys

import pytest

from trackio import logbook


@pytest.fixture
def proj(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return logbook.create_logbook("Test Logbook")


def _index_text(proj):
    return (logbook.logbook_root(proj) / "pages" / "index.md").read_text(
        encoding="utf-8"
    )


def test_create_logbook_scaffolds_index_and_site(proj):
    index = _index_text(proj)
    assert "# Test Logbook" in index
    assert "## Pages" in index
    assert "| Page |" in index
    manifest = json.loads(
        (logbook.logbook_root(proj) / "logbook.json").read_text(encoding="utf-8")
    )
    assert manifest["title"] == "Test Logbook"
    assert manifest["agent_view_tokens"] >= 1
    assert manifest["revision"]
    assert manifest["updated_at"]


def test_write_site_files_refreshes_generated_viewer_assets(proj):
    viewer_js = logbook.logbook_root(proj) / "logbook.js"
    viewer_js.write_text("stale", encoding="utf-8")
    logbook.write_site_files(proj)
    assert viewer_js.read_text(encoding="utf-8") != "stale"


def test_write_site_files_updates_revision_after_logbook_changes(proj):
    manifest = json.loads(
        (logbook.logbook_root(proj) / "logbook.json").read_text(encoding="utf-8")
    )
    slug = logbook.ensure_page(proj, "Live")
    logbook.add_markdown_cell(proj, slug, "new result")
    updated = json.loads(
        (logbook.logbook_root(proj) / "logbook.json").read_text(encoding="utf-8")
    )
    assert updated["revision"] != manifest["revision"]


def test_ensure_page_adds_toc_row(proj):
    slug = logbook.ensure_page(proj, "LR sweep")
    assert slug == "lr-sweep"
    index = _index_text(proj)
    assert "[LR sweep](#/lr-sweep)" in index
    assert "logbook page" not in index
    assert logbook.ensure_page(proj, "LR sweep") == "lr-sweep"
    assert index.count("(#/lr-sweep)") == 1


def test_toc_honors_custom_status_column(proj):
    index_path = logbook.logbook_root(proj) / "pages" / "index.md"
    text = _index_text(proj).replace(
        "| Page |\n| --- |", "| Status | Page | Notes |\n| --- | --- | --- |"
    )
    index_path.write_text(text, encoding="utf-8")
    logbook.ensure_page(proj, "Run A", status="in-progress")
    assert "| in-progress | [Run A](#/run-a) |  |" in _index_text(proj)
    logbook.set_page_status(proj, "run-a", "done")
    assert "| done | [Run A](#/run-a) |  |" in _index_text(proj)


def test_set_page_status_noop_without_status_column(proj):
    logbook.ensure_page(proj, "Run B")
    before = _index_text(proj)
    logbook.set_page_status(proj, "run-b", "done")
    assert _index_text(proj) == before


def test_cells_roundtrip_through_read(proj):
    slug = logbook.ensure_page(proj, "Exp")
    logbook.add_markdown_cell(proj, slug, "A finding.", title="Finding")
    logbook.add_code_cell(
        proj,
        slug,
        "line1\nline2\nline3\nline4\nline5",
        title="Code",
        code_text="print('hi')",
        language="python",
    )
    logbook.add_figure_cell(proj, slug, html="<b>fig</b>", raw='{"x": 1}')
    logbook.add_artifact_cell(
        proj, slug, "proj/data:v1", size=1_000_000, artifact_type="dataset"
    )

    text = logbook.read_logbook(proj)
    assert "A finding." in text
    assert "Output (5 lines; last 3):" in text
    assert "line5" in text and "line1" not in text
    assert "print('hi')" in text
    assert '{"x": 1}' in text
    assert "· dataset ·" in text
    assert "local (pushed to a Bucket on publish)" in text

    outline = logbook.read_page_outline(proj, "Exp")
    types = [cell["type"] for cell in outline["cells"]]
    assert types == ["markdown", "code", "figure", "artifact"]

    code_cell = outline["cells"][1]
    assert code_cell["output_lines"] == 5
    full = logbook.read_cell(proj, code_cell["id"], include_full=True)
    assert "line1" in full["body"]

    figure_cell = outline["cells"][2]
    fig = logbook.read_cell(proj, figure_cell["id"], include_raw=True)
    assert fig["raw"] == '{"x": 1}'
    assert fig["has_html"]


def test_read_head_tail_options(proj):
    slug = logbook.ensure_page(proj, "Tails")
    logbook.add_code_cell(proj, slug, "a\nb\nc\nd", title="T")
    text = logbook.read_logbook(proj, tail=1)
    assert "Output (4 lines; last 1):" in text
    text = logbook.read_logbook(proj, tail=0)
    assert "Output (" not in text


def test_strip_duplicate_heading():
    assert logbook._strip_duplicate_heading("## Title\nBody", "Title") == "Body"
    assert (
        logbook._strip_duplicate_heading("## Other\nBody", "Title") == "## Other\nBody"
    )


def test_read_logbook_data_structure(proj):
    slug = logbook.ensure_page(proj, "Exp")
    logbook.add_markdown_cell(proj, slug, "Hello.")
    data = logbook.read_logbook_data(proj)
    assert data["title"] == "Test Logbook"
    index_entry = data["pages"][0]
    assert index_entry["slug"] == "index"
    assert "## Pages" in index_entry["markdown"]
    exp = next(page for page in data["pages"] if page["slug"] == "exp")
    assert exp["cells"][0]["body"] == "Hello."


def test_readme_title_with_colon_is_valid_yaml(proj):
    yaml = pytest.importorskip("yaml")
    manifest = logbook.write_site_files(proj)
    manifest["title"] = 'Repro: Capacity without Access: "quotes" too'
    readme = logbook._readme(manifest)
    front = readme.split("---\n")[1]
    assert yaml.safe_load(front)["title"] == manifest["title"]


def test_write_site_files_sets_html_title(proj):
    logbook.write_site_files(proj)
    index_html = (logbook.logbook_root(proj) / "index.html").read_text(encoding="utf-8")
    assert "<title>Test Logbook</title>" in index_html


def test_publish_failure_reverts_metadata(proj, monkeypatch):
    monkeypatch.setattr(logbook, "_promote_local_deps", lambda *a, **k: None)

    def boom(*args, **kwargs):
        raise RuntimeError("upload failed")

    monkeypatch.setattr(logbook, "_push", boom)
    with pytest.raises(RuntimeError):
        logbook.publish("user/space")
    metadata = logbook.read_metadata(proj)
    assert metadata.get("space_id") is None
    assert not metadata.get("autosync")


def test_metadata_tags_flow_into_manifest_and_readme(proj):
    metadata = logbook.read_metadata(proj)
    metadata["tags"] = ["icml2026-repro", "paper-abc123"]
    logbook.write_metadata(proj, metadata)
    manifest = logbook.write_site_files(proj)
    assert manifest["tags"] == ["icml2026-repro", "paper-abc123"]
    readme = logbook._readme(manifest)
    assert " - icml2026-repro\n" in readme
    assert " - paper-abc123\n" in readme


def test_run_and_log_captures_command_and_output(proj):
    logbook.ensure_page(proj, "Runs")
    exit_code = logbook.run_and_log(
        proj, [sys.executable, "-c", "print('out-marker')"], page="Runs"
    )
    assert exit_code == 0
    text = logbook.read_logbook(proj)
    assert "out-marker" in text
    assert "exit 0" in text


def test_resolve_read_source_local_and_invalid(proj, tmp_path):
    resolved = logbook.resolve_read_source(str(tmp_path))
    assert resolved == proj
    with pytest.raises(logbook.LogbookError):
        logbook.resolve_read_source("definitely::not::a::source")


def test_project_from_url_blocks_path_traversal(monkeypatch):
    import urllib.request

    manifest = {
        "root": {
            "slug": "index",
            "title": "T",
            "file": "pages/index.md",
            "children": [
                {
                    "slug": "evil",
                    "title": "E",
                    "file": "../../trackio-evil-traversal.md",
                    "children": [],
                }
            ],
        }
    }
    responses = {
        "logbook.json": json.dumps(manifest),
        "pages/index.md": "# T\n",
        "../../trackio-evil-traversal.md": "evil",
    }

    class FakeResponse:
        def __init__(self, data):
            self.data = data.encode("utf-8")

        def read(self):
            return self.data

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fake_urlopen(url, timeout=None):
        path = url.split("http://logbook.test/", 1)[1]
        if path in responses:
            return FakeResponse(responses[path])
        raise OSError("404")

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    proj = logbook._project_from_url("http://logbook.test")
    root = logbook.logbook_root(proj)
    assert (root / "pages" / "index.md").is_file()
    escaped = (root / ".." / ".." / "trackio-evil-traversal.md").resolve()
    assert not escaped.exists()
