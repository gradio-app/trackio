import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

import trackio
from trackio import context_vars


@pytest.fixture
def cli_temp_dir(monkeypatch):
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        monkeypatch.setenv("TRACKIO_DIR", tmpdir)
        for name in ["trackio.sqlite_storage"]:
            monkeypatch.setattr(f"{name}.TRACKIO_DIR", Path(tmpdir))
        for name in [
            "trackio.media.media",
            "trackio.media.utils",
            "trackio.utils",
            "trackio.sqlite_storage",
        ]:
            monkeypatch.setattr(f"{name}.MEDIA_DIR", Path(tmpdir) / "media")
        context_vars.current_run.set(None)
        context_vars.current_project.set(None)
        context_vars.current_server.set(None)
        context_vars.current_space_id.set(None)
        yield tmpdir
        context_vars.current_run.set(None)
        context_vars.current_project.set(None)
        context_vars.current_server.set(None)
        context_vars.current_space_id.set(None)


def _run_cli(args, env_dir):
    env = os.environ.copy()
    env["TRACKIO_DIR"] = env_dir
    result = subprocess.run(
        [sys.executable, "-m", "trackio.cli"] + args,
        capture_output=True,
        text=True,
        env=env,
    )
    return result


def _seed_project(project, temp_dir):
    trackio.init(project=project, name="run-lr0.01", config={"lr": 0.01, "depth": 4})
    for step in range(10):
        trackio.log(
            {"val/loss": 1.0 - step * 0.08, "accuracy": 0.5 + step * 0.04}, step=step
        )
    trackio.finish()

    trackio.init(project=project, name="run-lr0.1", config={"lr": 0.1, "depth": 6})
    for step in range(10):
        trackio.log(
            {"val/loss": 1.5 - step * 0.05, "accuracy": 0.3 + step * 0.03}, step=step
        )
    trackio.finish()

    trackio.init(project=project, name="run-lr1.0", config={"lr": 1.0, "depth": 8})
    for step in range(5):
        trackio.log({"val/loss": 5.0 + step * 0.5, "accuracy": 0.1}, step=step)
    trackio.alert("Diverging", text="Loss too high", level=trackio.AlertLevel.ERROR)
    trackio.finish()


def test_best_json(cli_temp_dir):
    _seed_project("cli_best", cli_temp_dir)
    result = _run_cli(
        ["best", "--project", "cli_best", "--metric", "val/loss", "--json"],
        cli_temp_dir,
    )
    assert result.returncode == 0

    data = json.loads(result.stdout)
    assert data["project"] == "cli_best"
    assert data["metric"] == "val/loss"
    assert data["direction"] == "min"
    assert data["best_run"] == "run-lr0.01"
    assert "ranking" in data
    assert len(data["ranking"]) == 3
    assert data["ranking"][0]["run"] == "run-lr0.01"
    for entry in data["ranking"]:
        assert "value" in entry
        assert "step" in entry
        assert "config" in entry


def test_best_maximize(cli_temp_dir):
    _seed_project("cli_best_max", cli_temp_dir)
    result = _run_cli(
        [
            "best",
            "--project",
            "cli_best_max",
            "--metric",
            "accuracy",
            "--direction",
            "max",
            "--json",
        ],
        cli_temp_dir,
    )
    assert result.returncode == 0

    data = json.loads(result.stdout)
    assert data["direction"] == "max"
    assert data["best_run"] == "run-lr0.01"


def test_best_human_readable(cli_temp_dir):
    _seed_project("cli_best_hr", cli_temp_dir)
    result = _run_cli(
        ["best", "--project", "cli_best_hr", "--metric", "val/loss"], cli_temp_dir
    )
    assert result.returncode == 0
    assert "Best run:" in result.stdout
    assert "run-lr0.01" in result.stdout
    assert "Ranking" in result.stdout


def test_compare_json(cli_temp_dir):
    _seed_project("cli_compare", cli_temp_dir)
    result = _run_cli(
        [
            "compare",
            "--project",
            "cli_compare",
            "--metrics",
            "val/loss,accuracy",
            "--json",
        ],
        cli_temp_dir,
    )
    assert result.returncode == 0

    data = json.loads(result.stdout)
    assert data["project"] == "cli_compare"
    assert len(data["runs"]) == 3
    for run_entry in data["runs"]:
        assert "run" in run_entry
        assert "config" in run_entry
        assert "metrics" in run_entry
        assert "val/loss" in run_entry["metrics"]
        assert "accuracy" in run_entry["metrics"]


def test_compare_subset_runs(cli_temp_dir):
    _seed_project("cli_compare_sub", cli_temp_dir)
    result = _run_cli(
        [
            "compare",
            "--project",
            "cli_compare_sub",
            "--runs",
            "run-lr0.01,run-lr0.1",
            "--metrics",
            "val/loss",
            "--json",
        ],
        cli_temp_dir,
    )
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert len(data["runs"]) == 2


def test_compare_human_readable(cli_temp_dir):
    _seed_project("cli_compare_hr", cli_temp_dir)
    result = _run_cli(
        [
            "compare",
            "--project",
            "cli_compare_hr",
            "--metrics",
            "val/loss,accuracy",
        ],
        cli_temp_dir,
    )
    assert result.returncode == 0
    assert "Comparing 3 runs" in result.stdout
    assert "run-lr0.01" in result.stdout


def test_summary_json(cli_temp_dir):
    _seed_project("cli_summary", cli_temp_dir)
    result = _run_cli(
        [
            "summary",
            "--project",
            "cli_summary",
            "--metric",
            "val/loss",
            "--json",
        ],
        cli_temp_dir,
    )
    assert result.returncode == 0

    data = json.loads(result.stdout)
    assert data["project"] == "cli_summary"
    assert data["num_runs"] == 3
    assert data["total_alerts"] >= 1
    assert data["metric"] == "val/loss"
    assert len(data["runs"]) == 3
    for run_entry in data["runs"]:
        assert "run" in run_entry
        assert "status" in run_entry
        assert "last_step" in run_entry
        assert "num_logs" in run_entry
        assert "config" in run_entry
        assert "metric_value" in run_entry


def test_summary_human_readable(cli_temp_dir):
    _seed_project("cli_summary_hr", cli_temp_dir)
    result = _run_cli(
        ["summary", "--project", "cli_summary_hr", "--metric", "val/loss"],
        cli_temp_dir,
    )
    assert result.returncode == 0
    assert "Total runs: 3" in result.stdout
    assert "run-lr0.01" in result.stdout


def test_best_nonexistent_project(cli_temp_dir):
    result = _run_cli(
        ["best", "--project", "nope", "--metric", "loss", "--json"], cli_temp_dir
    )
    assert result.returncode != 0


def test_best_nonexistent_metric(cli_temp_dir):
    _seed_project("cli_no_metric", cli_temp_dir)
    result = _run_cli(
        ["best", "--project", "cli_no_metric", "--metric", "nonexistent", "--json"],
        cli_temp_dir,
    )
    assert result.returncode != 0
