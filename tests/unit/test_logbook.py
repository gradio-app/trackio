import json
import sys

import pytest

from trackio import logbook


@pytest.fixture(autouse=True)
def enable_autonote(monkeypatch):
    monkeypatch.setenv("TRACKIO_LOGBOOK_AUTONOTE", "1")


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


def _artifact_cells(proj, page):
    outline = logbook.read_page_outline(proj, page)
    return [c for c in outline["cells"] if c["type"] == "artifact"]


def _page_text(proj, page):
    outline = logbook.read_page_outline(proj, page)
    return (logbook.logbook_root(proj) / outline["file"]).read_text(encoding="utf-8")


def test_run_and_log_records_created_artifact_file(proj):
    logbook.ensure_page(proj, "Runs")
    exit_code = logbook.run_and_log(
        proj,
        [sys.executable, "-c", "open('model.pt','wb').write(b'x'*2048)"],
        page="Runs",
    )
    assert exit_code == 0
    cells = _artifact_cells(proj, "Runs")
    assert len(cells) == 1
    assert cells[0]["path"] == "model.pt"
    assert cells[0]["artifact_type"] == "model"
    assert cells[0]["local"] is False
    assert "local file" in cells[0]["preview"]
    text = _page_text(proj, "Runs")
    assert "**📦 Artifact** `model.pt`" in text
    assert "trackio-artifact://" not in text
    assert not logbook.read_metadata(proj).get("local_artifacts")


def test_run_and_log_records_modified_file(proj, tmp_path):
    (tmp_path / "data.csv").write_text("a,b\n", encoding="utf-8")
    logbook.ensure_page(proj, "Runs")
    logbook.run_and_log(
        proj,
        [sys.executable, "-c", "open('data.csv','a').write('1,2\\n'*100)"],
        page="Runs",
    )
    cells = _artifact_cells(proj, "Runs")
    assert len(cells) == 1
    assert cells[0]["path"] == "data.csv"
    assert cells[0]["artifact_type"] == "dataset"


def test_run_and_log_capture_disabled_by_flag_and_env(proj, monkeypatch):
    logbook.ensure_page(proj, "Runs")
    command = [sys.executable, "-c", "open('a.pt','wb').write(b'x'*100)"]
    logbook.run_and_log(proj, command, page="Runs", capture_artifacts=False)
    assert _artifact_cells(proj, "Runs") == []
    monkeypatch.setenv("TRACKIO_LOGBOOK_AUTONOTE", "0")
    logbook.run_and_log(proj, command, page="Runs")
    assert _artifact_cells(proj, "Runs") == []


def test_run_and_log_caps_auto_artifact_cells(proj):
    logbook.ensure_page(proj, "Runs")
    script = (
        "import pathlib\n"
        "for i in range(12):\n"
        "    pathlib.Path(f'out_{i}.npy').write_bytes(b'x'*(100+i))\n"
    )
    logbook.run_and_log(proj, [sys.executable, "-c", script], page="Runs")
    cells = _artifact_cells(proj, "Runs")
    assert len(cells) == logbook._MAX_AUTO_ARTIFACT_CELLS
    paths = {c["path"] for c in cells}
    assert "out_11.npy" in paths
    assert "out_0.npy" not in paths
    assert "12 output files detected" in _page_text(proj, "Runs")


def test_run_and_log_captures_artifacts_on_nonzero_exit(proj):
    logbook.ensure_page(proj, "Runs")
    exit_code = logbook.run_and_log(
        proj,
        [
            sys.executable,
            "-c",
            "import sys; open('ckpt.safetensors','wb').write(b'x'*64); sys.exit(3)",
        ],
        page="Runs",
    )
    assert exit_code == 3
    cells = _artifact_cells(proj, "Runs")
    assert len(cells) == 1
    assert cells[0]["path"] == "ckpt.safetensors"


def test_run_and_log_skips_hidden_dirs_and_empty_files(proj):
    logbook.ensure_page(proj, "Runs")
    script = (
        "import pathlib\n"
        "pathlib.Path('.cache').mkdir()\n"
        "pathlib.Path('.cache/x.pt').write_bytes(b'x'*100)\n"
        "pathlib.Path('empty.pt').touch()\n"
    )
    logbook.run_and_log(proj, [sys.executable, "-c", script], page="Runs")
    assert _artifact_cells(proj, "Runs") == []


def test_diff_output_files_new_changed_unchanged():
    before = {"a.pt": (1, 10), "b.pt": (1, 20), "c.pt": (1, 30)}
    after = {"a.pt": (1, 10), "b.pt": (2, 25), "d.pt": (1, 5), "e.pt": (1, 0)}
    assert logbook._diff_output_files(before, after) == [
        ("b.pt", 25),
        ("d.pt", 5),
    ]


def test_artifact_display_path(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    inside = tmp_path / "checkpoints" / "model.pt"
    assert logbook._artifact_display_path(str(inside)) == "checkpoints/model.pt"
    outside = tmp_path.parent / "elsewhere.pt"
    assert logbook._artifact_display_path(str(outside)) == outside.as_posix()


def _dashboard_cells(proj, page):
    outline = logbook.read_page_outline(proj, page)
    return [c for c in outline["cells"] if c["type"] == "dashboard"]


def test_add_dashboard_cell_local(proj):
    slug = logbook.ensure_page(proj, "mnist")
    logbook.add_dashboard_cell(proj, slug, "mnist")
    text = _page_text(proj, "mnist")
    assert "trackio-local-dashboard://mnist" in text
    assert logbook.read_metadata(proj)["local_dashboards"] == {"mnist": None}
    cells = _dashboard_cells(proj, "mnist")
    assert len(cells) == 1
    assert cells[0]["project"] == "mnist"
    assert cells[0]["local"] is True
    assert cells[0]["link"] is None
    assert "mnist" in cells[0]["preview"]


def test_add_dashboard_cell_space(proj):
    slug = logbook.ensure_page(proj, "mnist")
    logbook.add_dashboard_cell(proj, slug, "mnist", space_id="me/mnist")
    cells = _dashboard_cells(proj, "mnist")
    assert cells[0]["local"] is False
    assert cells[0]["link"] == "https://huggingface.co/spaces/me/mnist"
    assert "local_dashboards" not in logbook.read_metadata(proj)


def test_auto_note_dashboard_dedupes(proj):
    logbook.auto_note_dashboard("mnist")
    logbook.auto_note_dashboard("mnist")
    logbook.auto_note_dashboard("mnist", space_id="me/mnist")
    assert len(_dashboard_cells(proj, "mnist")) == 1
    logbook.auto_note_dashboard("cifar")
    assert len(_dashboard_cells(proj, "cifar")) == 1


def test_auto_note_dashboard_disabled_or_no_logbook(proj, monkeypatch, tmp_path):
    monkeypatch.setenv("TRACKIO_LOGBOOK_AUTONOTE", "0")
    logbook.auto_note_dashboard("mnist")
    assert logbook._page_file_for_slug(proj, "mnist") is None
    monkeypatch.setenv("TRACKIO_LOGBOOK_AUTONOTE", "1")
    bare = tmp_path / "bare"
    bare.mkdir()
    monkeypatch.chdir(bare)
    logbook.auto_note_dashboard("mnist")


def test_init_creates_dashboard_cell_immediately(temp_dir, proj):
    import trackio

    trackio.init(project="p1", name="r1")
    assert len(_dashboard_cells(proj, "p1")) == 1
    trackio.finish()
    trackio.init(project="p1", name="r2")
    trackio.finish()
    outline = logbook.read_page_outline(proj, "p1")
    assert len([c for c in outline["cells"] if c["type"] == "dashboard"]) == 1
    assert not [c for c in outline["cells"] if (c["title"] or "").startswith("Run:")]


def test_promote_rewrites_dashboard_body(proj, monkeypatch):
    import trackio as trackio_module

    slug = logbook.ensure_page(proj, "mnist")
    logbook.add_dashboard_cell(proj, slug, "mnist")
    monkeypatch.setattr(trackio_module, "sync", lambda **kwargs: None)
    logbook._promote_local_deps(proj, "me", private=False)
    cells = _dashboard_cells(proj, "mnist")
    assert cells[0]["local"] is False
    assert cells[0]["link"] == "https://huggingface.co/spaces/me/mnist"


def test_preview_handler_dashboard_info(proj, monkeypatch):
    import http.client
    import socketserver
    import threading

    calls = []

    def fake_show(**kwargs):
        calls.append(kwargs)
        return (None, "http://127.0.0.1:9999/", None, "http://127.0.0.1:9999/?token=s")

    import trackio as trackio_module

    monkeypatch.setattr(trackio_module, "show", fake_show)
    handler_cls = logbook._make_preview_handler(logbook._local_dashboard_launcher())
    import functools

    handler = functools.partial(handler_cls, directory=str(logbook.logbook_root(proj)))
    with socketserver.ThreadingTCPServer(("127.0.0.1", 0), handler) as httpd:
        port = httpd.server_address[1]
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            for _ in range(2):
                conn = http.client.HTTPConnection("127.0.0.1", port)
                conn.request("GET", "/dashboard-info.json")
                resp = conn.getresponse()
                payload = json.loads(resp.read())
                assert resp.status == 200
                assert payload == {"url": "http://127.0.0.1:9999"}
                assert "no-store" in resp.getheader("Cache-Control", "")
                conn.close()
        finally:
            httpd.shutdown()
    assert len(calls) == 1


def test_cli_cell_dashboard(proj, monkeypatch):
    from trackio import cli

    monkeypatch.setattr(
        sys,
        "argv",
        ["trackio", "logbook", "cell", "dashboard", "mnist", "--page", "Demo"],
    )
    cli.main()
    cells = _dashboard_cells(proj, "demo")
    assert len(cells) == 1
    assert cells[0]["project"] == "mnist"


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
