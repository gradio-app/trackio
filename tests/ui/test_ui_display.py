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
            page.set_default_timeout(5000)
            page.goto(url + "trackio/")
            page.wait_for_load_state("networkidle")

            run_label = page.locator(".run-name", has_text="test_run")
            expect(run_label).to_be_visible()

            checkbox = run_label.locator("xpath=ancestor::label").locator(
                "input[type='checkbox']"
            )
            expect(checkbox).to_be_checked()

            locator = page.locator(".vega-embed")
            expect(locator).to_have_count(2)

            checkbox.uncheck()
            locator = page.locator(".vega-embed")
            expect(locator).to_have_count(0)

            page.locator(".nav-link", has_text="Media").click()
            page.wait_for_load_state("networkidle")
            gallery = page.locator(".gallery")
            expect(gallery).to_be_visible()
            gallery_images = gallery.locator("img")
            expect(gallery_images.first).to_be_visible()

            browser.close()
    finally:
        trackio.delete_project("test_project", force=True)
        app.close()
