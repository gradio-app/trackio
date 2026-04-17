from trackio import server, utils
from trackio.run import Run
from trackio.table import Table


def test_get_settings_default_values(monkeypatch):
    monkeypatch.delenv("TRACKIO_LOGO_LIGHT_URL", raising=False)
    monkeypatch.delenv("TRACKIO_LOGO_DARK_URL", raising=False)
    monkeypatch.delenv("TRACKIO_COLOR_PALETTE", raising=False)
    monkeypatch.delenv("TRACKIO_PLOT_ORDER", raising=False)
    monkeypatch.delenv("TRACKIO_TABLE_TRUNCATE_LENGTH", raising=False)

    result = server.get_settings()

    assert "light" in result["logo_urls"]
    assert "dark" in result["logo_urls"]
    assert result["color_palette"] == utils.DEFAULT_COLOR_PALETTE
    assert result["plot_order"] == []
    assert result["table_truncate_length"] == 250


def test_custom_logos(monkeypatch):
    monkeypatch.setenv("TRACKIO_LOGO_LIGHT_URL", "https://example.com/light.png")
    monkeypatch.setenv("TRACKIO_LOGO_DARK_URL", "https://example.com/dark.png")
    result = utils.get_logo_urls()
    assert result["light"] == "https://example.com/light.png"
    assert result["dark"] == "https://example.com/dark.png"


def test_truncate_length_in_table_display(monkeypatch):
    monkeypatch.setenv("TRACKIO_TABLE_TRUNCATE_LENGTH", "10")
    long_text = "A" * 50
    table_data = [{"col": long_text}]
    result = Table.to_display_format(table_data)
    assert "truncated" in result[0]["col"]
    assert long_text != result[0]["col"]


def test_truncate_length_short_text_not_truncated(monkeypatch):
    monkeypatch.setenv("TRACKIO_TABLE_TRUNCATE_LENGTH", "100")
    short_text = "hello"
    table_data = [{"col": short_text}]
    result = Table.to_display_format(table_data)
    assert result[0]["col"] == short_text


def test_resolve_space_id_and_server_url_space_env_wins_over_server_env(monkeypatch):
    monkeypatch.setenv("TRACKIO_SPACE_ID", "user/repo")
    monkeypatch.setenv("TRACKIO_SERVER_URL", "http://127.0.0.1:7860/")
    assert utils.resolve_space_id_and_server_url(None, None) == ("user/repo", None)


def test_resolve_space_id_and_server_url_explicit_space_wins_over_server_arg(
    monkeypatch,
):
    monkeypatch.delenv("TRACKIO_SPACE_ID", raising=False)
    monkeypatch.delenv("TRACKIO_SERVER_URL", raising=False)
    assert utils.resolve_space_id_and_server_url("a/b", "http://127.0.0.1:1/") == (
        "a/b",
        None,
    )


def test_resolve_space_id_and_server_url_server_only(monkeypatch):
    monkeypatch.delenv("TRACKIO_SPACE_ID", raising=False)
    monkeypatch.delenv("TRACKIO_SERVER_URL", raising=False)
    assert utils.resolve_space_id_and_server_url(None, "http://127.0.0.1:9/") == (
        None,
        "http://127.0.0.1:9/",
    )


def test_webhook_url_from_env(monkeypatch, temp_dir):
    monkeypatch.setenv("TRACKIO_WEBHOOK_URL", "https://hooks.slack.com/test")
    monkeypatch.delenv("TRACKIO_WEBHOOK_MIN_LEVEL", raising=False)
    run = Run(
        url=None,
        project="test-project",
        client=None,
        name="test-run",
    )
    assert run._webhook_url == "https://hooks.slack.com/test"
    run.finish()
