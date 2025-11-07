from playwright.sync_api import expect, sync_playwright

import trackio


def test_basic_logging(temp_dir):
    trackio.init(project="test_project", name="test_run")
    trackio.log(metrics={"loss": 0.1})
    trackio.log(metrics={"loss": 0.2, "acc": 0.9})
    trackio.finish()

    app, url, _, _ =trackio.show(block_thread=False)

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            page.set_default_timeout(1000)
            page.goto(url)

            page.get_by_label("First Number").click()
            page.get_by_label("First Number").fill("3")
            page.get_by_label("Second Number (ignored for").click()
            page.get_by_label("Second Number (ignored for").fill("4")
            page.get_by_role("button", name="Calculate").click()
            locator = page.get_by_test_id("textbox")
            expect(locator).to_have_value("7")

            browser.close()
    finally:
        trackio.delete_project("test_project", force=True)
        app.close()
