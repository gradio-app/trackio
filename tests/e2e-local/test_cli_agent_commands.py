import json
import os
import subprocess
import sys

import pytest

import trackio

PROJECT = "cli_agent_test"
FILTER_PROJECT = "filter_test"


@pytest.fixture(scope="module")
def seeded(module_temp_dir):
    trackio.init(project=PROJECT, name="run-lr0.01", config={"lr": 0.01, "depth": 4})
    for step in range(10):
        trackio.log(
            {"val/loss": 1.0 - step * 0.08, "accuracy": 0.5 + step * 0.04}, step=step
        )
    trackio.finish()

    trackio.init(project=PROJECT, name="run-lr0.1", config={"lr": 0.1, "depth": 6})
    for step in range(10):
        trackio.log(
            {"val/loss": 1.5 - step * 0.05, "accuracy": 0.3 + step * 0.03}, step=step
        )
    trackio.finish()

    trackio.init(project=PROJECT, name="run-lr1.0", config={"lr": 1.0, "depth": 8})
    for step in range(5):
        trackio.log({"val/loss": 5.0 + step * 0.5, "accuracy": 0.1}, step=step)
    trackio.alert("Diverging", text="Loss too high", level=trackio.AlertLevel.ERROR)
    trackio.finish()

    trackio.init(project=FILTER_PROJECT, name="done-run", config={"lr": 0.01})
    for step in range(5):
        trackio.log({"val/loss": 1.0 - step * 0.1}, step=step)
    trackio.finish()

    trackio.init(project=FILTER_PROJECT, name="also-done", config={"lr": 0.1})
    for step in range(5):
        trackio.log({"val/loss": 2.0 - step * 0.1}, step=step)
    trackio.finish()

    trackio.init(project=FILTER_PROJECT, name="still-running", config={"lr": 1.0})
    for step in range(5):
        trackio.log({"val/loss": 5.0 + step * 0.5}, step=step)
    # Intentionally do NOT finish — tests status filtering for "still-running" runs.

    return module_temp_dir


def _cli(args, env_dir):
    env = os.environ.copy()
    env["TRACKIO_DIR"] = env_dir
    return subprocess.run(
        [sys.executable, "-m", "trackio.cli"] + args,
        capture_output=True,
        text=True,
        env=env,
    )


def test_best(seeded):
    r = _cli(["best", "--project", PROJECT, "--metric", "val/loss", "--json"], seeded)
    assert r.returncode == 0
    data = json.loads(r.stdout)
    assert data["best_run"] == "run-lr0.01"
    assert data["direction"] == "min"
    assert len(data["ranking"]) == 3
    for entry in data["ranking"]:
        assert {"value", "step", "config", "run"} <= entry.keys()

    r2 = _cli(
        [
            "best",
            "--project",
            PROJECT,
            "--metric",
            "accuracy",
            "--direction",
            "max",
            "--json",
        ],
        seeded,
    )
    assert r2.returncode == 0
    assert json.loads(r2.stdout)["best_run"] == "run-lr0.01"


def test_best_finished_filter(seeded):
    r = _cli(
        ["best", "--project", FILTER_PROJECT, "--metric", "val/loss", "--json"],
        seeded,
    )
    assert r.returncode == 0
    run_names = [e["run"] for e in json.loads(r.stdout)["ranking"]]
    assert "still-running" not in run_names
    assert len(run_names) == 2

    r2 = _cli(
        [
            "best",
            "--project",
            FILTER_PROJECT,
            "--metric",
            "val/loss",
            "--include-all",
            "--json",
        ],
        seeded,
    )
    assert r2.returncode == 0
    run_names2 = [e["run"] for e in json.loads(r2.stdout)["ranking"]]
    assert "still-running" in run_names2
    assert len(run_names2) == 3


def test_compare(seeded):
    r = _cli(
        ["compare", "--project", PROJECT, "--metrics", "val/loss,accuracy", "--json"],
        seeded,
    )
    assert r.returncode == 0
    data = json.loads(r.stdout)
    assert len(data["runs"]) == 3
    for run_entry in data["runs"]:
        assert {"val/loss", "accuracy"} <= run_entry["metrics"].keys()

    r2 = _cli(
        [
            "compare",
            "--project",
            PROJECT,
            "--runs",
            "run-lr0.01,run-lr0.1",
            "--metrics",
            "val/loss",
            "--json",
        ],
        seeded,
    )
    assert r2.returncode == 0
    assert len(json.loads(r2.stdout)["runs"]) == 2


def test_compare_finished_filter(seeded):
    r = _cli(
        ["compare", "--project", FILTER_PROJECT, "--metrics", "val/loss", "--json"],
        seeded,
    )
    assert r.returncode == 0
    run_names = [e["run"] for e in json.loads(r.stdout)["runs"]]
    assert "still-running" not in run_names
    assert len(run_names) == 2

    r2 = _cli(
        [
            "compare",
            "--project",
            FILTER_PROJECT,
            "--metrics",
            "val/loss",
            "--include-all",
            "--json",
        ],
        seeded,
    )
    assert r2.returncode == 0
    run_names2 = [e["run"] for e in json.loads(r2.stdout)["runs"]]
    assert "still-running" in run_names2
    assert len(run_names2) == 3


def test_summary(seeded):
    r = _cli(
        ["summary", "--project", PROJECT, "--metric", "val/loss", "--json"], seeded
    )
    assert r.returncode == 0
    data = json.loads(r.stdout)
    assert data["num_runs"] == 3
    assert data["total_alerts"] == 1
    for run_entry in data["runs"]:
        assert {
            "run",
            "status",
            "last_step",
            "num_logs",
            "config",
            "metric_value",
        } <= run_entry.keys()


def test_best_error_cases(seeded):
    r = _cli(["best", "--project", "nope", "--metric", "loss", "--json"], seeded)
    assert r.returncode != 0
    assert "not found" in r.stderr.lower()

    r = _cli(
        ["best", "--project", PROJECT, "--metric", "nonexistent", "--json"],
        seeded,
    )
    assert r.returncode != 0
    assert "no" in r.stderr.lower()


def test_best_human_format(seeded):
    r = _cli(["best", "--project", PROJECT, "--metric", "val/loss"], seeded)
    assert r.returncode == 0
    assert PROJECT in r.stdout
    assert "Best run:" in r.stdout
    assert "run-lr0.01" in r.stdout


def test_compare_human_format(seeded):
    r = _cli(
        ["compare", "--project", PROJECT, "--metrics", "val/loss,accuracy"], seeded
    )
    assert r.returncode == 0
    assert PROJECT in r.stdout
    assert "val/loss" in r.stdout
    assert "accuracy" in r.stdout


def test_summary_human_format(seeded):
    r = _cli(["summary", "--project", PROJECT, "--metric", "val/loss"], seeded)
    assert r.returncode == 0
    assert PROJECT in r.stdout
    assert "run-lr0.01" in r.stdout
