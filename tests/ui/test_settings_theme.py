from playwright.sync_api import expect, sync_playwright

import trackio


def test_settings_theme_switching_and_persistence(temp_dir):
    trackio.init(project="test_theme", name="theme_run")
    trackio.log(metrics={"loss": 0.5})
    trackio.finish()

    app, _, _, full_url = trackio.show(
        project="test_theme", block_thread=False, open_browser=False
    )

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            page.set_default_timeout(5000)
            base_url = full_url
            page.goto(base_url)

            settings_button = page.get_by_role("button", name="Settings", exact=True)
            expect(settings_button).to_be_visible()
            settings_button.click()
            expect(page.locator(".settings-page")).to_be_visible()

            page.get_by_role("button", name="Dark", exact=True).click()
            assert page.locator("html").get_attribute("data-theme") == "dark"

            page.get_by_role("button", name="Light", exact=True).click()
            assert page.locator("html").get_attribute("data-theme") is None

            page.get_by_role("button", name="Dark", exact=True).click()
            page.goto(base_url)
            expect(page.locator("html")).to_have_attribute("data-theme", "dark")

            browser.close()
    finally:
        trackio.delete_project("test_theme", force=True)
        app.close()
