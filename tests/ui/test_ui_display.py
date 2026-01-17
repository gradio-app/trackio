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

            # capture textual ordering of metric names on the page
            body_text_before = page.locator("body").inner_text()
            idx_loss_before = body_text_before.find("loss")
            idx_acc_before = body_text_before.find("acc")
            assert idx_loss_before != -1 and idx_acc_before != -1
            assert idx_loss_before < idx_acc_before

            # toggle the X-axis and ensure layout (order) is preserved
            xaxis = page.get_by_label("X-axis")
            try:
                xaxis.select_option("time")
                expect(locator).to_have_count(2)
                body_text_after_x = page.locator("body").inner_text()
                # relative order should remain
                assert body_text_after_x.find("loss") < body_text_after_x.find("acc")
            finally:
                # switch back to step to avoid flakiness for other tests
                xaxis.select_option("step")

            # But if we uncheck the run, the line plots should be hidden
            checkbox_label.locator("input[type='checkbox']").uncheck()
            locator = page.locator(".vega-embed")
            expect(locator).to_have_count(0)

            # re-check the run — layout/order should be preserved
            checkbox_label.locator("input[type='checkbox']").check()
            expect(page.locator(".vega-embed")).to_have_count(2)
            body_text_after = page.locator("body").inner_text()
            assert body_text_after.find("loss") < body_text_after.find("acc")

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
