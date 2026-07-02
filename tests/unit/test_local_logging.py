import json
import math
import sys
import time
import types
import warnings
from unittest.mock import patch

import pytest

import trackio
from trackio import gpu
from trackio.sqlite_storage import SQLiteStorage


def test_infinity_logging(temp_dir):
    trackio.init(project="test_infinity", name="test_run")
    trackio.log(
        metrics={
            "loss": float("inf"),
            "accuracy": float("-inf"),
            "f1_score": float("nan"),
            "normal_value": 0.95,
        }
    )
    trackio.finish()

    results = SQLiteStorage.get_logs(project="test_infinity", run="test_run")
    assert len(results) == 1
    log = results[0]

    assert math.isinf(log["loss"]) and log["loss"] > 0
    assert math.isinf(log["accuracy"]) and log["accuracy"] < 0
    assert math.isnan(log["f1_score"])
    assert log["normal_value"] == 0.95


def test_import_from_csv(temp_dir, tmp_path):
    csv_path = tmp_path / "logs.csv"
    csv_path.write_text(
        "\n".join(
            [
                "step,timestamp,train/loss,train/acc",
                "4,2024-01-01T00:00:00+00:00,12.2,82.2",
                "52,2024-01-01T00:01:00+00:00,9.5,93.5",
                "72,2024-01-01T00:02:00+00:00,8.9,94.9",
                "82,2024-01-01T00:03:00+00:00,8.8,95.8",
            ]
        )
    )

    trackio.import_csv(
        csv_path=str(csv_path),
        project="test_project",
        name="test_run",
    )

    results = SQLiteStorage.get_logs(project="test_project", run="test_run")
    assert len(results) == 4
    assert results[0]["train/loss"] == 12.2
    assert results[0]["train/acc"] == 82.2
    assert results[0]["step"] == 4
    assert results[1]["train/loss"] == 9.5
    assert results[1]["train/acc"] == 93.5
    assert results[1]["step"] == 52
    assert results[2]["train/loss"] == 8.9
    assert results[2]["train/acc"] == 94.9
    assert results[2]["step"] == 72
    assert results[3]["train/loss"] == 8.8
    assert results[3]["train/acc"] == 95.8
    assert results[3]["step"] == 82
    assert "timestamp" in results[0]
    assert "timestamp" in results[1]
    assert "timestamp" in results[2]
    assert "timestamp" in results[3]


def test_reserved_keys_are_renamed(temp_dir):
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        run = trackio.init(project="test_reserved", name="test_run")

        run.log({"step": 100, "time": 200, "project": "test", "normal_key": 42})

        reserved_warnings = [
            warning
            for warning in captured
            if "Reserved keys renamed" in str(warning.message)
        ]
        assert len(reserved_warnings) == 1
        assert "['step', 'time', 'project']" in str(reserved_warnings[0].message)

        run.finish()

    results = SQLiteStorage.get_logs(project="test_reserved", run="test_run")
    assert len(results) == 1
    log = results[0]

    assert "__step" in log
    assert "__time" in log
    assert "__project" in log
    assert "normal_key" in log
    assert log["__step"] == 100
    assert log["__time"] == 200
    assert log["__project"] == "test"
    assert log["normal_key"] == 42


def test_auto_log_gpu(temp_dir):
    def fake_gpu_metrics(device=None, all_gpus=False):
        return {
            "gpu/0/utilization": 75,
            "gpu/0/allocated_memory": 4.5,
            "gpu/0/total_memory": 12.0,
            "gpu/0/temp": 65,
            "gpu/0/power": 150.0,
            "gpu/mean_utilization": 75,
        }

    with patch.object(gpu, "collect_gpu_metrics", fake_gpu_metrics):
        with patch.object(gpu, "get_all_gpu_count", return_value=(1, [0])):
            with patch("trackio.run.gpu_available", return_value=True):
                with patch("trackio.run.apple_gpu_available", return_value=False):
                    trackio.init(
                        project="test_gpu_project",
                        name="test_gpu_run",
                        auto_log_gpu=True,
                        gpu_log_interval=0.1,
                    )
                    trackio.log({"loss": 0.5})
                    time.sleep(0.3)
                    trackio.finish()

    system_logs = SQLiteStorage.get_system_logs(
        project="test_gpu_project", run="test_gpu_run"
    )
    assert len(system_logs) >= 1
    log = system_logs[0]
    assert log["gpu/0/utilization"] == 75
    assert log["gpu/0/allocated_memory"] == 4.5
    assert log["gpu/0/total_memory"] == 12.0
    assert log["gpu/0/temp"] == 65
    assert log["gpu/0/power"] == 150.0
    assert log["gpu/mean_utilization"] == 75
    assert "timestamp" in log


def test_auto_log_gpu_multi(temp_dir):
    def fake_gpu_metrics(device=None, all_gpus=False):
        metrics = {
            "gpu/0/utilization": 75,
            "gpu/0/allocated_memory": 4.5,
            "gpu/0/total_memory": 12.0,
            "gpu/0/temp": 65,
            "gpu/0/power": 150.0,
            "gpu/mean_utilization": 70,
        }
        if all_gpus:
            metrics.update(
                {
                    "gpu/1/utilization": 65,
                    "gpu/1/allocated_memory": 3.0,
                    "gpu/1/total_memory": 12.0,
                    "gpu/1/temp": 60,
                    "gpu/1/power": 120.0,
                }
            )
        return metrics

    with patch.object(gpu, "collect_gpu_metrics", fake_gpu_metrics):
        with patch.object(gpu, "get_all_gpu_count", return_value=(2, [0, 1])):
            with patch("trackio.run.gpu_available", return_value=True):
                with patch("trackio.run.apple_gpu_available", return_value=False):
                    trackio.init(
                        project="test_gpu_multi",
                        name="test_gpu_multi_run",
                        auto_log_gpu=True,
                        gpu_log_interval=0.1,
                    )
                    trackio.log({"loss": 0.5})
                    time.sleep(0.3)
                    trackio.finish()

    system_logs = SQLiteStorage.get_system_logs(
        project="test_gpu_multi", run="test_gpu_multi_run"
    )
    assert len(system_logs) >= 1
    log = system_logs[0]
    assert log["gpu/0/utilization"] == 75
    assert log["gpu/1/utilization"] == 65
    assert log["gpu/mean_utilization"] == 70


def test_import_from_csv_without_numeric_metrics_raises(temp_dir, tmp_path):
    csv_path = tmp_path / "logs.csv"
    csv_path.write_text(
        "\n".join(
            [
                "step,timestamp,note",
                "1,2024-01-01T00:00:00+00:00,start",
                "2,2024-01-01T00:01:00+00:00,end",
            ]
        )
    )

    with pytest.raises(ValueError, match="No numeric metric data"):
        trackio.import_csv(
            csv_path=str(csv_path),
            project="test_project_no_metrics",
            name="test_run",
        )


class FakeWandbRun:
    def __init__(self, run_id, name, rows, metric_definitions=None, config=None):
        self.id = run_id
        self.name = name
        self.config = config or {}
        self.json_config = json.dumps(
            {"_wandb": {"value": {"m": metric_definitions or []}}}
        )
        self._rows = rows

    def scan_history(self, page_size=None):
        return iter(self._rows)


def _fake_wandb(monkeypatch, runs):
    class FakeApi:
        def runs(self, path):
            return list(runs)

    monkeypatch.setitem(sys.modules, "wandb", types.SimpleNamespace(Api=FakeApi))


def test_import_from_wandb(temp_dir, monkeypatch):
    # eval/* metrics use eval_iter as their x-axis (wandb define_metric encoding:
    # "1"=name, "2"=glob, "5"=1-based index of the step-metric record)
    metric_definitions = [
        {"1": "eval_iter", "6": [3]},
        {"2": "eval/*", "5": 1, "6": [1]},
    ]
    rows = [
        {"_step": 10, "_timestamp": 1700000000.0, "loss": 1.5},
        # wandb merges same-step logs into one row: train metric at _step 20
        # plus an eval logged at eval_iter 5
        {
            "_step": 20,
            "_timestamp": 1700000060.0,
            "loss": 1.2,
            "eval/acc": 0.8,
            "eval_iter": 5,
        },
    ]
    run = FakeWandbRun(
        "abc123", "my-run", rows, metric_definitions, config={"lr": 0.001}
    )
    _fake_wandb(monkeypatch, [run])

    trackio.import_wandb("entity/proj", project="test_wandb_project")

    results = SQLiteStorage.get_logs(project="test_wandb_project", run="my-run")
    by_step = {r["step"]: r for r in results}
    assert len(results) == 3
    assert by_step[10]["loss"] == 1.5
    assert by_step[20]["loss"] == 1.2
    assert "eval/acc" not in by_step[20]
    assert by_step[5]["eval/acc"] == 0.8
    assert "loss" not in by_step[5]
    assert "eval_iter" not in by_step[5]
    config = SQLiteStorage.get_run_config("test_wandb_project", "my-run")
    assert config["lr"] == 0.001

    with pytest.raises(ValueError, match="already exists"):
        trackio.import_wandb("entity/proj", project="test_wandb_project")


def test_import_from_wandb_step_metrics_override(temp_dir, monkeypatch):
    # no stored metric definitions: the caller supplies the mapping instead
    rows = [
        {"_step": 20, "_timestamp": 1700000060.0, "loss": 1.2},
        {"_step": 21, "_timestamp": 1700000120.0, "eval/acc": 0.8, "eval_iter": 5},
    ]
    run = FakeWandbRun("def456", "my-run", rows)
    _fake_wandb(monkeypatch, [run])

    trackio.import_wandb(
        "entity/proj",
        project="test_wandb_override",
        step_metrics={"eval/*": "eval_iter"},
    )

    results = SQLiteStorage.get_logs(project="test_wandb_override", run="my-run")
    by_step = {r["step"]: r for r in results}
    assert by_step[20]["loss"] == 1.2
    assert by_step[5]["eval/acc"] == 0.8


def test_import_from_wandb_offline_run_encoding(temp_dir, tmp_path, monkeypatch):
    """
    End-to-end against the installed wandb client, to catch wandb updates changing
    the metric-definition encoding that `import_wandb` decodes:

    1. Assert the `MetricRecord` protobuf field numbers the decoder relies on.
    2. Create a real offline run with `define_metric()`, read back the metric
       records the client actually wrote to the run file, re-encode them the way
       wandb stores them in the run config, and import through that.

    The history transport is faked because offline runs are not queryable through
    `wandb.Api` without a server; the client-written metric definitions are real.
    """
    wandb = pytest.importorskip("wandb")
    from wandb.proto import wandb_internal_pb2

    from trackio.imports import _wandb_step_metric_definitions

    # 1. the decoder reads keys "1", "2", "4", "5" of the stored MetricRecord
    fields = wandb_internal_pb2.MetricRecord.DESCRIPTOR.fields_by_name
    assert fields["name"].number == 1
    assert fields["glob_name"].number == 2
    assert fields["step_metric"].number == 4
    assert fields["step_metric_index"].number == 5

    # 2. real offline run
    source_run = wandb.init(
        project="source-project",
        name="offline-run",
        dir=str(tmp_path),
        mode="offline",
    )
    source_run.define_metric("eval_iter")
    source_run.define_metric("eval/*", step_metric="eval_iter")
    source_run.log({"loss": 1.5})
    source_run.log({"loss": 1.2, "eval/acc": 0.8, "eval_iter": 5})
    source_run.finish()

    try:
        from wandb.sdk.internal.datastore import DataStore
    except ImportError:
        pytest.skip(
            "wandb moved its internal datastore reader; update this test to keep "
            "covering the client-written metric definitions"
        )

    run_file = next((tmp_path / "wandb").glob("offline-run-*/run-*.wandb"))
    datastore = DataStore()
    datastore.open_for_scan(str(run_file))
    metric_records = []
    while True:
        data = datastore.scan_data()
        if data is None:
            break
        record = wandb_internal_pb2.Record()
        record.ParseFromString(bytes(data))
        if record.WhichOneof("record_type") == "metric":
            metric_records.append(record.metric)
    assert metric_records, "the wandb client wrote no metric records"

    # re-encode the client-written records as they appear in a stored run config
    # (a list of dicts keyed by stringified protobuf field number)
    stored = [
        {
            str(field.number): value
            for field, value in message.ListFields()
            if isinstance(value, (str, int, float))
        }
        for message in metric_records
    ]
    json_config = json.dumps({"_wandb": {"value": {"m": stored}}})
    assert _wandb_step_metric_definitions(json_config)["eval/*"] == "eval_iter"

    rows = [
        {"_step": 0, "_timestamp": 1700000000.0, "loss": 1.5},
        {
            "_step": 1,
            "_timestamp": 1700000060.0,
            "loss": 1.2,
            "eval/acc": 0.8,
            "eval_iter": 5,
        },
    ]
    run = FakeWandbRun("off123", "offline-run", rows, config={"lr": 0.001})
    run.json_config = json_config
    _fake_wandb(monkeypatch, [run])

    trackio.import_wandb("entity/proj", project="test_wandb_offline")

    results = SQLiteStorage.get_logs(project="test_wandb_offline", run="offline-run")
    by_step = {r["step"]: r for r in results}
    assert len(results) == 3
    assert by_step[0]["loss"] == 1.5
    assert by_step[1]["loss"] == 1.2
    assert by_step[5]["eval/acc"] == 0.8
    assert "eval_iter" not in by_step[5]
