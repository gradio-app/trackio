import numpy as np
from playwright.sync_api import expect, sync_playwright

import trackio


def test_runs_plots_images_are_displayed(temp_dir):
    trackio.init(project="test_project", name="test_run")
    trackio.log(metrics={"loss": 0.1})
    trackio.log(metrics={"loss": 0.2, "acc": 0.9})

    random_image = np.random.randint(0, 255, size=(64, 64, 3), dtype=np.uint8)
    trackio.log(
        metrics={"test_image": trackio.Image(random_image, caption="Test image")}
    )

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
            checkbox_label = page.locator("label.checkbox-label").filter(
                has_text="test_run"
            )
            expect(checkbox_label).to_be_visible()

            # Initially, two line plots should be displayed
            locator = page.locator(".vega-embed")
            expect(locator).to_have_count(2)

            # But if we uncheck the run, the line plots should be hidden
            checkbox_label.locator("input[type='checkbox']").uncheck()
            locator = page.locator(".vega-embed")
            expect(locator).to_have_count(0)

            # Navigate to media page and verify image is displayed
            page.get_by_role("link", name="Media & Tables").click()
            gallery = page.locator(".media-gallery")
            expect(gallery).to_be_visible()
            gallery_images = gallery.locator("img")
            expect(gallery_images.first).to_be_visible()

            browser.close()
    finally:
        trackio.delete_project("test_project", force=True)
        app.close()
