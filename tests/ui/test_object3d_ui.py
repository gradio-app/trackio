import numpy as np
from playwright.sync_api import expect, sync_playwright

import trackio


def test_object3d_cards_open_one_disposable_viewer(temp_dir):
    project = "test-object3d"
    run = trackio.init(project=project, name="viewer-run")
    direct = trackio.Object3D(
        np.array([[0, 0, 0, 255, 80, 40], [1, 1, 1, 40, 160, 255]]),
        caption="Direct cloud",
    )
    nested = trackio.Object3D(np.array([[0, 0, 0], [0, 1, 0], [1, 0, 0]]))
    run.log(
        {
            "cloud": direct,
            "samples": trackio.Table(columns=["model"], data=[[nested]]),
        }
    )
    run.finish()
    app, _, _, full_url = trackio.show(
        project=project, block_thread=False, open_browser=False
    )

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page()
            page.set_default_timeout(10_000)
            errors = []
            failed_requests = []
            page.on(
                "console",
                lambda message: errors.append(message.text)
                if message.type == "error"
                else None,
            )
            page.on(
                "requestfailed", lambda request: failed_requests.append(request.url)
            )
            page.goto(full_url)
            page.get_by_role("button", name="Media & Tables", exact=True).click()

            cards = page.locator(".object-card")
            expect(cards).to_have_count(2)
            expect(
                page.locator("canvas[aria-label='Interactive 3D scene']")
            ).to_have_count(0)

            direct_card = cards.filter(has_text="Direct cloud")
            direct_card.click()
            assert direct_card.evaluate(
                "element => element.classList.contains('selected')"
            )
            direct_card.press("Enter")
            expect(
                page.get_by_role("dialog", name="3D viewer for Direct cloud")
            ).to_be_visible()
            expect(
                page.locator("canvas[aria-label='Interactive 3D scene']")
            ).to_have_count(1)
            expect(page.locator(".status")).to_have_count(0)
            page.get_by_role("button", name="Grid", exact=True).click()
            page.get_by_role("button", name="Axes", exact=True).click()
            page.get_by_role("button", name="Reset camera", exact=True).click()
            page.get_by_role("button", name="Close 3D viewer", exact=True).click()
            expect(
                page.locator("canvas[aria-label='Interactive 3D scene']")
            ).to_have_count(0)

            cards.last.dblclick()
            expect(
                page.locator("canvas[aria-label='Interactive 3D scene']")
            ).to_have_count(1)
            page.keyboard.press("Escape")
            expect(
                page.locator("canvas[aria-label='Interactive 3D scene']")
            ).to_have_count(0)
            assert errors == []
            assert failed_requests == []
            browser.close()
    finally:
        trackio.delete_project(project, force=True)
        app.close()
