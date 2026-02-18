from playwright.sync_api import expect, sync_playwright

import trackio


def test_group_checkbox_no_redundant_render(temp_dir):
    for lr in ["0.01", "0.001"]:
        trackio.init(project="test_grouped", name=f"run-lr-{lr}", config={"lr": lr})
        trackio.log(metrics={"loss": 0.5})
        trackio.finish()

    app, url, _, _ = trackio.show(block_thread=False, open_browser=False)

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            page.set_default_timeout(5000)
            page.goto(url)

            group_dd = page.get_by_label("Group by...")
            group_dd.click()
            page.get_by_role("option", name="lr").click()

            page.wait_for_timeout(500)

            accordion_button = page.locator("button").filter(has_text="lr:").first
            accordion_button.click()
            page.wait_for_timeout(300)

            item_checkboxes = page.locator(".item-checkbox input[type='checkbox']")
            expect(item_checkboxes.first).to_be_visible()

            first_cb = item_checkboxes.first
            expect(first_cb).to_be_checked()

            first_cb.uncheck()
            page.wait_for_timeout(500)
            expect(first_cb).not_to_be_checked()

            first_cb.check()
            page.wait_for_timeout(500)
            expect(first_cb).to_be_checked()

            browser.close()
    finally:
        trackio.delete_project("test_grouped", force=True)
        app.close()
