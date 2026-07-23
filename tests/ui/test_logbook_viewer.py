import functools
import http.server
import json
import re
import socketserver
import threading

from playwright.sync_api import expect, sync_playwright

from trackio import logbook


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        pass


def test_logbook_renders_pages_as_single_document(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    proj = logbook.create_logbook("Single-page logbook")
    first = logbook.ensure_page(proj, "First experiment")
    second = logbook.ensure_page(proj, "Second experiment")
    logbook.add_markdown_cell(proj, first, "First section finding.")
    logbook.add_artifact_cell(proj, first, "demo/first:v1")
    logbook.add_markdown_cell(proj, second, "Second section finding.")
    logbook.add_artifact_cell(proj, second, "demo/second:v1")
    logbook.write_site_files(proj)

    handler = functools.partial(
        _QuietHandler, directory=str(logbook.logbook_root(proj))
    )
    socketserver.ThreadingTCPServer.allow_reuse_address = True
    with socketserver.ThreadingTCPServer(("127.0.0.1", 0), handler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                page = browser.new_page(viewport={"width": 1440, "height": 900})
                page.goto(f"http://127.0.0.1:{server.server_address[1]}/")

                expect(page.locator(".page-section")).to_have_count(3)
                expect(
                    page.get_by_role("heading", name="Pages", exact=True)
                ).to_have_count(0)
                expect(page.locator('[data-slug="index"] table.board')).to_have_count(0)
                expect(
                    page.get_by_role("heading", name="First experiment")
                ).to_be_visible()
                expect(
                    page.get_by_role("heading", name="Second experiment")
                ).to_be_visible()
                expect(page.locator("#tree a")).to_have_count(2)
                expect(page.locator(".context-rail")).to_have_count(0)

                content_box = page.locator("#page").bounding_box()
                assert content_box is not None
                paper_box = page.locator("#content").bounding_box()
                assert paper_box is not None
                paper_right = paper_box["x"] + paper_box["width"]
                assert content_box["x"] == 320
                assert paper_right - content_box["x"] - content_box["width"] == 320

                page.get_by_role("link", name="Second experiment").first.click()
                expect(page).to_have_url(re.compile(r"#/view/code/second-experiment$"))
                expect(page.locator("#tree a.active")).to_have_text(
                    "§ Second experiment"
                )
                browser.close()
        finally:
            server.shutdown()
            thread.join()


def test_dashboard_cell_uses_the_main_cell_header(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    proj = logbook.create_logbook("Dashboard logbook")
    slug = logbook.ensure_page(proj, "Dashboard")
    logbook.add_dashboard_cell(
        proj, slug, "backprop-repro", space_id="me/backprop-repro"
    )
    logbook.write_site_files(proj)

    handler = functools.partial(
        _QuietHandler, directory=str(logbook.logbook_root(proj))
    )
    socketserver.ThreadingTCPServer.allow_reuse_address = True
    with socketserver.ThreadingTCPServer(("127.0.0.1", 0), handler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                page = browser.new_page(viewport={"width": 1440, "height": 900})
                page.goto(f"http://127.0.0.1:{server.server_address[1]}/#/dashboard")

                cell = page.locator(".cell.dashboard")
                expect(cell).to_have_count(1)
                expect(cell.locator(".embed-head")).to_have_count(0)
                expect(cell.locator("iframe.dashboard-frame")).to_have_count(1)
                expect(cell.locator(".cell-head .cell-open")).to_have_count(1)
                expect(cell.locator(".cell-head .cell-open")).to_have_text("Open ↗")
                expect(cell.locator(".cell-head .cell-open")).to_have_attribute(
                    "href", "https://huggingface.co/spaces/me/backprop-repro"
                )
                browser.close()
        finally:
            server.shutdown()
            thread.join()


def test_figure_hotspot_navigates_to_its_logbook_page(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    proj = logbook.create_logbook("Interactive figure logbook")
    target = logbook.ensure_page(proj, "Claim evidence")
    conclusion = logbook.ensure_page(proj, "Conclusion")
    logbook.add_markdown_cell(proj, target, "Evidence lives here.")
    logbook.add_figure_cell(
        proj,
        conclusion,
        html=(
            "<button onclick=\"parent.postMessage({type:'trackio-logbook:navigate',"
            f"target:'{target}'}} , '*')\">Open details</button>"
        ),
    )
    logbook.write_site_files(proj)

    handler = functools.partial(
        _QuietHandler, directory=str(logbook.logbook_root(proj))
    )
    socketserver.ThreadingTCPServer.allow_reuse_address = True
    with socketserver.ThreadingTCPServer(("127.0.0.1", 0), handler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                page = browser.new_page(viewport={"width": 1440, "height": 900})
                page.goto(f"http://127.0.0.1:{server.server_address[1]}/#/conclusion")
                page.frame_locator("iframe.figure-frame").get_by_role(
                    "button", name="Open details"
                ).click()
                expect(page).to_have_url(re.compile(r"#/view/code/claim-evidence$"))
                browser.close()
        finally:
            server.shutdown()
            thread.join()


def test_trace_events_are_loaded_one_chunk_at_a_time(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    proj = logbook.create_logbook("Large trace logbook")
    trace_path = tmp_path / "large-trace.json"
    trace_path.write_text(
        json.dumps(
            [
                {"role": "assistant", "content": f"Trace event {index}"}
                for index in range(401)
            ]
        ),
        encoding="utf-8",
    )
    logbook.attach_trace(proj, trace_path, title="Large trace")
    logbook.write_site_files(proj)

    handler = functools.partial(
        _QuietHandler, directory=str(logbook.logbook_root(proj))
    )
    socketserver.ThreadingTCPServer.allow_reuse_address = True
    with socketserver.ThreadingTCPServer(("127.0.0.1", 0), handler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                page = browser.new_page(viewport={"width": 1440, "height": 900})
                requests = []
                page.on("request", lambda request: requests.append(request.url))
                page.goto(f"http://127.0.0.1:{server.server_address[1]}/#/view/trace")

                expect(page.locator(".trace-entry")).to_have_count(200)
                expect(page.locator(".trace-load-progress")).to_have_text(
                    "200 of 401 events loaded"
                )
                assert any("events-0000.json" in url for url in requests)
                assert not any("events-0001.json" in url for url in requests)

                page.get_by_role("button", name="Load 200 more events").click()
                expect(page.locator(".trace-entry")).to_have_count(400)
                expect(page.locator(".trace-load-progress")).to_have_text(
                    "400 of 401 events loaded"
                )
                assert any("events-0001.json" in url for url in requests)
                assert not any("events-0002.json" in url for url in requests)
                browser.close()
        finally:
            server.shutdown()
            thread.join()


def test_empty_trace_and_workspace_views_explain_how_they_fill(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    proj = logbook.create_logbook("Empty views logbook")

    handler = functools.partial(
        _QuietHandler, directory=str(logbook.logbook_root(proj))
    )
    socketserver.ThreadingTCPServer.allow_reuse_address = True
    with socketserver.ThreadingTCPServer(("127.0.0.1", 0), handler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                page = browser.new_page(viewport={"width": 1440, "height": 900})
                base_url = f"http://127.0.0.1:{server.server_address[1]}/"

                page.goto(base_url + "#/view/trace")
                expect(
                    page.get_by_role("heading", name="No agent sessions attached yet")
                ).to_be_visible()
                expect(page.locator(".view-empty code")).to_have_text(
                    "trackio logbook attach trace <session.jsonl>"
                )

                page.goto(base_url + "#/view/workspace")
                expect(
                    page.get_by_role("heading", name="No workspace files captured yet")
                ).to_be_visible()
                expect(page.locator(".view-empty")).to_contain_text(
                    "Files stay local until you choose to publish."
                )
                browser.close()
        finally:
            server.shutdown()
            thread.join()


def test_logbook_code_overflow_cli_ellipsis_and_copy(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    proj = logbook.create_logbook("Overflow logbook")
    slug = logbook.ensure_page(proj, "Long code")
    code_text = "\n".join(f"print({index})" for index in range(120))
    logbook.add_code_cell(proj, slug, "", code_text=code_text, language="python")
    logbook.write_site_files(proj)

    handler = functools.partial(
        _QuietHandler, directory=str(logbook.logbook_root(proj))
    )
    socketserver.ThreadingTCPServer.allow_reuse_address = True
    with socketserver.ThreadingTCPServer(("127.0.0.1", 0), handler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                page = browser.new_page(viewport={"width": 430, "height": 900})
                page.add_init_script(
                    """
                    Object.defineProperty(navigator, "clipboard", {
                      configurable: true,
                      value: { writeText: async (text) => { window.__copied = text; } }
                    });
                    """
                )
                page.goto(
                    f"http://127.0.0.1:{server.server_address[1]}/#/view/code/{slug}"
                )

                input_code = page.locator(".jp-in-body pre.hl")
                expect(input_code).to_be_visible()
                overflow = input_code.evaluate(
                    """el => ({
                      scrollHeight: el.scrollHeight,
                      clientHeight: el.clientHeight,
                      overflowY: getComputedStyle(el).overflowY
                    })"""
                )
                assert overflow["scrollHeight"] > overflow["clientHeight"]
                assert overflow["overflowY"] == "auto"

                command = page.locator(".agent-hint code")
                full_command = command.text_content()
                page.locator(".agent-hint .copy").click()
                expect(page.locator(".agent-hint .copy")).to_have_text("✓")
                assert page.evaluate("window.__copied") == full_command

                command.evaluate("(el) => { el.textContent += 'x'.repeat(240); }")
                truncation = command.evaluate(
                    """el => ({
                      scrollWidth: el.scrollWidth,
                      clientWidth: el.clientWidth,
                      overflow: getComputedStyle(el).overflow,
                      textOverflow: getComputedStyle(el).textOverflow,
                      whiteSpace: getComputedStyle(el).whiteSpace
                    })"""
                )
                assert truncation["scrollWidth"] > truncation["clientWidth"]
                assert truncation["overflow"] == "hidden"
                assert truncation["textOverflow"] == "ellipsis"
                assert truncation["whiteSpace"] == "nowrap"
                browser.close()
        finally:
            server.shutdown()
            thread.join()


def test_public_repo_visibility_and_hub_ref_filtering(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    proj = logbook.create_logbook("Referenced stores")
    logbook.write_site_files(proj)
    root = logbook.logbook_root(proj)

    manifest_path = root / "logbook.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["traces_ref"] = {
        "repo_id": "me/trace-data",
        "repo_type": "dataset",
        "repo_url": "https://huggingface.co/datasets/me/trace-data",
        "private": True,
        "viewer_path": "trackio/index.json",
    }
    manifest["workspace_ref"] = {
        "repo_id": "me/workspace-files",
        "repo_type": "bucket",
        "repo_url": "https://huggingface.co/buckets/me/workspace-files",
        "private": True,
    }
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    workspace_path = root / "workspace.json"
    workspace = json.loads(workspace_path.read_text(encoding="utf-8"))
    workspace["hub_refs"] = [
        {
            "url": "https://huggingface.co/jobs/me/{job_id}",
            "type": "Jobs",
            "label": "me/{job_id}",
        },
        {
            "url": "https://huggingface.co/datasets/{DATASET_ID}",
            "type": "Datasets",
            "label": "{DATASET_ID}",
        },
        {
            "url": "https://huggingface.co/spaces/{args.trackio_space}",
            "type": "Spaces",
            "label": "{args.trackio_space}",
        },
    ]
    workspace_path.write_text(json.dumps(workspace), encoding="utf-8")

    handler = functools.partial(_QuietHandler, directory=str(root))
    socketserver.ThreadingTCPServer.allow_reuse_address = True
    with socketserver.ThreadingTCPServer(("127.0.0.1", 0), handler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                page = browser.new_page(viewport={"width": 1440, "height": 900})
                public_metadata = json.dumps({"private": False})
                page.route(
                    "https://huggingface.co/api/datasets/me/trace-data",
                    lambda route: route.fulfill(
                        status=200,
                        content_type="application/json",
                        body=public_metadata,
                    ),
                )
                page.route(
                    "https://huggingface.co/api/buckets/me/workspace-files",
                    lambda route: route.fulfill(
                        status=200,
                        content_type="application/json",
                        body=public_metadata,
                    ),
                )
                page.route(
                    "https://huggingface.co/api/buckets/me/workspace-files/tree",
                    lambda route: route.fulfill(
                        status=200,
                        content_type="application/json",
                        body=json.dumps(
                            [
                                {
                                    "type": "file",
                                    "path": "workspace/results/metrics.csv",
                                    "size": 128,
                                    "mtime": "2026-07-21T10:00:00Z",
                                },
                                {
                                    "type": "file",
                                    "path": "logbook-files/results/metrics.csv",
                                    "size": 128,
                                    "mtime": "2026-07-21T10:00:00Z",
                                },
                            ]
                        ),
                    ),
                )
                page.route(
                    "https://huggingface.co/datasets/me/trace-data/resolve/main/trackio/index.json",
                    lambda route: route.fulfill(
                        status=200,
                        content_type="application/json",
                        body=json.dumps(
                            {
                                "schema_version": 1,
                                "sessions": [
                                    {
                                        "id": "remote-session",
                                        "title": "Published reproduction session",
                                        "index_file": "traces/remote-session/index.json",
                                    }
                                ],
                            }
                        ),
                    ),
                )
                page.route(
                    "https://huggingface.co/datasets/me/trace-data/resolve/main/trackio/traces/remote-session/index.json",
                    lambda route: route.fulfill(
                        status=200,
                        content_type="application/json",
                        body=json.dumps(
                            {
                                "id": "remote-session",
                                "title": "Published reproduction session",
                                "event_count": 1,
                                "started_at": "2026-07-21T10:00:00Z",
                                "ended_at": "2026-07-21T10:00:01Z",
                                "duration_ms": 1000,
                                "chunks": [
                                    {
                                        "file": "traces/remote-session/events-0000.json",
                                        "count": 1,
                                    }
                                ],
                            }
                        ),
                    ),
                )
                page.route(
                    "https://huggingface.co/datasets/me/trace-data/resolve/main/trackio/traces/remote-session/events-0000.json",
                    lambda route: route.fulfill(
                        status=200,
                        content_type="application/json",
                        body=json.dumps(
                            {
                                "events": [
                                    {
                                        "kind": "message",
                                        "sequence": 1,
                                        "title": "Assistant",
                                        "text": "Loaded from the public trace dataset.",
                                    }
                                ]
                            }
                        ),
                    ),
                )
                base_url = f"http://127.0.0.1:{server.server_address[1]}/"

                page.goto(base_url + "#/view/workspace")
                expect(page.locator(".repo-ref-card")).to_have_count(0)
                expect(page.locator(".workspace-file")).to_have_count(1)
                expect(page.locator(".workspace-file")).to_contain_text("metrics.csv")
                expect(page.locator(".workspace-header")).to_contain_text(
                    "1 files · 128 B"
                )
                expect(page.locator("#tree .tree-label")).to_have_text("Artifacts")
                expect(page.locator("#tree a").first).to_have_text("Workspace files")
                expect(page.locator("#tree")).not_to_contain_text("§")
                expect(
                    page.get_by_role(
                        "heading", name="Linked Hugging Face artifacts", exact=True
                    )
                ).to_be_visible()
                expect(
                    page.locator('.workspace-hub-link[href$="/datasets/me/trace-data"]')
                ).to_have_count(1)
                expect(
                    page.locator(
                        '.workspace-hub-link[href$="/buckets/me/workspace-files"]'
                    )
                ).to_have_count(1)
                expect(page.locator(".workspace-hub-link", has_text="{")).to_have_count(
                    0
                )

                page.goto(base_url + "#/view/trace")
                expect(page.locator(".repo-ref-card")).to_have_count(0)
                expect(page.locator(".trace-session-title")).to_have_text(
                    "Published reproduction session"
                )
                expect(page.locator(".trace-entry")).to_contain_text(
                    "Loaded from the public trace dataset."
                )
                expect(page.locator("#tree .tree-label")).to_have_text("Sessions")
                expect(page.locator("#tree a")).to_have_text(
                    "Published reproduction session"
                )
                assert page.evaluate("window.scrollY") == 0
                browser.close()
        finally:
            server.shutdown()
            thread.join()
