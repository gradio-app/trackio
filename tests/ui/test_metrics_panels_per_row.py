from playwright.sync_api import expect, sync_playwright

import trackio


def _log_grouped_metrics(project):
    trackio.init(project=project, name="run_0")
    for s in range(5):
        metrics = {f"big/m{i}": float(s + i) for i in range(8)}
        metrics.update({f"small/m{i}": float(s + i) for i in range(3)})
        trackio.log(metrics=metrics)
    trackio.finish()


def _grid_cols(group):
    return group.locator(".plot-grid").first.evaluate(
        "el => getComputedStyle(el).getPropertyValue('--cols').trim()"
    )


def _set_plots_per_row(page, n):
    dropdown = page.locator(".dropdown-container", has_text="Plots per row")
    dropdown.locator("input").click()
    dropdown.locator("li.item", has_text=str(n)).click()


def test_plots_per_row_dropdown_sets_grid_columns(temp_dir):
    _log_grouped_metrics("test_ppr_columns")

    app, _, _, full_url = trackio.show(
        project="test_ppr_columns", block_thread=False, open_browser=False
    )

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1400, "height": 1000})
            page.set_default_timeout(5000)
            page.goto(full_url)
            page.wait_for_load_state("networkidle")

            big_group = page.locator(".accordion", has_text="big (8)")
            small_group = page.locator(".accordion", has_text="small (3)")
            expect(big_group.locator(".plot-container")).to_have_count(8)
            expect(small_group.locator(".plot-container")).to_have_count(3)

            # default is 4/row, capped to the group size
            assert _grid_cols(big_group) == "4"
            assert _grid_cols(small_group) == "3"

            _set_plots_per_row(page, 2)
            assert _grid_cols(big_group) == "2"
            assert _grid_cols(small_group) == "2"

            # a group with fewer panels than the setting stays capped
            _set_plots_per_row(page, 6)
            assert _grid_cols(big_group) == "6"
            assert _grid_cols(small_group) == "3"

            # every panel keeps rendering regardless of the layout
            expect(big_group.locator(".plot-container")).to_have_count(8)

            browser.close()
    finally:
        trackio.delete_project("test_ppr_columns", force=True)
        app.close()


def test_chart_resizes_when_plots_per_row_changes(temp_dir):
    _log_grouped_metrics("test_ppr_resize")

    app, _, _, full_url = trackio.show(
        project="test_ppr_resize", block_thread=False, open_browser=False
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

            _set_plots_per_row(page, 2)
            page.wait_for_timeout(500)

            after_box = container.bounding_box()
            after_canvas_width = canvas.bounding_box()["width"]

            # the canvas must actually grow with its (now wider) box, not
            # stay stuck at its old size
            assert after_canvas_width > before_width + 20
            assert abs(after_canvas_width - after_box["width"]) < 30

            browser.close()
    finally:
        trackio.delete_project("test_ppr_resize", force=True)
        app.close()
