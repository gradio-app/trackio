import sqlite3

import trackio
from trackio.sqlite_storage import SQLiteStorage


def _sync_ids(project, table):
    with sqlite3.connect(SQLiteStorage.get_project_db_path(project)) as conn:
        return conn.execute(
            f"SELECT run_name, log_id, space_id FROM {table} ORDER BY id"
        ).fetchall()


def _log_and_finish(**init_kwargs):
    trackio.init(project="proj", name="run", **init_kwargs)
    trackio.log({"loss": 1.0})
    trackio.finish()


def test_resume_keeps_existing_config_group_and_creation_time(temp_dir):
    _log_and_finish(config={"lr": 0.001, "epochs": 10}, group="baseline")
    original = SQLiteStorage.get_run_config("proj", "run")

    _log_and_finish(resume="must")

    resumed = SQLiteStorage.get_run_config("proj", "run")
    assert resumed["lr"] == 0.001
    assert resumed["epochs"] == 10
    assert resumed["_Group"] == "baseline"
    assert resumed["_Created"] == original["_Created"]
    assert len(SQLiteStorage.get_run_records("proj")) == 1


def test_resume_merges_explicit_config_and_group_over_existing(temp_dir):
    _log_and_finish(config={"lr": 0.001, "epochs": 10}, group="baseline")

    _log_and_finish(resume="allow", config={"lr": 0.01, "seed": 7}, group="tuned")

    resumed = SQLiteStorage.get_run_config("proj", "run")
    assert resumed["lr"] == 0.01
    assert resumed["epochs"] == 10
    assert resumed["seed"] == 7
    assert resumed["_Group"] == "tuned"


def test_new_run_with_same_name_does_not_inherit_config(temp_dir):
    _log_and_finish(config={"lr": 0.001}, group="baseline")

    _log_and_finish(resume="never")

    configs = SQLiteStorage.get_all_run_configs("proj").values()
    fresh = [config for config in configs if "lr" not in config]
    assert len(fresh) == 1
    assert fresh[0]["_Group"] is None


def test_resume_recovers_config_from_remote_server(temp_dir, monkeypatch):
    class _Remote:
        def predict(self, *args, api_name, **kwargs):
            assert api_name == "/get_run_configs"
            return {"run-id": {"lr": 0.5, "_Group": "remote", "_Created": "then"}}

    config = trackio._safe_get_config_for_init(
        "proj", "run", "run-id", "user/space", None, True, remote_client=_Remote()
    )
    assert config == {"lr": 0.5, "_Group": "remote", "_Created": "then"}
    assert (
        trackio._safe_get_config_for_init(
            "proj", "run", "run-id", "user/space", None, False, remote_client=_Remote()
        )
        is None
    )


def test_rename_run_keeps_pending_and_dedup_ids(temp_dir):
    SQLiteStorage.bulk_log(
        "proj",
        "old",
        [{"loss": 1.0}, {"loss": 0.5}],
        steps=[0, 1],
        log_ids=["log-0", "log-1"],
        space_id="user/space",
    )

    SQLiteStorage.rename_run("proj", "old", "new")

    assert _sync_ids("proj", "metrics") == [
        ("new", "log-0", "user/space"),
        ("new", "log-1", "user/space"),
    ]
    pending = SQLiteStorage.get_pending_logs("proj", "user/space")
    assert [log["run"] for log in pending["logs"]] == ["new", "new"]

    SQLiteStorage.bulk_log(
        "proj",
        "new",
        [{"loss": 1.0}],
        steps=[0],
        log_ids=["log-0"],
        space_id="user/space",
    )
    assert len(_sync_ids("proj", "metrics")) == 2


def test_move_run_keeps_pending_and_dedup_ids(temp_dir):
    SQLiteStorage.bulk_log(
        "source",
        "run",
        [{"loss": 1.0}],
        steps=[0],
        log_ids=["log-0"],
        space_id="user/space",
    )
    SQLiteStorage.bulk_log_system(
        "source", "run", [{"cpu": 1.0}], log_ids=["sys-0"], space_id="user/space"
    )

    assert SQLiteStorage.move_run("source", "run", "target") is True

    assert _sync_ids("target", "metrics") == [("run", "log-0", "user/space")]
    assert _sync_ids("target", "system_metrics") == [("run", "sys-0", "user/space")]
    assert SQLiteStorage.get_pending_logs("target", "user/space") is not None
    assert SQLiteStorage.get_pending_system_logs("target", "user/space") is not None
