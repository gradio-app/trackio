from playwright.sync_api import expect, sync_playwright

import trackio


def test_that_runs_are_displayed(temp_dir):
    trackio.init(project="test_project", name="test_run")
    trackio.log(metrics={"loss": 0.1})
    trackio.log(metrics={"loss": 0.2, "acc": 0.9})
    trackio.finish()

    app, url, _, _ = trackio.show(block_thread=False, open_browser=False)

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            page.set_default_timeout(1000)
            page.goto(url)

            # The project name and run name should be displayed
            locator = page.get_by_label("Project")
            expect(locator).to_be_visible()
            locator = page.get_by_text("test_run")
            expect(locator).to_be_visible()

            # Initially, two line plots should be displayed
            locator = page.locator(".vega-embed")
            expect(locator).to_have_count(2)

            # But if we uncheck the run, the line plots should be hidden
            page.get_by_label("test_run").uncheck()
            locator = page.locator(".vega-embed")
            expect(locator).to_have_count(0)

            browser.close()
    finally:
        trackio.delete_project("test_project", force=True)
        app.close()
