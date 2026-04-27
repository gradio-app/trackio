import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

import trackio
from trackio import context_vars

PROJECT = "cli_agent_test"


@pytest.fixture(scope="module")
def seeded_dir():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        import trackio.media.media as mm
        import trackio.media.utils as mu
        import trackio.sqlite_storage as ss
        import trackio.utils as tu

        orig_trackio = ss.TRACKIO_DIR
        orig_media = [mm.MEDIA_DIR, mu.MEDIA_DIR, tu.MEDIA_DIR, ss.MEDIA_DIR]
        ss.TRACKIO_DIR = Path(tmpdir)
        mm.MEDIA_DIR = mu.MEDIA_DIR = tu.MEDIA_DIR = ss.MEDIA_DIR = (
            Path(tmpdir) / "media"
        )

        context_vars.current_run.set(None)
        context_vars.current_project.set(None)
        context_vars.current_server.set(None)
        context_vars.current_space_id.set(None)

        trackio.init(
            project=PROJECT, name="run-lr0.01", config={"lr": 0.01, "depth": 4}
        )
        for step in range(10):
            trackio.log(
                {"val/loss": 1.0 - step * 0.08, "accuracy": 0.5 + step * 0.04},
                step=step,
            )
        trackio.finish()

        trackio.init(project=PROJECT, name="run-lr0.1", config={"lr": 0.1, "depth": 6})
        for step in range(10):
            trackio.log(
                {"val/loss": 1.5 - step * 0.05, "accuracy": 0.3 + step * 0.03},
                step=step,
            )
        trackio.finish()

        trackio.init(project=PROJECT, name="run-lr1.0", config={"lr": 1.0, "depth": 8})
        for step in range(5):
            trackio.log({"val/loss": 5.0 + step * 0.5, "accuracy": 0.1}, step=step)
        trackio.alert("Diverging", text="Loss too high", level=trackio.AlertLevel.ERROR)
        trackio.finish()

        context_vars.current_run.set(None)
        context_vars.current_project.set(None)
        context_vars.current_server.set(None)
        context_vars.current_space_id.set(None)

        yield tmpdir

        ss.TRACKIO_DIR = orig_trackio
        mm.MEDIA_DIR, mu.MEDIA_DIR, tu.MEDIA_DIR, ss.MEDIA_DIR = orig_media


def _cli(args, env_dir):
    env = os.environ.copy()
    env["TRACKIO_DIR"] = env_dir
    return subprocess.run(
        [sys.executable, "-m", "trackio.cli"] + args,
        capture_output=True,
        text=True,
        env=env,
    )


def test_best(seeded_dir):
    r = _cli(
        ["best", "--project", PROJECT, "--metric", "val/loss", "--json"], seeded_dir
    )
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
        seeded_dir,
    )
    assert r2.returncode == 0
    assert json.loads(r2.stdout)["best_run"] == "run-lr0.01"


def test_compare(seeded_dir):
    r = _cli(
        ["compare", "--project", PROJECT, "--metrics", "val/loss,accuracy", "--json"],
        seeded_dir,
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
        seeded_dir,
    )
    assert r2.returncode == 0
    assert len(json.loads(r2.stdout)["runs"]) == 2


def test_summary(seeded_dir):
    r = _cli(
        ["summary", "--project", PROJECT, "--metric", "val/loss", "--json"], seeded_dir
    )
    assert r.returncode == 0
    data = json.loads(r.stdout)
    assert data["num_runs"] == 3
    assert data["total_alerts"] >= 1
    for run_entry in data["runs"]:
        assert {
            "run",
            "status",
            "last_step",
            "num_logs",
            "config",
            "metric_value",
        } <= run_entry.keys()


def test_best_error_cases(seeded_dir):
    assert (
        _cli(
            ["best", "--project", "nope", "--metric", "loss", "--json"], seeded_dir
        ).returncode
        != 0
    )
    assert (
        _cli(
            ["best", "--project", PROJECT, "--metric", "nonexistent", "--json"],
            seeded_dir,
        ).returncode
        != 0
    )
