import threading
from pathlib import Path

import pytest

import trackio
from trackio.sqlite_storage import SQLiteStorage


def grid_config():
    return {
        "method": "grid",
        "metric": {"name": "loss", "goal": "minimize"},
        "parameters": {
            "lr": {"values": [0.1, 0.01]},
            "batch_size": {"values": [8, 16]},
        },
    }


def test_grid_sweep_runs_every_cell_once(temp_dir):
    sweep_id = trackio.sweep(grid_config(), project="proj")
    seen = []

    def train():
        run = trackio.init(project="proj")
        seen.append((run.config["lr"], run.config["batch_size"]))
        trackio.log({"loss": run.config["lr"] * run.config["batch_size"]})
        trackio.finish()

    trackio.agent(sweep_id, function=train, project="proj")

    assert sorted(seen) == sorted([(0.1, 8), (0.1, 16), (0.01, 8), (0.01, 16)])
    sweep = SQLiteStorage.get_sweep("proj", sweep_id)
    assert sweep["state"] == "finished"
    assert sweep["num_trials"] == 4
    assert sweep["trial_counts"] == {"finished": 4}
    assert sweep["best_metric_value"] == pytest.approx(0.08)


def test_sweep_params_override_init_config(temp_dir):
    sweep_id = trackio.sweep(
        {"method": "grid", "parameters": {"lr": {"values": [0.5]}}},
        project="proj",
    )
    captured = {}

    def train():
        run = trackio.init(project="proj", config={"lr": 999, "epochs": 3})
        captured.update(run.config)
        trackio.finish()

    trackio.agent(sweep_id, function=train, project="proj")
    assert captured["lr"] == 0.5
    assert captured["epochs"] == 3


def test_run_config_records_sweep_id(temp_dir):
    sweep_id = trackio.sweep(
        {"method": "grid", "parameters": {"lr": {"values": [0.5]}}},
        project="proj",
    )
    run_ids = []

    def train():
        run = trackio.init(project="proj")
        assert run.sweep_id == sweep_id
        run_ids.append(run.id)
        trackio.log({"loss": 1.0})
        trackio.finish()

    trackio.agent(sweep_id, function=train, project="proj")
    config = SQLiteStorage.get_run_config("proj", None, run_id=run_ids[0])
    assert config["_Sweep"] == sweep_id


def test_run_outside_sweep_has_no_sweep_id(temp_dir):
    run = trackio.init(project="proj")
    assert run.sweep_id is None
    trackio.finish()


def test_agent_count_limits_trials(temp_dir):
    sweep_id = trackio.sweep(grid_config(), project="proj")
    calls = []

    def train():
        trackio.init(project="proj")
        calls.append(1)
        trackio.finish()

    trackio.agent(sweep_id, function=train, project="proj", count=2)
    assert len(calls) == 2
    assert SQLiteStorage.get_sweep("proj", sweep_id)["state"] == "running"


def test_agent_accepts_qualified_sweep_id(temp_dir):
    sweep_id = trackio.sweep(
        {"method": "grid", "parameters": {"lr": {"values": [0.5]}}},
        project="proj",
    )
    calls = []

    def train():
        trackio.init(project="proj")
        calls.append(1)
        trackio.finish()

    trackio.agent(f"proj/{sweep_id}", function=train)
    assert len(calls) == 1


def test_agent_requires_function(temp_dir):
    sweep_id = trackio.sweep(
        {"method": "grid", "parameters": {"lr": {"values": [0.5]}}},
        project="proj",
    )
    with pytest.raises(ValueError, match="function-based"):
        trackio.agent(sweep_id, project="proj")


def test_agent_rejects_function_for_command_sweep(temp_dir):
    sweep_id = trackio.sweep(
        {
            "method": "grid",
            "program": "train.py",
            "parameters": {"lr": {"values": [0.5]}},
        },
        project="proj",
    )
    with pytest.raises(ValueError, match="command-based"):
        trackio.agent(sweep_id, function=lambda: None, project="proj")


def test_agent_marks_failed_trials_and_aborts(temp_dir):
    sweep_id = trackio.sweep(
        {
            "method": "grid",
            "parameters": {"lr": {"values": [1, 2, 3, 4, 5]}},
        },
        project="proj",
    )

    def train():
        trackio.init(project="proj")
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="consecutive failed trials"):
        trackio.agent(sweep_id, function=train, project="proj")

    trials = SQLiteStorage.get_sweep_trials("proj", sweep_id)
    assert len(trials) == 3
    assert all(t["state"] == "failed" for t in trials)


def test_agent_recovers_after_single_failure(temp_dir):
    sweep_id = trackio.sweep(
        {"method": "grid", "parameters": {"lr": {"values": [1, 2]}}},
        project="proj",
    )
    calls = []

    def train():
        trackio.init(project="proj")
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("flaky")
        trackio.log({"loss": 1.0})
        trackio.finish()

    trackio.agent(sweep_id, function=train, project="proj")
    trials = SQLiteStorage.get_sweep_trials("proj", sweep_id)
    states = sorted(t["state"] for t in trials)
    assert states == ["failed", "finished"]


def test_function_without_init_still_finishes_trial(temp_dir):
    sweep_id = trackio.sweep(
        {"method": "grid", "parameters": {"lr": {"values": [0.5]}}},
        project="proj",
    )

    def train():
        pass

    trackio.agent(sweep_id, function=train, project="proj")
    trials = SQLiteStorage.get_sweep_trials("proj", sweep_id)
    assert trials[0]["state"] == "finished"


TRAIN_SCRIPT = """\
import argparse
import os

import trackio

parser = argparse.ArgumentParser()
parser.add_argument("--lr", type=float, required=True)
args = parser.parse_args()

assert os.environ.get("TRACKIO_SWEEP_ID")
assert os.environ.get("TRACKIO_SWEEP_TRIAL_ID")

run = trackio.init(project="proj")
assert run.config["lr"] == args.lr
trackio.log({"loss": args.lr * 2})
trackio.finish()
"""


def test_command_mode_agent_end_to_end(temp_dir, monkeypatch):
    monkeypatch.setenv("TRACKIO_DIR", temp_dir)
    script = Path(temp_dir) / "train_script.py"
    script.write_text(TRAIN_SCRIPT)
    sweep_id = trackio.sweep(
        {
            "method": "grid",
            "metric": {"name": "loss", "goal": "minimize"},
            "program": str(script),
            "parameters": {"lr": {"values": [0.5, 0.25]}},
        },
        project="proj",
    )

    trackio.agent(sweep_id, project="proj")

    sweep = SQLiteStorage.get_sweep("proj", sweep_id)
    assert sweep["state"] == "finished"
    trials = SQLiteStorage.get_sweep_trials("proj", sweep_id)
    assert len(trials) == 2
    assert all(t["state"] == "finished" for t in trials)
    assert all(t["run_id"] for t in trials)
    assert sorted(t["metric_value"] for t in trials) == [0.5, 1.0]
    assert sweep["best_metric_value"] == 0.5


def test_command_mode_nonzero_exit_marks_trial_failed(temp_dir, monkeypatch):
    monkeypatch.setenv("TRACKIO_DIR", temp_dir)
    script = Path(temp_dir) / "crash_script.py"
    script.write_text("import sys\nsys.exit(1)\n")
    sweep_id = trackio.sweep(
        {
            "method": "grid",
            "program": str(script),
            "parameters": {"lr": {"values": [0.5]}},
        },
        project="proj",
    )

    trackio.agent(sweep_id, project="proj")

    trials = SQLiteStorage.get_sweep_trials("proj", sweep_id)
    assert len(trials) == 1
    assert trials[0]["state"] == "failed"
    assert SQLiteStorage.get_sweep("proj", sweep_id)["state"] == "finished"


def test_command_mode_crash_after_init_marks_trial_failed(temp_dir, monkeypatch):
    monkeypatch.setenv("TRACKIO_DIR", temp_dir)
    script = Path(temp_dir) / "crash_after_init.py"
    script.write_text(
        "import trackio\n"
        'trackio.init(project="proj")\n'
        'trackio.log({"loss": 1.0})\n'
        'raise RuntimeError("boom")\n'
    )
    sweep_id = trackio.sweep(
        {
            "method": "grid",
            "program": str(script),
            "metric": {"name": "loss", "goal": "minimize", "target": 2.0},
            "parameters": {"lr": {"values": [0.5]}},
        },
        project="proj",
    )

    trackio.agent(sweep_id, project="proj")

    trials = SQLiteStorage.get_sweep_trials("proj", sweep_id)
    assert len(trials) == 1
    assert trials[0]["state"] == "failed"
    assert SQLiteStorage.get_sweep("proj", sweep_id)["finish_reason"] != "target"


def test_trial_child_env_includes_metric_and_context(temp_dir):
    from trackio.sweep_agent import SweepClient, _trial_child_env

    client = SweepClient("proj")
    env = _trial_child_env(
        {"metric": {"name": "loss", "goal": "minimize"}},
        client,
        "abcd1234",
        7,
        {"lr": 0.5},
    )
    assert env["TRACKIO_SWEEP_ID"] == "abcd1234"
    assert env["TRACKIO_SWEEP_TRIAL_ID"] == "7"
    assert env["TRACKIO_SWEEP_PROJECT"] == "proj"
    assert env["TRACKIO_SWEEP_METRIC_NAME"] == "loss"

    env = _trial_child_env({}, client, "abcd1234", 7, {"lr": 0.5})
    assert "TRACKIO_SWEEP_METRIC_NAME" not in env


def test_trial_context_from_env_reads_metric_name(temp_dir, monkeypatch):
    from trackio.sweep_agent import trial_context_from_env

    monkeypatch.setenv("TRACKIO_SWEEP_ID", "abcd1234")
    monkeypatch.setenv("TRACKIO_SWEEP_TRIAL_ID", "3")
    monkeypatch.setenv("TRACKIO_SWEEP_METRIC_NAME", "loss")
    context = trial_context_from_env()
    assert context["metric_name"] == "loss"


def test_agent_fallback_report_carries_metric(temp_dir, monkeypatch):
    from trackio import context_vars
    from trackio.run import Run

    def report_without_server(self, state):
        trial_context = context_vars.current_sweep_trial.get()
        if trial_context is not None:
            trial_context["metric_value"] = self._sweep_metric_last

    monkeypatch.setattr(Run, "_report_sweep_trial", report_without_server)
    sweep_id = trackio.sweep(
        {
            "method": "grid",
            "metric": {"name": "loss", "goal": "minimize"},
            "parameters": {"lr": {"values": [0.5]}},
        },
        project="proj",
    )

    def train():
        trackio.init(project="proj")
        trackio.log({"loss": 0.25})
        trackio.finish()

    trackio.agent(sweep_id, function=train, project="proj")

    trials = SQLiteStorage.get_sweep_trials("proj", sweep_id)
    assert trials[0]["state"] == "finished"
    assert trials[0]["metric_value"] == 0.25


def test_init_merges_params_into_namespace_config(temp_dir):
    import argparse

    sweep_id = trackio.sweep(
        {"method": "grid", "parameters": {"lr": {"values": [0.5]}}},
        project="proj",
    )
    captured = {}

    def train():
        run = trackio.init(project="proj", config=argparse.Namespace(momentum=0.9))
        captured["config"] = dict(run.config)
        trackio.finish()

    trackio.agent(sweep_id, function=train, project="proj")

    assert captured["config"]["lr"] == 0.5
    assert captured["config"]["momentum"] == 0.9


def test_concurrent_agents_never_share_a_grid_cell(temp_dir):
    sweep_id = SQLiteStorage.create_sweep(
        "proj",
        {
            "method": "grid",
            "parameters": {"x": {"values": list(range(10))}},
        },
    )
    assigned = []
    lock = threading.Lock()

    def worker():
        while True:
            command = SQLiteStorage.suggest_trial("proj", sweep_id)
            if command["command"] != "run":
                return
            with lock:
                assigned.append(command["params"]["x"])

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(assigned) == list(range(10))


def test_trial_context_from_env(temp_dir, monkeypatch):
    sweep_id = SQLiteStorage.create_sweep(
        "proj",
        {
            "method": "grid",
            "metric": {"name": "loss", "goal": "minimize"},
            "parameters": {"lr": {"values": [0.5]}},
        },
    )
    command = SQLiteStorage.suggest_trial("proj", sweep_id)

    monkeypatch.setenv("TRACKIO_SWEEP_ID", sweep_id)
    monkeypatch.setenv("TRACKIO_SWEEP_TRIAL_ID", str(command["trial_id"]))
    monkeypatch.setenv("TRACKIO_SWEEP_PARAMS", '{"lr": 0.5}')
    monkeypatch.setenv("TRACKIO_SWEEP_PROJECT", "proj")

    run = trackio.init(project="proj")
    assert run.config["lr"] == 0.5
    assert run.sweep_id == sweep_id
    trackio.log({"loss": 0.1})
    trackio.finish()

    trials = SQLiteStorage.get_sweep_trials("proj", sweep_id)
    assert trials[0]["state"] == "finished"
    assert trials[0]["metric_value"] == 0.1
    assert trials[0]["run_id"] == run.id


def test_bayes_sweep_through_agent_loop(temp_dir):
    sweep_id = trackio.sweep(
        {
            "method": "bayes",
            "metric": {"name": "loss", "goal": "minimize"},
            "run_cap": 5,
            "parameters": {"x": {"min": 0.0, "max": 1.0}},
        },
        project="proj",
    )

    def train():
        run = trackio.init(project="proj")
        trackio.log({"loss": (run.config["x"] - 0.5) ** 2})
        trackio.finish()

    trackio.agent(sweep_id, function=train, project="proj")

    sweep = SQLiteStorage.get_sweep("proj", sweep_id)
    assert sweep["state"] == "finished"
    assert sweep["trial_counts"] == {"finished": 5}
    assert sweep["best_metric_value"] is not None


def test_api_sweeps_accessor(temp_dir):
    sweep_id = trackio.sweep(grid_config(), project="proj")

    def train():
        run = trackio.init(project="proj")
        trackio.log({"loss": run.config["lr"] * run.config["batch_size"]})
        trackio.finish()

    trackio.agent(sweep_id, function=train, project="proj")

    api = trackio.Api()
    sweeps = api.sweeps("proj")
    assert len(sweeps) == 1
    sweep = sweeps[0]
    assert sweep.sweep_id == sweep_id
    assert sweep.state == "finished"
    assert len(sweep.trials) == 4
    best = sweep.best_run()
    assert best is not None
    assert best.config["lr"] == 0.01
    assert best.config["batch_size"] == 8
