import sys

from trackio import cli


def test_report_init_cli(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "trackio",
            "report",
            "init",
            "--space-id",
            "abidlabs/report",
            "--bucket-id",
            "abidlabs/report-bucket",
        ],
    )

    cli.main()

    captured = capsys.readouterr()
    assert "Initialized Trackio Report workspace." in captured.out
    assert (tmp_path / "REPORTS.md").exists()
    assert (tmp_path / ".trackio" / "config.toml").exists()


def test_report_validate_cli_exits_nonzero_for_invalid_report(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["trackio", "report", "validate"])

    try:
        cli.main()
    except SystemExit as e:
        assert e.code == 1
    else:
        raise AssertionError("Expected report validate to exit with status 1")
