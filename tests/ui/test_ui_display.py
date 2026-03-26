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
            page.goto(url if url.endswith("/") else url + "/")
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

            checkbox.check()
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


def test_latest_only_selects_last_run(temp_dir):
    for i in range(3):
        trackio.init(project="test_latest", name=f"run-{i}")
        trackio.log(metrics={"loss": 0.1 * (i + 1)})
        trackio.finish()

    app, url, _, _ = trackio.show(block_thread=False, open_browser=False)

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            page.set_default_timeout(5000)
            page.goto(url if url.endswith("/") else url + "/")
            page.wait_for_load_state("networkidle")

            checkboxes = page.locator(".checkbox-item input[type='checkbox']")
            expect(checkboxes).to_have_count(3)
            for i in range(3):
                expect(checkboxes.nth(i)).to_be_checked()

            latest_toggle = page.locator(".latest-toggle input[type='checkbox']")
            latest_toggle.check()

            expect(checkboxes.nth(0)).not_to_be_checked()
            expect(checkboxes.nth(1)).not_to_be_checked()
            expect(checkboxes.nth(2)).to_be_checked()

            browser.close()
    finally:
        trackio.delete_project("test_latest", force=True)
        app.close()


def test_navbar_page_navigation(temp_dir):
    trackio.init(project="test_nav", name="nav_run")
    trackio.log(metrics={"loss": 0.5})
    trackio.finish()

    app, url, _, _ = trackio.show(block_thread=False, open_browser=False)

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            page.set_default_timeout(5000)
            page.goto(url if url.endswith("/") else url + "/")
            page.wait_for_load_state("networkidle")

            expect(page.locator(".metrics-page")).to_be_visible()

            page.locator(".nav-link", has_text="System Metrics").click()
            page.wait_for_load_state("networkidle")
            expect(page.locator(".system-page")).to_be_visible()

            page.locator(".nav-link", has_text="Runs").click()
            page.wait_for_load_state("networkidle")
            expect(page.locator(".runs-page")).to_be_visible()

            page.locator(".nav-link", has_text="Reports").click()
            page.wait_for_load_state("networkidle")
            expect(page.locator(".reports-page")).to_be_visible()

            browser.close()
    finally:
        trackio.delete_project("test_nav", force=True)
        app.close()


def test_runs_table_shows_run_data(temp_dir):
    trackio.init(project="test_runs_table", name="my-run")
    for i in range(5):
        trackio.log(metrics={"loss": 1.0 / (i + 1)})
    trackio.finish()

    app, url, _, _ = trackio.show(block_thread=False, open_browser=False)

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            page.set_default_timeout(5000)
            page.goto(url if url.endswith("/") else url + "/")
            page.wait_for_load_state("networkidle")

            page.locator(".nav-link", has_text="Runs").click()
            page.wait_for_load_state("networkidle")

            table = page.locator(".runs-table")
            expect(table).to_be_visible()

            row = table.locator("tbody tr")
            expect(row).to_have_count(1)
            expect(row.locator("td", has_text="my-run")).to_be_visible()

            browser.close()
    finally:
        trackio.delete_project("test_runs_table", force=True)
        app.close()


def test_multiple_runs_display_multiple_plots(temp_dir):
    for i in range(2):
        trackio.init(project="test_multi", name=f"run-{i}")
        for j in range(5):
            trackio.log(metrics={"loss": 0.1 * (j + 1), "acc": 0.9 - 0.1 * j})
        trackio.log(metrics={"val_loss": 0.05 * (i + 1)})
        trackio.finish()

    app, url, _, _ = trackio.show(block_thread=False, open_browser=False)

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            page.set_default_timeout(5000)
            page.goto(url if url.endswith("/") else url + "/")
            page.wait_for_load_state("networkidle")

            run_items = page.locator(".checkbox-item")
            expect(run_items).to_have_count(2)

            plots = page.locator(".vega-embed")
            expect(plots).to_have_count(3)

            line_marks = page.locator(".vega-embed .mark-line.role-mark")
            expect(line_marks.first).to_be_visible()

            bar_plots = page.locator(".bar-plot")
            expect(bar_plots).to_have_count(1)
            bar_vega = bar_plots.first.locator(".vega-embed")
            expect(bar_vega).to_be_visible()

            runs_label = page.get_by_text("Runs (2)", exact=True)
            expect(runs_label).to_be_visible()

            browser.close()
    finally:
        trackio.delete_project("test_multi", force=True)
        app.close()
