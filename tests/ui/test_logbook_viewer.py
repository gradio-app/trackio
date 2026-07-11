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

                sections_with_resources = page.locator(
                    ".page-section:has(.context-rail .rail-item)"
                )
                expect(sections_with_resources).to_have_count(2)
                expect(
                    page.locator('[data-slug="first-experiment"] .rail-item')
                ).to_have_count(1)
                expect(
                    page.locator('[data-slug="second-experiment"] .rail-item')
                ).to_have_count(1)

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
