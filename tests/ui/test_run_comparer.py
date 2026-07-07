from playwright.sync_api import expect, sync_playwright

import trackio


def test_run_comparer_diff_and_search(temp_dir):
    """Two runs differing only in lr: the comparer starts collapsed, shows both
    configs side by side, and filters rows via key search and Diff only."""
    for name, lr, losses in [
        ("run-a", 0.01, [0.5, 0.4, 0.3]),
        ("run-b", 0.02, [0.4, 0.3, 0.2]),
    ]:
        trackio.init(
            project="test_comparer",
            name=name,
            config={
                "lr": lr,
                "seed": 42,
                "optimizer": {"name": "adam", "eps": 1e-8},
            },
        )
        for loss in losses:
            trackio.log(metrics={"loss": loss})
        trackio.finish()

    app, _, _, full_url = trackio.show(
        project="test_comparer", block_thread=False, open_browser=False
    )

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            page.set_default_timeout(5000)
            page.goto(full_url)
            page.wait_for_load_state("networkidle")

            header = page.locator(".run-comparer .accordion-header")
            expect(header).to_be_visible()
            expect(page.locator(".comparer-table")).to_have_count(0)

            header.click()
            table = page.locator(".comparer-table")
            expect(table).to_be_visible()

            run_names = table.locator(".run-header .run-name")
            expect(run_names).to_have_count(2)
            expect(run_names.filter(has_text="run-a")).to_have_count(1)
            expect(run_names.filter(has_text="run-b")).to_have_count(1)

            expect(
                table.locator("td.key-col", has_text="optimizer.name")
            ).to_be_visible()
            expect(table.locator("td.key-col", has_text="Created")).to_have_count(1)

            lr_row = table.locator("tbody tr").filter(
                has=page.locator("td.key-col", has_text="lr")
            )
            lr_cells = lr_row.locator("td.value-cell")
            expect(lr_cells).to_have_count(2)
            expect(lr_cells.filter(has_text="0.01")).to_have_count(1)
            expect(lr_cells.filter(has_text="0.02")).to_have_count(1)
            expect(lr_row.locator(".copy-btn")).to_have_count(2)

            search = page.locator(".comparer-search input")
            search.fill("lr")
            expect(table.locator("td.key-col", has_text="seed")).to_have_count(0)
            expect(table.locator("td.key-col", has_text="lr")).to_have_count(1)
            search.fill("")

            diff_toggle = page.locator(".comparer-controls input[type='checkbox']")
            diff_toggle.check()
            expect(table.locator("td.key-col", has_text="seed")).to_have_count(0)
            expect(table.locator("td.key-col", has_text="optimizer.eps")).to_have_count(
                0
            )
            expect(
                table.locator("tbody tr.differs").filter(
                    has=page.locator("td.key-col", has_text="lr")
                )
            ).to_have_count(1)

            browser.close()
    finally:
        trackio.delete_project("test_comparer", force=True)
        app.close()
