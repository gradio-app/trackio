from playwright.sync_api import expect, sync_playwright

import trackio


def _log_grouped_metrics(project):
    trackio.init(project=project, name="run_0")
    for s in range(5):
        metrics = {f"big/m{i}": float(s + i) for i in range(8)}
        metrics.update({f"small/m{i}": float(s + i) for i in range(3)})
        trackio.log(metrics=metrics)
    trackio.finish()


def test_panels_per_row_is_capped_to_group_size(temp_dir):
    _log_grouped_metrics("test_pagination_caps")

    app, _, _, full_url = trackio.show(
        project="test_pagination_caps", block_thread=False, open_browser=False
    )

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            page.set_default_timeout(5000)
            page.goto(full_url)
            page.wait_for_load_state("networkidle")

            small_group = page.locator(".accordion", has_text="small (3)")
            expect(small_group.locator(".plot-container")).to_have_count(3)

            # a 3-panel group must not offer a "4/row" (or higher) option
            options = small_group.locator("select.per-row-select option")
            expect(options).to_have_count(3)
            values = options.evaluate_all("els => els.map(e => e.value)")
            assert values == ["1", "2", "3"]

            browser.close()
    finally:
        trackio.delete_project("test_pagination_caps", force=True)
        app.close()


def test_row_pagination_shows_pages_of_panels(temp_dir):
    _log_grouped_metrics("test_pagination_pages")

    app, _, _, full_url = trackio.show(
        project="test_pagination_pages", block_thread=False, open_browser=False
    )

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            page.set_default_timeout(5000)
            page.goto(full_url)
            page.wait_for_load_state("networkidle")

            big_group = page.locator(".accordion", has_text="big (8)")

            # default: 4/row, all rows shown -> every panel visible
            expect(big_group.locator(".plot-container")).to_have_count(8)

            # switch to 1 row per page -> only the first 4 panels render
            big_group.locator("button.rows-button").click()
            big_group.get_by_role("button", name="1 row per page", exact=True).click()
            expect(big_group.locator(".plot-container")).to_have_count(4)
            first_page_titles = big_group.locator(".plot-title").all_inner_texts()

            next_button = big_group.locator("button.page-nav", has_text="›")
            prev_button = big_group.locator("button.page-nav", has_text="‹")
            expect(prev_button).to_be_disabled()

            next_button.click()
            expect(big_group.locator(".plot-container")).to_have_count(4)
            second_page_titles = big_group.locator(".plot-title").all_inner_texts()
            assert set(first_page_titles).isdisjoint(second_page_titles)
            expect(next_button).to_be_disabled()

            # "show all rows" restores every panel
            big_group.locator("button.rows-button").click()
            big_group.get_by_role("button", name="Show all rows", exact=True).click()
            expect(big_group.locator(".plot-container")).to_have_count(8)

            browser.close()
    finally:
        trackio.delete_project("test_pagination_pages", force=True)
        app.close()


def test_chart_resizes_when_panels_per_row_changes(temp_dir):
    _log_grouped_metrics("test_pagination_resize")

    app, _, _, full_url = trackio.show(
        project="test_pagination_resize", block_thread=False, open_browser=False
    )

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1400, "height": 1000})
            page.set_default_timeout(5000)
            page.goto(full_url)
            page.wait_for_load_state("networkidle")

            big_group = page.locator(".accordion", has_text="big (8)")
            container = big_group.locator(".plot-container").first
            canvas = container.locator("canvas")
            expect(canvas).to_be_visible()

            before_width = canvas.bounding_box()["width"]

            big_group.locator("select.per-row-select").select_option("2")
            page.wait_for_timeout(500)

            after_box = container.bounding_box()
            after_canvas_width = canvas.bounding_box()["width"]

            # the canvas must actually grow with its (now wider) box, not
            # stay stuck at its old size
            assert after_canvas_width > before_width + 20
            assert abs(after_canvas_width - after_box["width"]) < 30

            browser.close()
    finally:
        trackio.delete_project("test_pagination_resize", force=True)
        app.close()
