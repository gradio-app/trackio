from urllib.parse import urlencode, urlparse, urlunparse

from playwright.sync_api import expect, sync_playwright

import trackio


def _url_with_query(base_url: str, params: dict[str, str]) -> str:
    parsed = urlparse(base_url)
    path = parsed.path if parsed.path else "/"
    query = urlencode(params)
    return urlunparse((parsed.scheme, parsed.netloc, path, "", query, ""))


def test_share_view_query_params_apply(temp_dir):
    project = "test_share_qp"
    run_ids_by_name: dict[str, list[str]] = {}
    for name in ("run-alpha", "run-beta", "run-alpha"):
        run = trackio.init(project=project, name=name)
        run_ids_by_name.setdefault(name, []).append(run.id)
        for _ in range(3):
            trackio.log(metrics={"loss": 0.1, "accuracy": 0.9})
        trackio.finish()

    alpha_ids = run_ids_by_name["run-alpha"]
    assert len(alpha_ids) == 2

    app, _, _, full_url = trackio.show(
        project=project, block_thread=False, open_browser=False
    )

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            page.set_default_timeout(15000)

            primary = _url_with_query(
                full_url,
                {
                    "project": project,
                    "run_ids": alpha_ids[0],
                    "metric_filter": "^loss$",
                    "sidebar": "hidden",
                    "navbar": "hidden",
                    "accordion": "hidden",
                },
            )
            page.goto(primary)
            page.wait_for_load_state("networkidle")

            expect(page.locator(".navbar")).to_have_count(0)
            expect(page.locator(".sidebar")).to_have_count(0)
            expect(page.locator(".accordion")).to_have_count(0)

            expect(page.locator(".metrics-page")).to_be_visible()
            expect(page.locator(".vega-embed")).to_have_count(1)
            expect(page.locator(".metrics-page .legend-dot")).to_have_count(1)

            duplicate = _url_with_query(
                full_url,
                {
                    "project": project,
                    "run_ids": ",".join(alpha_ids),
                    "metric_filter": "^loss$",
                    "sidebar": "hidden",
                    "navbar": "hidden",
                    "accordion": "hidden",
                },
            )
            page.goto(duplicate)
            page.wait_for_load_state("networkidle")

            expect(page.locator(".metrics-page")).to_be_visible()
            expect(page.locator(".vega-embed")).to_have_count(1)
            expect(page.locator(".metrics-page .legend-dot")).to_have_count(2)

            legacy = _url_with_query(
                full_url,
                {
                    "project": project,
                    "runs": "run-beta",
                    "metrics": "loss",
                    "sidebar": "hidden",
                    "navbar": "hidden",
                    "accordion": "hidden",
                },
            )
            page.goto(legacy)
            page.wait_for_load_state("networkidle")

            expect(page.locator(".navbar")).to_have_count(0)
            expect(page.locator(".vega-embed")).to_have_count(1)
            expect(page.locator(".metrics-page .legend-dot")).to_have_count(1)

            browser.close()
    finally:
        trackio.delete_project(project, force=True)
        app.close()
