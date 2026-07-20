import functools
import http.server
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

                page.get_by_role("link", name="Second experiment").first.click()
                expect(page).to_have_url(re.compile(r"#/second-experiment$"))
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


def test_logbook_index_omits_hub_summary(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    proj = logbook.create_logbook("Reproduction: Hub summary test")
    index = logbook.logbook_root(proj) / "pages" / "index.md"
    index.write_text(
        "# Reproduction: Hub summary test\n\n"
        "[OpenReview paper](https://openreview.net/forum?id=abc123XYZ1)\n\n"
        "## Pages\n\n| Page |\n| --- |\n",
        encoding="utf-8",
    )
    executive = logbook.ensure_page(proj, "Executive summary")
    logbook.add_markdown_cell(proj, executive, "Pinned reproduction summary.")
    logbook.set_cell_pinned(proj, logbook.last_cell_id(proj, executive), page=executive)
    logbook.add_markdown_cell(proj, executive, "Pinned reproduction poster.")
    logbook.set_cell_pinned(proj, logbook.last_cell_id(proj, executive), page=executive)
    claim = logbook.ensure_page(proj, "Claim 1: Demo")
    logbook.add_markdown_cell(
        proj,
        claim,
        "Models: https://huggingface.co/org/model-a "
        "https://huggingface.co/org/model-b "
        "https://huggingface.co/org/model-c\n"
        "Datasets: https://huggingface.co/datasets/org/data-a "
        "https://huggingface.co/datasets/org/data-b\n"
        "Job: https://huggingface.co/jobs/org/abc123def4567890\n"
        "Code: https://github.com/org/repro-repo",
    )
    logbook.add_artifact_cell(proj, claim, "org/bundle:v1")
    claim_path = logbook.logbook_root(proj) / "pages" / claim / "page.md"
    claim_path.write_text(
        claim_path.read_text(encoding="utf-8").replace(
            "trackio-artifact://org/bundle:v1",
            "https://huggingface.co/buckets/org/my-bucket-artifacts#org/bundle:v1",
        ),
        encoding="utf-8",
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
                page.goto(f"http://127.0.0.1:{server.server_address[1]}/")

                intro = page.locator('[data-slug="index"] .page-body')
                expect(intro.locator("h1")).to_have_text(
                    "Reproduction: Hub summary test"
                )
                expect(intro.locator(".index-paper-link a")).to_have_attribute(
                    "href", "https://openreview.net/forum?id=abc123XYZ1"
                )
                assert (
                    intro.locator(".index-paper-link").evaluate(
                        "el => parseFloat(getComputedStyle(el).fontSize)"
                    )
                    >= 19
                )
                expect(intro.locator(".agent-hint")).to_have_count(1)

                executive_body = page.locator(
                    '[data-slug="executive-summary"] .page-body'
                )
                expect(executive_body.locator(".pinned-copy")).to_have_count(2)
                expect(page.locator(".pinned-source:not(.pinned-copy)")).to_have_count(
                    0
                )
                expect(executive_body.locator(":scope > .pinned-notes")).to_have_count(
                    1
                )
                assert executive_body.locator(":scope > *").evaluate_all(
                    "els => els.map(el => el.className || el.tagName)"
                ) == ["H1", "pinned-notes"]

                expect(page.locator(".logbook-hub-summary")).to_have_count(0)
                expect(page.locator(".logbook-stats")).to_have_count(0)
                expect(page.locator(".context-rail")).to_have_count(0)
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
                expect(page).to_have_url(re.compile(r"#/claim-evidence$"))
                browser.close()
        finally:
            server.shutdown()
            thread.join()
