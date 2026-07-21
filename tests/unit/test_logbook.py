import base64
import json
import re
import sys
from pathlib import Path

import pytest
from starlette.testclient import TestClient

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


def test_write_site_files_keeps_revision_stable_without_changes(proj):
    first = logbook.write_site_files(proj)
    second = logbook.write_site_files(proj)
    assert second["revision"] == first["revision"]
    assert second["updated_at"] == first["updated_at"]


def test_preview_manifest_refreshes_active_trace_and_workspace(proj, tmp_path):
    trace_path = tmp_path / "active-session.jsonl"
    trace_path.write_text(
        json.dumps({"role": "user", "content": "Start the experiment"}) + "\n",
        encoding="utf-8",
    )
    logbook.attach_trace(proj, trace_path)
    before = logbook.write_site_files(proj)

    with trace_path.open("a", encoding="utf-8") as trace:
        trace.write(json.dumps({"role": "assistant", "content": "Training now"}) + "\n")
    checkpoint = tmp_path / "checkpoint.safetensors"
    checkpoint.write_bytes(b"weights")

    with TestClient(logbook._build_preview_app(proj)) as client:
        response = client.get("/logbook.json")

    assert response.status_code == 200
    manifest = response.json()
    assert manifest["revision"] != before["revision"]
    assert manifest["traces"][0]["event_count"] == 2
    assert manifest["workspace"]["file_count"] == 1
    workspace = json.loads(
        (logbook.logbook_root(proj) / "workspace.json").read_text(encoding="utf-8")
    )
    assert workspace["files"][0]["path"] == "checkpoint.safetensors"


def test_logbook_run_path_artifact_appears_without_trace(proj, tmp_path):
    checkpoint = tmp_path / "run-output.ckpt"
    checkpoint.write_bytes(b"checkpoint")
    logbook.add_path_artifact_cell(
        proj,
        "index",
        str(checkpoint),
        checkpoint.stat().st_size,
        artifact_type="model",
    )

    manifest = logbook.write_site_files(proj)
    workspace = json.loads(
        (logbook.logbook_root(proj) / "workspace.json").read_text(encoding="utf-8")
    )
    assert manifest["workspace"]["file_count"] == 1
    assert workspace["files"][0]["path"] == "run-output.ckpt"
    assert workspace["files"][0]["captured_by"] == "logbook-run"


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


# A minimal valid 1x1 PNG.
_PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)


def test_figure_html_from_image_embeds_data_uri(tmp_path):
    png = tmp_path / "plot.png"
    png.write_bytes(_PNG_BYTES)
    html = logbook.figure_html_from_image(png)
    assert html.startswith('<img src="data:image/png;base64,')
    assert "max-width:100%" in html
    assert 'alt="plot"' in html


def test_figure_html_from_image_rejects_unsupported_type(tmp_path):
    bad = tmp_path / "notes.txt"
    bad.write_text("hello")
    with pytest.raises(logbook.LogbookError, match="Unsupported image type"):
        logbook.figure_html_from_image(bad)


def test_figure_html_from_image_missing_file(tmp_path):
    with pytest.raises(logbook.LogbookError, match="not found"):
        logbook.figure_html_from_image(tmp_path / "absent.png")


def test_add_figure_cell_accepts_image_path(proj, tmp_path):
    slug = logbook.ensure_page(proj, "Figs")
    png = tmp_path / "chart.png"
    png.write_bytes(_PNG_BYTES)
    logbook.add_figure_cell(proj, slug, image=png, title="Chart")

    outline = logbook.read_page_outline(proj, "Figs")
    figure_cell = outline["cells"][0]
    assert figure_cell["type"] == "figure"
    fig = logbook.read_cell(proj, figure_cell["id"], include_html=True)
    assert fig["has_html"]
    assert "data:image/png;base64," in fig["html"]


def test_is_figure_image_path():
    assert logbook.is_figure_image_path("a/b/plot.PNG")
    assert logbook.is_figure_image_path("chart.svg")
    assert not logbook.is_figure_image_path("page.html")
    assert not logbook.is_figure_image_path("notes.txt")


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
    with pytest.raises(logbook.LogbookError):
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
    assert cells[0]["local"] is True
    assert "local file" in cells[0]["preview"]
    text = _page_text(proj, "Runs")
    assert "**📦 Artifact** `model.pt`" in text
    assert "trackio-artifact://" not in text
    assert "trackio-local-path://model.pt" in text
    assert not logbook.read_metadata(proj).get("local_artifacts")
    path_arts = logbook.read_metadata(proj).get("local_path_artifacts")
    assert path_arts and path_arts[0]["path"] == "model.pt"


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
    page = logbook.ensure_page(proj, "Training results")
    logbook.auto_note_dashboard("mnist")
    logbook.auto_note_dashboard("mnist")
    logbook.auto_note_dashboard("mnist", space_id="me/mnist")
    assert len(_dashboard_cells(proj, page)) == 1
    logbook.auto_note_dashboard("cifar")
    assert len(_dashboard_cells(proj, page)) == 2
    assert logbook._page_file_for_slug(proj, "mnist") is None
    assert logbook._page_file_for_slug(proj, "cifar") is None


def test_auto_note_dashboard_without_active_page_is_a_noop(proj):
    logbook.auto_note_dashboard("mnist")

    assert logbook._page_file_for_slug(proj, "mnist") is None
    assert "local_dashboards" not in logbook.read_metadata(proj)


def test_auto_note_dashboard_disabled_or_no_logbook(proj, monkeypatch, tmp_path):
    monkeypatch.setenv("TRACKIO_LOGBOOK_AUTONOTE", "0")
    logbook.auto_note_dashboard("mnist")
    assert logbook._page_file_for_slug(proj, "mnist") is None
    monkeypatch.setenv("TRACKIO_LOGBOOK_AUTONOTE", "1")
    bare = tmp_path / "bare"
    bare.mkdir()
    monkeypatch.chdir(bare)
    logbook.auto_note_dashboard("mnist")


def test_init_does_not_mutate_logbook_pages(temp_dir, proj):
    """trackio.init() must be side-effect-free on a logbook in the cwd.

    Regression test: init() used to auto-note a dashboard cell on the active
    page, corrupting curated logbooks. It must not add cells or pages now.
    """
    import trackio

    page = logbook.ensure_page(proj, "Training results")
    before = logbook.read_page_outline(proj, page)["cells"]
    trackio.init(project="p1", name="r1")
    trackio.finish()
    trackio.init(project="p1", name="r2")
    trackio.finish()
    after = logbook.read_page_outline(proj, page)["cells"]
    assert len(after) == len(before)
    assert not [c for c in after if c["type"] == "dashboard"]
    # No stray sidebar page named after the project.
    assert logbook._page_file_for_slug(proj, "p1") is None


def test_log_artifact_does_not_create_logbook_page(temp_dir, proj, tmp_path):
    """Regression: log_artifact() used to inject a sidebar page named after the
    project (via auto_note_artifact -> ensure_page), appended after the last
    page and breaking logbook structure. It must not touch the page tree."""
    import trackio

    logbook.ensure_page(proj, "Conclusion")
    slugs_before = logbook._all_slugs(proj)

    weights = tmp_path / "model.bin"
    weights.write_bytes(b"\x00" * 2048)

    trackio.init(project="capacity-sweep", name="r1")
    art = trackio.Artifact(name="ckpt", type="model")
    art.add_file(weights)
    trackio.log_artifact(art)
    trackio.finish()

    assert logbook._all_slugs(proj) == slugs_before
    assert logbook._page_file_for_slug(proj, "capacity-sweep") is None


def test_promote_pushes_path_artifact_to_bucket_preserving_relative_path(
    proj, tmp_path, monkeypatch
):
    import huggingface_hub

    checkpoints = tmp_path / "checkpoints"
    checkpoints.mkdir()
    model_path = checkpoints / "model.pt"
    model_path.write_bytes(b"x" * 4096)

    slug = logbook.ensure_page(proj, "Runs")
    logbook.add_path_artifact_cell(
        proj, slug, str(model_path), size=4096, artifact_type="model"
    )
    metadata = logbook.read_metadata(proj)
    metadata["space_id"] = "me/Runs"
    logbook.write_metadata(proj, metadata)

    calls = []
    monkeypatch.setattr(
        huggingface_hub,
        "create_bucket",
        lambda bucket_id, **kw: calls.append(("create", bucket_id)),
    )
    monkeypatch.setattr(
        huggingface_hub,
        "batch_bucket_files",
        lambda bucket_id, add, **kw: calls.append(("upload", bucket_id, add)),
    )
    monkeypatch.setattr(huggingface_hub.utils, "get_token", lambda: "tok")

    logbook._promote_local_deps(proj, "me", private=False)

    cells = _artifact_cells(proj, "Runs")
    assert cells[0]["local"] is False
    assert (
        cells[0]["link"]
        == "https://huggingface.co/buckets/me/Runs-artifacts#logbook-files/checkpoints/model.pt"
    )

    upload_call = next(c for c in calls if c[0] == "upload")
    assert upload_call[1] == "me/Runs-artifacts"
    assert upload_call[2] == [
        (str(model_path.resolve()), "logbook-files/checkpoints/model.pt")
    ]

    metadata = logbook.read_metadata(proj)
    assert metadata["artifacts_bucket"] == "me/Runs-artifacts"


def test_promote_reuses_existing_bucket_on_second_publish(proj, tmp_path, monkeypatch):
    import huggingface_hub

    f = tmp_path / "out.csv"
    f.write_bytes(b"a,b\n1,2\n")
    slug = logbook.ensure_page(proj, "Runs")
    logbook.add_path_artifact_cell(proj, slug, str(f), size=8, artifact_type="dataset")
    metadata = logbook.read_metadata(proj)
    metadata["space_id"] = "me/Runs"
    logbook.write_metadata(proj, metadata)

    create_calls = []
    monkeypatch.setattr(
        huggingface_hub,
        "create_bucket",
        lambda bucket_id, **kw: create_calls.append(bucket_id),
    )
    monkeypatch.setattr(huggingface_hub, "batch_bucket_files", lambda *a, **kw: None)
    monkeypatch.setattr(huggingface_hub.utils, "get_token", lambda: "tok")

    logbook._promote_local_deps(proj, "me", private=False)
    first_bucket = logbook.read_metadata(proj)["artifacts_bucket"]

    # A second cell captured after the first publish should reuse the same bucket.
    f2 = tmp_path / "out2.csv"
    f2.write_bytes(b"c,d\n3,4\n")
    logbook.add_path_artifact_cell(proj, slug, str(f2), size=8, artifact_type="dataset")
    logbook._promote_local_deps(proj, "me", private=False)

    assert logbook.read_metadata(proj)["artifacts_bucket"] == first_bucket
    assert create_calls == [first_bucket, first_bucket]


def test_promote_skips_missing_path_artifact_file(proj, tmp_path, monkeypatch):
    import huggingface_hub

    f = tmp_path / "gone.pt"
    f.write_bytes(b"x" * 10)
    slug = logbook.ensure_page(proj, "Runs")
    logbook.add_path_artifact_cell(proj, slug, str(f), size=10, artifact_type="model")
    f.unlink()
    metadata = logbook.read_metadata(proj)
    metadata["space_id"] = "me/Runs"
    logbook.write_metadata(proj, metadata)

    monkeypatch.setattr(huggingface_hub, "create_bucket", lambda *a, **kw: None)
    uploads = []
    monkeypatch.setattr(
        huggingface_hub,
        "batch_bucket_files",
        lambda bucket_id, add, **kw: uploads.append(add),
    )
    monkeypatch.setattr(huggingface_hub.utils, "get_token", lambda: "tok")

    logbook._promote_local_deps(proj, "me", private=False)

    cells = _artifact_cells(proj, "Runs")
    assert cells[0]["local"] is True
    assert uploads == []


def test_promote_rewrites_dashboard_body(proj, monkeypatch):
    import trackio as trackio_module

    slug = logbook.ensure_page(proj, "mnist")
    logbook.add_dashboard_cell(proj, slug, "mnist")
    monkeypatch.setattr(trackio_module, "sync", lambda **kwargs: None)
    logbook._promote_local_deps(proj, "me", private=False)
    cells = _dashboard_cells(proj, "mnist")
    assert cells[0]["local"] is False
    assert cells[0]["link"] == "https://huggingface.co/spaces/me/mnist"


def test_preview_app_serves_logbook_and_mounted_dashboard(proj):
    from starlette.testclient import TestClient

    app = logbook._build_preview_app(proj)
    client = TestClient(app)

    root = client.get("/")
    assert root.status_code == 200
    assert "no-store" in root.headers.get("cache-control", "")
    assert "Test Logbook" in root.text

    dash_root = client.get("/dashboard/")
    assert dash_root.status_code == 200
    assert 'window.__trackio_base = "/dashboard"' in dash_root.text

    match = re.search(r'src="(/dashboard/assets/[^"]+\.js)"', dash_root.text)
    assert match
    asset = client.get(match.group(1))
    assert asset.status_code == 200
    assert "javascript" in asset.headers.get("content-type", "")

    missing = client.get("/dashboard/no-such-file.js")
    assert missing.status_code == 404 or "html" in missing.headers.get(
        "content-type", ""
    )


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


def test_cli_logbook_sync_regenerates_site(proj, monkeypatch):
    from trackio import cli

    logbook.ensure_page(proj, "Sweep")
    logbook_json = logbook.logbook_root(proj) / "logbook.json"
    logbook_json.unlink()
    monkeypatch.setattr(sys, "argv", ["trackio", "logbook", "sync"])
    cli.main()
    assert logbook_json.is_file()
    manifest = json.loads(logbook_json.read_text(encoding="utf-8"))
    assert any(node["title"] == "Sweep" for node in logbook._walk(manifest["root"]))


def test_cli_cell_remove_deletes_cell(proj, monkeypatch):
    from trackio import cli

    slug = logbook.ensure_page(proj, "Notes")
    logbook.add_markdown_cell(proj, slug, "keep me", title="Keep")
    logbook.add_markdown_cell(proj, slug, "drop me", title="Drop")
    cell_id = logbook.last_cell_id(proj, page="Notes")
    assert len(logbook.read_page_outline(proj, slug)["cells"]) == 2

    monkeypatch.setattr(sys, "argv", ["trackio", "logbook", "cell", "remove", cell_id])
    cli.main()

    cells = logbook.read_page_outline(proj, slug)["cells"]
    assert len(cells) == 1
    assert cells[0]["title"] == "Keep"
    assert "drop me" not in _page_text(proj, slug)


def test_remove_cell_missing_id_raises(proj):
    logbook.ensure_page(proj, "Notes")
    with pytest.raises(logbook.LogbookError):
        logbook.remove_cell(proj, "cell_doesnotexist")


def test_cli_cell_code_output_is_optional(proj, monkeypatch):
    from trackio import cli

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "trackio",
            "logbook",
            "cell",
            "code",
            "--page",
            "Runs",
            "--code-text",
            "print('hi')",
            "--language",
            "python",
        ],
    )
    cli.main()
    text = _page_text(proj, "Runs")
    assert "print('hi')" in text
    assert "````output" not in text


def test_add_code_cell_includes_output_when_provided(proj):
    slug = logbook.ensure_page(proj, "Runs")
    logbook.add_code_cell(proj, slug, "the output", code_text="cmd")
    text = _page_text(proj, "Runs")
    assert "````output" in text
    assert "the output" in text


def test_rewrite_plotly_cdn_replaces_inline_library():
    version = "2.27.0"
    big_library = "Plotly=" + "x" * 300_000 + f"/* plotly.js v{version} */"
    html = (
        "<div id='plot'></div>\n"
        f'<script charset="utf-8">{big_library}</script>\n'
        "<script>Plotly.newPlot('plot', data);</script>"
    )
    rewritten, changed = logbook._rewrite_plotly_cdn(html)
    assert changed is True
    assert big_library not in rewritten
    assert f"https://cdn.plot.ly/plotly-{version}.min.js" in rewritten
    # The small per-figure newPlot call is preserved.
    assert "Plotly.newPlot('plot', data);" in rewritten
    assert len(rewritten) < len(html)


def test_rewrite_plotly_cdn_ignores_non_plotly_html():
    html = "<div>hello</div><script>console.log(1)</script>"
    rewritten, changed = logbook._rewrite_plotly_cdn(html)
    assert changed is False
    assert rewritten == html


def test_add_figure_cell_rewrites_plotly_by_default(proj):
    slug = logbook.ensure_page(proj, "Figs")
    big_library = "Plotly=" + "x" * 300_000 + "/* plotly.js v2.30.0 */"
    html = (
        f'<div id="p"></div><script charset="utf-8">{big_library}</script>'
        "<script>Plotly.newPlot('p', []);</script>"
    )
    logbook.add_figure_cell(proj, slug, html=html)
    text = _page_text(proj, "Figs")
    assert "cdn.plot.ly/plotly-2.30.0.min.js" in text
    assert big_library not in text

    logbook.add_figure_cell(proj, slug, html=html, inline_plotlyjs=True)
    text = _page_text(proj, "Figs")
    assert big_library in text


def test_scan_hub_refs_classifies_urls(proj):
    slug = logbook.ensure_page(proj, "Links")
    body = (
        "See the run at https://huggingface.co/jobs/me/abc123 and dataset "
        "https://huggingface.co/datasets/me/data plus the space "
        "https://huggingface.co/spaces/me/demo, bucket "
        "https://huggingface.co/buckets/me/store#logbook-files/a.csv and again "
        "https://huggingface.co/buckets/me/store#logbook-files/b.csv, model "
        "https://huggingface.co/Qwen/Qwen2.5-Coder-32B-Instruct. Ignore the "
        "profile https://huggingface.co/me and docs "
        "https://huggingface.co/docs/hub/index."
    )
    logbook.add_markdown_cell(proj, slug, body)
    refs = logbook.scan_hub_refs(proj)
    by_type = {}
    for ref in refs:
        by_type.setdefault(ref["type"], []).append(ref["label"])
    assert by_type["Jobs"] == ["me/abc123"]
    assert by_type["Datasets"] == ["me/data"]
    assert by_type["Spaces"] == ["me/demo"]
    assert by_type["Models"] == ["Qwen/Qwen2.5-Coder-32B-Instruct"]
    # Two file links into the same bucket collapse to one reference.
    assert by_type["Buckets"] == ["me/store"]
    # Bare profile and docs links are not classified as artifacts.
    labels = [ref["label"] for ref in refs]
    assert "me" not in labels
    assert not any(ref["type"] == "Models" and ref["label"] == "me" for ref in refs)


def test_scrub_text_redacts_common_secrets():
    from trackio import logbook_trace

    hf = "hf_" + "a" * 30
    text = (
        f"token {hf}\n"
        "export HF_TOKEN=hf_SECRETSECRETSECRETSECRET1\n"
        "Authorization: Bearer sk-abc123def456ghi789jkl\n"
        "aws AKIAIOSFODNN7EXAMPLE key\n"
        '{"api_key": "sk-proj-1234567890abcdefghij"}\n'
        "password=hunter2pass\n"
    )
    scrubbed, count = logbook_trace.scrub_text(text)
    assert count >= 6
    assert hf not in scrubbed
    assert "AKIAIOSFODNN7EXAMPLE" not in scrubbed
    assert "hunter2pass" not in scrubbed
    assert "sk-proj-1234567890abcdefghij" not in scrubbed
    assert logbook_trace.REDACTION_PLACEHOLDER in scrubbed


def test_scrub_text_keeps_non_secret_mentions():
    from trackio import logbook_trace

    # A bare env-var NAME (no value) and an hf_ word that is too short must be
    # left untouched.
    text = "run with --secrets HF_TOKEN and note hf_indexed here"
    scrubbed, count = logbook_trace.scrub_text(text)
    assert count == 0
    assert scrubbed == text


def test_scrub_file_streams_and_counts(tmp_path):
    from trackio import logbook_trace

    src = tmp_path / "in.jsonl"
    dst = tmp_path / "out.jsonl"
    hf = "hf_" + "z" * 25
    src.write_text(
        json.dumps({"role": "user", "content": f"here is {hf}"})
        + "\n"
        + json.dumps({"role": "assistant", "content": "clean line"})
        + "\n",
        encoding="utf-8",
    )
    count = logbook_trace.scrub_file(src, dst)
    out = dst.read_text(encoding="utf-8")
    assert count == 1
    assert hf not in out
    assert "clean line" in out


def test_attach_trace_scrubs_by_default(proj, tmp_path):
    hf = "hf_" + "b" * 30
    trace_path = tmp_path / "secret-session.jsonl"
    trace_path.write_text(
        json.dumps({"role": "user", "content": f"my token is {hf}"})
        + "\n"
        + json.dumps({"role": "assistant", "content": "ok"})
        + "\n",
        encoding="utf-8",
    )
    result = logbook.attach_trace(proj, trace_path)
    assert result["scrub_redactions"] >= 1

    # Neither the normalized chunk nor the stored raw copy may contain the token.
    session_id = result["id"]
    stored = list((proj / "logbook" / "traces").rglob("*.json"))
    raw = list((proj / "traces" / "raw").glob("*"))
    for path in stored + raw:
        assert hf not in path.read_text(encoding="utf-8"), path
    assert session_id  # sanity


def test_attach_trace_no_scrub_keeps_content(proj, tmp_path):
    hf = "hf_" + "c" * 30
    trace_path = tmp_path / "raw-session.jsonl"
    trace_path.write_text(
        json.dumps({"role": "user", "content": f"token {hf}"}) + "\n",
        encoding="utf-8",
    )
    result = logbook.attach_trace(proj, trace_path, scrub=False)
    assert result.get("scrub_redactions", 0) == 0
    raw = list((proj / "traces" / "raw").glob("*"))
    assert any(hf in path.read_text(encoding="utf-8") for path in raw)


def test_publish_default_is_private_reference_only(proj, tmp_path, monkeypatch):
    import huggingface_hub

    from trackio import logbook_trace

    hf = "hf_" + "d" * 30
    trace_path = tmp_path / "session.jsonl"
    trace_path.write_text(
        json.dumps({"role": "user", "content": f"secret {hf}"}) + "\n",
        encoding="utf-8",
    )
    logbook.attach_trace(proj, trace_path, title="My secret session")
    checkpoint = tmp_path / "model.safetensors"
    checkpoint.write_bytes(b"weights")
    logbook.add_path_artifact_cell(
        proj, "index", str(checkpoint), size=7, artifact_type="model"
    )

    monkeypatch.setattr(logbook, "_promote_local_deps", lambda *a, **k: None)
    monkeypatch.setattr(logbook_trace, "sync_trace_dataset", lambda *a, **k: "url")
    monkeypatch.setattr(logbook_trace, "sync_workspace_bucket", lambda *a, **k: {})
    monkeypatch.setattr(huggingface_hub, "create_repo", lambda *a, **k: None)

    captured = {}

    class FakeApi:
        def __init__(self, *a, **k):
            pass

        def upload_folder(self, *, folder_path, **k):
            root = Path(folder_path)
            captured["manifest"] = json.loads(
                (root / "logbook.json").read_text(encoding="utf-8")
            )
            captured["has_traces_dir"] = (root / "traces").exists()
            captured["files"] = {
                p.relative_to(root).as_posix(): p.read_text(
                    encoding="utf-8", errors="ignore"
                )
                for p in root.rglob("*")
                if p.is_file()
            }

    monkeypatch.setattr(huggingface_hub, "HfApi", FakeApi)

    logbook.publish("me/space")

    manifest = captured["manifest"]
    # References only: no embedded trace content or names, private flag set.
    assert manifest["traces"] == []
    assert manifest["traces_ref"]["private"] is True
    assert manifest["traces_ref"]["repo_id"] == "me/space-traces"
    assert manifest["workspace_ref"]["private"] is True
    assert manifest["workspace_ref"]["repo_id"] == "me/space-artifacts"
    assert captured["has_traces_dir"] is False
    ws = json.loads(captured["files"]["workspace.json"])
    # The auto-generated workspace inventory carries no file names/sizes.
    assert ws["files"] == []
    # No scrubbed secret and no trace title/session content anywhere in the
    # static Space (author-curated page cells are a separate, intentional path).
    blob = "\n".join(captured["files"].values())
    assert hf not in blob
    assert "My secret session" not in blob


def test_publish_public_embeds_content(proj, tmp_path, monkeypatch):
    import huggingface_hub

    from trackio import logbook_trace

    trace_path = tmp_path / "session.jsonl"
    trace_path.write_text(
        json.dumps({"role": "user", "content": "hello world"}) + "\n",
        encoding="utf-8",
    )
    logbook.attach_trace(proj, trace_path, title="Public session")

    monkeypatch.setattr(logbook, "_promote_local_deps", lambda *a, **k: None)
    monkeypatch.setattr(logbook_trace, "sync_trace_dataset", lambda *a, **k: "url")
    monkeypatch.setattr(logbook_trace, "sync_workspace_bucket", lambda *a, **k: {})
    monkeypatch.setattr(huggingface_hub, "create_repo", lambda *a, **k: None)

    captured = {}

    class FakeApi:
        def __init__(self, *a, **k):
            pass

        def upload_folder(self, *, folder_path, **k):
            root = Path(folder_path)
            captured["manifest"] = json.loads(
                (root / "logbook.json").read_text(encoding="utf-8")
            )
            captured["has_traces_dir"] = (root / "traces").exists()

    monkeypatch.setattr(huggingface_hub, "HfApi", FakeApi)

    logbook.publish("me/space", public=True)

    manifest = captured["manifest"]
    # --public embeds trace content inline and marks the repo reference public.
    assert manifest["traces"], "public publish should embed trace summaries"
    assert manifest["traces_ref"]["private"] is False
    assert captured["has_traces_dir"] is True


def test_scan_hub_refs_written_into_workspace_manifest(proj):
    slug = logbook.ensure_page(proj, "Links")
    logbook.add_markdown_cell(proj, slug, "job https://huggingface.co/jobs/me/xyz789")
    logbook.write_site_files(proj)
    workspace = json.loads(
        (logbook.logbook_root(proj) / "workspace.json").read_text(encoding="utf-8")
    )
    assert workspace["hub_refs"] == [
        {
            "url": "https://huggingface.co/jobs/me/xyz789",
            "type": "Jobs",
            "label": "me/xyz789",
        }
    ]
