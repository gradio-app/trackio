from contextlib import contextmanager

from playwright.sync_api import sync_playwright

import trackio


@contextmanager
def _dashboard_page(*projects):
    for project in projects:
        trackio.init(project=project, name="run")
        trackio.log(metrics={"loss": 0.5})
        trackio.finish()
    app, _, _, url = trackio.show(
        project=projects[0], block_thread=False, open_browser=False
    )
    try:
        with sync_playwright() as p:
            page = p.chromium.launch().new_page()
            page.set_default_timeout(5000)
            page.clock.install()
            yield page, url
    finally:
        app.close()
        for project in projects:
            trackio.delete_project(project, force=True)


def _hold(page, pattern):
    held = []
    page.route(pattern, lambda route: held.append(route))
    return held


def test_dashboard_polls_wait_for_slow_requests_until_they_time_out(temp_dir):
    with _dashboard_page("test_slow_polls") as (page, url):
        with page.expect_response("**/api/get_tab_availability"):
            page.goto(url)
        held = _hold(page, "**/api/get_all_projects")

        with page.expect_request("**/api/get_all_projects"):
            page.clock.run_for(5000)
        page.wait_for_timeout(500)
        assert len(held) == 1

        with page.expect_request("**/api/get_all_projects"):
            page.clock.run_for(30000)


def test_dashboard_requests_projects_without_waiting_for_settings(temp_dir):
    with _dashboard_page("test_slow_settings") as (page, url):
        _hold(page, "**/api/get_settings")
        requested = []
        page.on("request", lambda request: requested.append(request.url))

        with page.expect_request("**/api/get_all_projects"):
            page.goto(url)
        page.wait_for_timeout(500)

        assert not any("/config.json" in u for u in requested)
        assert not any("/api/get_runs_for_project" in u for u in requested)


def test_dashboard_finishes_startup_without_waiting_for_alerts(temp_dir):
    with _dashboard_page("test_slow_alerts") as (page, url):
        _hold(page, "**/api/get_alerts")

        with page.expect_request("**/api/get_tab_availability"):
            page.goto(url)


def test_dashboard_loads_runs_once_and_aborts_them_on_project_switch(temp_dir):
    with _dashboard_page("test_switch_a", "test_switch_b") as (page, url):
        _hold(page, "**/api/get_tab_availability")
        runs = _hold(page, "**/api/get_runs_for_project")

        with page.expect_request("**/api/get_runs_for_project"):
            page.goto(url)
        with page.expect_request("**/api/get_runs_for_project"):
            page.evaluate(
                "history.pushState({}, '', '?project=test_switch_b');"
                "dispatchEvent(new PopStateEvent('popstate'))"
            )
        page.wait_for_timeout(500)

        assert [r.request.post_data_json["project"] for r in runs] == [
            "test_switch_a",
            "test_switch_b",
        ]
        assert [r.request.failure for r in runs] == ["net::ERR_ABORTED", None]
