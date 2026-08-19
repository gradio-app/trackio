import os
import sqlite3
from pathlib import Path

import pytest

from trackio.sqlite_storage import SQLiteStorage
from trackio.sweeps import SweepConfigError


def grid_config():
    return {
        "method": "grid",
        "metric": {"name": "loss", "goal": "minimize"},
        "parameters": {"lr": {"values": [0.1, 0.01]}},
    }


def test_create_and_get_sweep(temp_dir):
    sweep_id = SQLiteStorage.create_sweep("proj", grid_config(), name="my-sweep")
    sweep = SQLiteStorage.get_sweep("proj", sweep_id)
    assert sweep["sweep_id"] == sweep_id
    assert sweep["name"] == "my-sweep"
    assert sweep["method"] == "grid"
    assert sweep["state"] == "running"
    assert sweep["metric_name"] == "loss"
    assert sweep["metric_goal"] == "minimize"
    assert sweep["num_trials"] == 0
    assert sweep["config"]["parameters"]["lr"]["values"] == [0.1, 0.01]


def test_create_sweep_validates_config(temp_dir):
    with pytest.raises(SweepConfigError):
        SQLiteStorage.create_sweep("proj", {"method": "grid"})


def test_get_sweep_missing(temp_dir):
    assert SQLiteStorage.get_sweep("proj", "nope") is None
    SQLiteStorage.init_db("proj")
    assert SQLiteStorage.get_sweep("proj", "nope") is None


def test_list_sweeps(temp_dir):
    assert SQLiteStorage.list_sweeps("proj") == []
    first = SQLiteStorage.create_sweep("proj", grid_config())
    second = SQLiteStorage.create_sweep("proj", grid_config())
    listed = {s["sweep_id"] for s in SQLiteStorage.list_sweeps("proj")}
    assert listed == {first, second}


def test_suggest_trial_lifecycle(temp_dir):
    sweep_id = SQLiteStorage.create_sweep("proj", grid_config())

    first = SQLiteStorage.suggest_trial("proj", sweep_id, agent_id="a1")
    assert first["command"] == "run"
    second = SQLiteStorage.suggest_trial("proj", sweep_id, agent_id="a1")
    assert second["command"] == "run"
    assert first["params"] != second["params"]

    exhausted = SQLiteStorage.suggest_trial("proj", sweep_id)
    assert exhausted == {"command": "exit", "reason": "exhausted"}
    sweep = SQLiteStorage.get_sweep("proj", sweep_id)
    assert sweep["state"] == "finished"
    assert sweep["finish_reason"] == "exhausted"
    assert SQLiteStorage.suggest_trial("proj", sweep_id) == {
        "command": "exit",
        "reason": "exhausted",
    }


def test_suggest_trial_unknown_sweep(temp_dir):
    with pytest.raises(ValueError, match="not found"):
        SQLiteStorage.suggest_trial("proj", "nope")


def test_suggest_trial_respects_pause_and_stop(temp_dir):
    sweep_id = SQLiteStorage.create_sweep("proj", grid_config())
    SQLiteStorage.set_sweep_state("proj", sweep_id, "paused")
    assert SQLiteStorage.suggest_trial("proj", sweep_id) == {"command": "wait"}
    SQLiteStorage.set_sweep_state("proj", sweep_id, "stopped")
    assert SQLiteStorage.suggest_trial("proj", sweep_id) == {
        "command": "exit",
        "reason": "stopped",
    }


def test_run_cap_reason(temp_dir):
    config = {**grid_config(), "run_cap": 1}
    sweep_id = SQLiteStorage.create_sweep("proj", config)
    assert SQLiteStorage.suggest_trial("proj", sweep_id)["command"] == "run"
    capped = SQLiteStorage.suggest_trial("proj", sweep_id)
    assert capped == {"command": "exit", "reason": "run_cap"}
    assert SQLiteStorage.get_sweep("proj", sweep_id)["finish_reason"] == "run_cap"


def test_state_transitions_enforced(temp_dir):
    sweep_id = SQLiteStorage.create_sweep("proj", grid_config())
    SQLiteStorage.set_sweep_state("proj", sweep_id, "stopped")
    with pytest.raises(ValueError, match="Cannot transition"):
        SQLiteStorage.set_sweep_state("proj", sweep_id, "running")


def test_set_sweep_state_same_state_is_noop(temp_dir):
    sweep_id = SQLiteStorage.create_sweep("proj", grid_config())
    sweep = SQLiteStorage.set_sweep_state("proj", sweep_id, "running")
    assert sweep["state"] == "running"


def test_invalid_state_rejected(temp_dir):
    sweep_id = SQLiteStorage.create_sweep("proj", grid_config())
    with pytest.raises(ValueError, match="Invalid sweep state"):
        SQLiteStorage.set_sweep_state("proj", sweep_id, "zombie")


def test_mark_and_report_trial(temp_dir):
    sweep_id = SQLiteStorage.create_sweep("proj", grid_config())
    trial = SQLiteStorage.suggest_trial("proj", sweep_id)

    assert SQLiteStorage.mark_trial_running(
        "proj", sweep_id, trial["trial_id"], "run-1"
    )
    trials = SQLiteStorage.get_sweep_trials("proj", sweep_id)
    assert trials[0]["state"] == "running"
    assert trials[0]["run_id"] == "run-1"

    assert SQLiteStorage.report_trial(
        "proj", sweep_id, trial["trial_id"], "finished", metric_value=0.5
    )
    trials = SQLiteStorage.get_sweep_trials("proj", sweep_id)
    assert trials[0]["state"] == "finished"
    assert trials[0]["metric_value"] == 0.5


def test_report_trial_first_report_wins(temp_dir):
    sweep_id = SQLiteStorage.create_sweep("proj", grid_config())
    trial = SQLiteStorage.suggest_trial("proj", sweep_id)
    assert SQLiteStorage.report_trial("proj", sweep_id, trial["trial_id"], "failed")
    assert not SQLiteStorage.report_trial(
        "proj", sweep_id, trial["trial_id"], "finished", metric_value=1.0
    )
    trials = SQLiteStorage.get_sweep_trials("proj", sweep_id)
    assert trials[0]["state"] == "failed"


def test_report_trial_rejects_non_terminal_state(temp_dir):
    sweep_id = SQLiteStorage.create_sweep("proj", grid_config())
    trial = SQLiteStorage.suggest_trial("proj", sweep_id)
    with pytest.raises(ValueError, match="Invalid terminal trial state"):
        SQLiteStorage.report_trial("proj", sweep_id, trial["trial_id"], "running")


def test_best_metric_tracking(temp_dir):
    sweep_id = SQLiteStorage.create_sweep("proj", grid_config())
    for run_id, value in (("run-a", 0.8), ("run-b", 0.2)):
        trial = SQLiteStorage.suggest_trial("proj", sweep_id)
        SQLiteStorage.mark_trial_running("proj", sweep_id, trial["trial_id"], run_id)
        SQLiteStorage.report_trial(
            "proj", sweep_id, trial["trial_id"], "finished", metric_value=value
        )
    sweep = SQLiteStorage.get_sweep("proj", sweep_id)
    assert sweep["best_metric_value"] == 0.2
    assert sweep["best_run_id"] == "run-b"


def test_best_metric_maximize(temp_dir):
    config = {**grid_config(), "metric": {"name": "acc", "goal": "maximize"}}
    sweep_id = SQLiteStorage.create_sweep("proj", config)
    for run_id, value in (("run-a", 0.8), ("run-b", 0.2)):
        trial = SQLiteStorage.suggest_trial("proj", sweep_id)
        SQLiteStorage.mark_trial_running("proj", sweep_id, trial["trial_id"], run_id)
        SQLiteStorage.report_trial(
            "proj", sweep_id, trial["trial_id"], "finished", metric_value=value
        )
    sweep = SQLiteStorage.get_sweep("proj", sweep_id)
    assert sweep["best_metric_value"] == 0.8
    assert sweep["best_run_id"] == "run-a"


def random_target_config(goal="minimize", target=0.5):
    return {
        "method": "random",
        "metric": {"name": "loss", "goal": goal, "target": target},
        "parameters": {"lr": {"min": 0.0, "max": 1.0}},
    }


def test_report_trial_meeting_target_finishes_sweep(temp_dir):
    sweep_id = SQLiteStorage.create_sweep("proj", random_target_config())
    trial = SQLiteStorage.suggest_trial("proj", sweep_id)
    SQLiteStorage.mark_trial_running("proj", sweep_id, trial["trial_id"], "run-1")
    SQLiteStorage.report_trial(
        "proj", sweep_id, trial["trial_id"], "finished", metric_value=0.4
    )
    sweep = SQLiteStorage.get_sweep("proj", sweep_id)
    assert sweep["state"] == "finished"
    assert sweep["finish_reason"] == "target"
    assert SQLiteStorage.suggest_trial("proj", sweep_id) == {
        "command": "exit",
        "reason": "target",
    }


def test_report_trial_missing_target_keeps_running(temp_dir):
    sweep_id = SQLiteStorage.create_sweep("proj", random_target_config())
    trial = SQLiteStorage.suggest_trial("proj", sweep_id)
    SQLiteStorage.report_trial(
        "proj", sweep_id, trial["trial_id"], "finished", metric_value=0.9
    )
    assert SQLiteStorage.get_sweep("proj", sweep_id)["state"] == "running"


def test_failed_trial_value_does_not_trigger_target(temp_dir):
    sweep_id = SQLiteStorage.create_sweep("proj", random_target_config())
    trial = SQLiteStorage.suggest_trial("proj", sweep_id)
    SQLiteStorage.report_trial(
        "proj", sweep_id, trial["trial_id"], "failed", metric_value=0.1
    )
    assert SQLiteStorage.get_sweep("proj", sweep_id)["state"] == "running"
    assert SQLiteStorage.suggest_trial("proj", sweep_id)["command"] == "run"


def test_target_maximize_direction(temp_dir):
    sweep_id = SQLiteStorage.create_sweep(
        "proj", random_target_config(goal="maximize", target=0.9)
    )
    trial = SQLiteStorage.suggest_trial("proj", sweep_id)
    SQLiteStorage.report_trial(
        "proj", sweep_id, trial["trial_id"], "finished", metric_value=0.5
    )
    assert SQLiteStorage.get_sweep("proj", sweep_id)["state"] == "running"
    trial = SQLiteStorage.suggest_trial("proj", sweep_id)
    SQLiteStorage.report_trial(
        "proj", sweep_id, trial["trial_id"], "finished", metric_value=0.95
    )
    assert SQLiteStorage.get_sweep("proj", sweep_id)["state"] == "finished"


def test_suggest_trial_detects_preexisting_target_hit(temp_dir):
    sweep_id = SQLiteStorage.create_sweep("proj", random_target_config())
    trial = SQLiteStorage.suggest_trial("proj", sweep_id)
    db_path = SQLiteStorage.get_project_db_path("proj")
    with SQLiteStorage._get_connection(db_path) as conn:
        conn.execute(
            """UPDATE sweep_trials SET state = 'finished', metric_value = 0.1
            WHERE trial_id = ?""",
            (trial["trial_id"],),
        )
        conn.commit()
    result = SQLiteStorage.suggest_trial("proj", sweep_id)
    assert result == {"command": "exit", "reason": "target"}
    sweep = SQLiteStorage.get_sweep("proj", sweep_id)
    assert sweep["state"] == "finished"
    assert sweep["finish_reason"] == "target"


def test_manual_stop_has_no_finish_reason(temp_dir):
    sweep_id = SQLiteStorage.create_sweep("proj", grid_config())
    SQLiteStorage.set_sweep_state("proj", sweep_id, "stopped")
    sweep = SQLiteStorage.get_sweep("proj", sweep_id)
    assert sweep["state"] == "stopped"
    assert sweep["finish_reason"] is None
    assert SQLiteStorage.suggest_trial("proj", sweep_id) == {
        "command": "exit",
        "reason": "stopped",
    }


def test_create_sweep_validates_project_name(temp_dir):
    with pytest.raises(ValueError, match="reserved suffix"):
        SQLiteStorage.create_sweep("model_sweeps", grid_config())
    assert not SQLiteStorage.get_project_db_path("model_sweeps").exists()


def test_existing_reserved_name_project_is_grandfathered(temp_dir):
    db_path = SQLiteStorage.get_project_db_path("legacy_sweeps")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    sqlite3.connect(db_path).close()

    SQLiteStorage.validate_project_name("legacy_sweeps")
    with pytest.raises(ValueError, match="reserved suffix"):
        SQLiteStorage.validate_project_name("other_sweeps")


def test_import_preserves_legacy_project_named_like_sidecar(temp_dir):
    SQLiteStorage.init_db("legacy_sweeps", validate_name=False)
    SQLiteStorage.log(
        project="legacy_sweeps",
        run="r1",
        metrics={"loss": 1.0},
        step=0,
        run_id="r1",
    )
    SQLiteStorage._dataset_import_attempted = True
    SQLiteStorage.export_to_parquet()
    os.unlink(SQLiteStorage.get_project_db_path("legacy_sweeps"))

    SQLiteStorage.import_from_parquet()

    projects = set(SQLiteStorage.get_projects())
    assert "legacy_sweeps" in projects
    assert "legacy" not in projects
    values = SQLiteStorage.get_metric_values("legacy_sweeps", None, "loss", run_id="r1")
    assert len(values) == 1


def test_import_distinguishes_real_sidecar_from_legacy_project(temp_dir):
    SQLiteStorage.log(
        project="myproj", run="r1", metrics={"loss": 1.0}, step=0, run_id="r1"
    )
    SQLiteStorage.init_db("myproj_sweeps", validate_name=False)
    SQLiteStorage.log(
        project="myproj_sweeps", run="r2", metrics={"acc": 0.5}, step=0, run_id="r2"
    )
    SQLiteStorage._dataset_import_attempted = True
    SQLiteStorage.export_to_parquet()
    for name in ("myproj", "myproj_sweeps"):
        os.unlink(SQLiteStorage.get_project_db_path(name))

    SQLiteStorage.import_from_parquet()

    values = SQLiteStorage.get_metric_values("myproj_sweeps", None, "acc", run_id="r2")
    assert len(values) == 1
    assert SQLiteStorage.list_sweeps("myproj") == []
    assert SQLiteStorage.get_metric_values("myproj", None, "loss", run_id="r1")
    with pytest.raises(ValueError, match="reserved suffix"):
        SQLiteStorage.validate_project_name("model_sweeps")
    with pytest.raises(ValueError, match="reserved suffix"):
        SQLiteStorage.validate_project_name("model_sweep_trials")


def test_suggest_trial_unknown_project_creates_no_db(temp_dir):
    with pytest.raises(ValueError, match="not found"):
        SQLiteStorage.suggest_trial("no-such-proj", "abc123")
    assert not SQLiteStorage.get_project_db_path("no-such-proj").exists()


def test_init_db_rejects_reserved_suffix_on_creation(temp_dir):
    with pytest.raises(ValueError, match="reserved suffix"):
        SQLiteStorage.init_db("train_sweeps")
    assert not SQLiteStorage.get_project_db_path("train_sweeps").exists()


def test_import_preserves_sweep_only_project(temp_dir):
    sweep_id = SQLiteStorage.create_sweep("proj", grid_config())
    SQLiteStorage._dataset_import_attempted = True
    SQLiteStorage.export_to_parquet()
    os.unlink(SQLiteStorage.get_project_db_path("proj"))

    SQLiteStorage.import_from_parquet()

    assert SQLiteStorage.get_sweep("proj", sweep_id) is not None
    assert "proj_sweeps" not in set(SQLiteStorage.get_projects())


def test_tab_availability_includes_sweeps(temp_dir):
    SQLiteStorage.init_db("proj")
    assert SQLiteStorage.get_tab_availability_flags("proj")["sweeps"] is False
    SQLiteStorage.create_sweep("proj", grid_config())
    assert SQLiteStorage.get_tab_availability_flags("proj")["sweeps"] is True


def test_parquet_roundtrip_preserves_sweeps(temp_dir):
    sweep_id = SQLiteStorage.create_sweep("proj", grid_config(), name="rt")
    trial = SQLiteStorage.suggest_trial("proj", sweep_id, agent_id="a1")
    SQLiteStorage.mark_trial_running("proj", sweep_id, trial["trial_id"], "run-1")
    SQLiteStorage.report_trial(
        "proj", sweep_id, trial["trial_id"], "finished", metric_value=0.3
    )
    SQLiteStorage.suggest_trial("proj", sweep_id, agent_id="a1")
    assert SQLiteStorage.suggest_trial("proj", sweep_id)["reason"] == "exhausted"
    before_sweep = SQLiteStorage.get_sweep("proj", sweep_id)
    assert before_sweep["finish_reason"] == "exhausted"
    before_trials = SQLiteStorage.get_sweep_trials("proj", sweep_id)

    SQLiteStorage._dataset_import_attempted = True
    SQLiteStorage.export_to_parquet()

    db_path = SQLiteStorage.get_project_db_path("proj")
    for table in SQLiteStorage._SWEEP_PARQUET_TABLES:
        assert (Path(temp_dir) / f"{db_path.stem}_{table}.parquet").exists()

    os.unlink(db_path)
    SQLiteStorage.import_from_parquet()

    assert SQLiteStorage.get_sweep("proj", sweep_id) == before_sweep
    assert SQLiteStorage.get_sweep_trials("proj", sweep_id) == before_trials


def test_sweep_run_memberships(temp_dir):
    assert SQLiteStorage.get_sweep_run_memberships("proj") == {}

    sweep_id = SQLiteStorage.create_sweep("proj", grid_config(), name="my-sweep")
    for run_id, value in (("run-a", 0.8), ("run-b", 0.2)):
        trial = SQLiteStorage.suggest_trial("proj", sweep_id)
        SQLiteStorage.mark_trial_running("proj", sweep_id, trial["trial_id"], run_id)
        SQLiteStorage.report_trial(
            "proj", sweep_id, trial["trial_id"], "finished", metric_value=value
        )

    memberships = SQLiteStorage.get_sweep_run_memberships("proj")
    assert set(memberships) == {"run-a", "run-b"}
    assert memberships["run-a"]["sweep_id"] == sweep_id
    assert memberships["run-a"]["sweep_name"] == "my-sweep"
    assert memberships["run-a"]["trial_state"] == "finished"
    assert memberships["run-a"]["metric_value"] == 0.8
    assert not memberships["run-a"]["best"]
    assert memberships["run-b"]["best"]


def test_sweep_run_memberships_maximize_and_pending(temp_dir):
    config = {**grid_config(), "metric": {"name": "acc", "goal": "maximize"}}
    sweep_id = SQLiteStorage.create_sweep("proj", config)

    trial = SQLiteStorage.suggest_trial("proj", sweep_id)
    SQLiteStorage.mark_trial_running("proj", sweep_id, trial["trial_id"], "run-a")
    SQLiteStorage.report_trial(
        "proj", sweep_id, trial["trial_id"], "finished", metric_value=0.9
    )

    running = SQLiteStorage.suggest_trial("proj", sweep_id)
    SQLiteStorage.mark_trial_running("proj", sweep_id, running["trial_id"], "run-b")

    memberships = SQLiteStorage.get_sweep_run_memberships("proj")
    assert memberships["run-a"]["best"]
    assert memberships["run-b"]["trial_state"] == "running"
    assert memberships["run-b"]["metric_value"] is None
    assert not memberships["run-b"]["best"]
