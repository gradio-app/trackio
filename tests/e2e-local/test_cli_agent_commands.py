import json
import os
import subprocess
import sys

import trackio

PROJECT = "cli_agent_test"
FILTER_PROJECT = "filter_test"


def _seed(temp_dir):
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

    return temp_dir


def _cli(args, env_dir):
    env = os.environ.copy()
    env["TRACKIO_DIR"] = env_dir
    return subprocess.run(
        [sys.executable, "-m", "trackio.cli"] + args,
        capture_output=True,
        text=True,
        env=env,
    )


def test_best(temp_dir):
    _seed(temp_dir)
    r = _cli(["best", "--project", PROJECT, "--metric", "val/loss", "--json"], temp_dir)
    assert r.returncode == 0
    data = json.loads(r.stdout)
    assert data["best_run"] == "run-lr0.01"
    assert data["direction"] == "min"
    assert len(data["ranking"]) == 3
    for entry in data["ranking"]:
        assert {"value", "step", "config", "run"} <= entry.keys()

    r2 = _cli(
        ["best", "--project", PROJECT, "--metric", "accuracy", "--direction", "max", "--json"],
        temp_dir,
    )
    assert r2.returncode == 0
    assert json.loads(r2.stdout)["best_run"] == "run-lr0.01"


def test_best_excludes_unfinished_by_default(temp_dir):
    _seed(temp_dir)
    r = _cli(
        ["best", "--project", FILTER_PROJECT, "--metric", "val/loss", "--json"], temp_dir
    )
    assert r.returncode == 0
    run_names = [e["run"] for e in json.loads(r.stdout)["ranking"]]
    assert "still-running" not in run_names
    assert len(run_names) == 2


def test_best_include_all(temp_dir):
    _seed(temp_dir)
    r = _cli(
        ["best", "--project", FILTER_PROJECT, "--metric", "val/loss", "--include-all", "--json"],
        temp_dir,
    )
    assert r.returncode == 0
    run_names = [e["run"] for e in json.loads(r.stdout)["ranking"]]
    assert "still-running" in run_names
    assert len(run_names) == 3


def test_compare(temp_dir):
    _seed(temp_dir)
    r = _cli(
        ["compare", "--project", PROJECT, "--metrics", "val/loss,accuracy", "--json"],
        temp_dir,
    )
    assert r.returncode == 0
    data = json.loads(r.stdout)
    assert len(data["runs"]) == 3
    for run_entry in data["runs"]:
        assert {"val/loss", "accuracy"} <= run_entry["metrics"].keys()

    r2 = _cli(
        ["compare", "--project", PROJECT, "--runs", "run-lr0.01,run-lr0.1", "--metrics", "val/loss", "--json"],
        temp_dir,
    )
    assert r2.returncode == 0
    assert len(json.loads(r2.stdout)["runs"]) == 2


def test_compare_excludes_unfinished_by_default(temp_dir):
    _seed(temp_dir)
    r = _cli(
        ["compare", "--project", FILTER_PROJECT, "--metrics", "val/loss", "--json"], temp_dir
    )
    assert r.returncode == 0
    run_names = [e["run"] for e in json.loads(r.stdout)["runs"]]
    assert "still-running" not in run_names
    assert len(run_names) == 2


def test_compare_include_all(temp_dir):
    _seed(temp_dir)
    r = _cli(
        ["compare", "--project", FILTER_PROJECT, "--metrics", "val/loss", "--include-all", "--json"],
        temp_dir,
    )
    assert r.returncode == 0
    run_names = [e["run"] for e in json.loads(r.stdout)["runs"]]
    assert "still-running" in run_names
    assert len(run_names) == 3


def test_summary(temp_dir):
    _seed(temp_dir)
    r = _cli(
        ["summary", "--project", PROJECT, "--metric", "val/loss", "--json"], temp_dir
    )
    assert r.returncode == 0
    data = json.loads(r.stdout)
    assert data["num_runs"] == 3
    assert data["total_alerts"] >= 1
    for run_entry in data["runs"]:
        assert {"run", "status", "last_step", "num_logs", "config", "metric_value"} <= run_entry.keys()


def test_list_runs_json_includes_status(temp_dir):
    _seed(temp_dir)
    r = _cli(["list", "runs", "--project", PROJECT, "--json"], temp_dir)
    assert r.returncode == 0
    data = json.loads(r.stdout)
    assert "runs" in data
    for entry in data["runs"]:
        assert "name" in entry
        assert "status" in entry
    statuses = {e["name"]: e["status"] for e in data["runs"]}
    assert statuses.get("run-lr0.01") == "finished"
    assert statuses.get("run-lr0.1") == "finished"
    assert statuses.get("run-lr1.0") == "finished"


def test_best_error_cases(temp_dir):
    _seed(temp_dir)
    assert _cli(["best", "--project", "nope", "--metric", "loss", "--json"], temp_dir).returncode != 0
    assert _cli(["best", "--project", PROJECT, "--metric", "nonexistent", "--json"], temp_dir).returncode != 0
