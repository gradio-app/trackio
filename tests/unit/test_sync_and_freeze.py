import tempfile
from pathlib import Path

import pandas as pd

from trackio.sqlite_storage import SQLiteStorage


def test_clear_pending_preserves_local_data(temp_dir):
    project = "test-project"
    SQLiteStorage.bulk_log(
        project=project,
        run="run1",
        metrics_list=[{"loss": 0.5}, {"loss": 0.3}],
        steps=[0, 1],
        space_id="user/my-space",
    )
    pending = SQLiteStorage.get_pending_logs(project)
    assert pending is not None
    assert len(pending["logs"]) == 2

    SQLiteStorage.clear_pending_logs(project, pending["ids"])

    pending_after = SQLiteStorage.get_pending_logs(project)
    assert pending_after is None

    all_logs = SQLiteStorage.get_logs(project, "run1")
    assert len(all_logs) == 2
    assert all_logs[0]["loss"] == 0.5
    assert all_logs[1]["loss"] == 0.3


def test_clear_pending_system_logs_preserves_local_data(temp_dir):
    project = "test-project"
    SQLiteStorage.bulk_log_system(
        project=project,
        run="run1",
        metrics_list=[{"gpu_util": 80.0}, {"gpu_util": 90.0}],
        space_id="user/my-space",
    )
    pending = SQLiteStorage.get_pending_system_logs(project)
    assert pending is not None
    assert len(pending["logs"]) == 2

    SQLiteStorage.clear_pending_system_logs(project, pending["ids"])

    pending_after = SQLiteStorage.get_pending_system_logs(project)
    assert pending_after is None

    system_logs = SQLiteStorage.get_system_logs(project, "run1")
    assert len(system_logs) == 2


def test_export_static_preserves_all_data_across_rounds(temp_dir):
    project = "test-project"
    SQLiteStorage.bulk_log(
        project=project,
        run="run1",
        metrics_list=[{"loss": 0.5}, {"loss": 0.3}],
        steps=[0, 1],
    )

    with tempfile.TemporaryDirectory() as export_dir1:
        output1 = Path(export_dir1)
        SQLiteStorage.export_for_static_space(project, output1)
        df1 = pd.read_parquet(output1 / "metrics.parquet")
        assert len(df1) == 2

    SQLiteStorage.bulk_log(
        project=project,
        run="run1",
        metrics_list=[{"loss": 0.1}, {"loss": 0.05}],
        steps=[2, 3],
    )

    with tempfile.TemporaryDirectory() as export_dir2:
        output2 = Path(export_dir2)
        SQLiteStorage.export_for_static_space(project, output2)
        df2 = pd.read_parquet(output2 / "metrics.parquet")
        assert len(df2) == 4


def test_export_static_after_sync_preserves_all_data(temp_dir):
    project = "test-project"
    SQLiteStorage.bulk_log(
        project=project,
        run="run1",
        metrics_list=[{"loss": 0.5}, {"loss": 0.3}],
        steps=[0, 1],
        space_id="user/my-space",
    )

    pending = SQLiteStorage.get_pending_logs(project)
    SQLiteStorage.clear_pending_logs(project, pending["ids"])

    SQLiteStorage.bulk_log(
        project=project,
        run="run1",
        metrics_list=[{"loss": 0.1}, {"loss": 0.05}],
        steps=[2, 3],
        space_id="user/my-space",
    )

    pending2 = SQLiteStorage.get_pending_logs(project)
    SQLiteStorage.clear_pending_logs(project, pending2["ids"])

    with tempfile.TemporaryDirectory() as export_dir:
        output = Path(export_dir)
        SQLiteStorage.export_for_static_space(project, output)
        df = pd.read_parquet(output / "metrics.parquet")
        assert len(df) == 4


def test_multiple_sync_rounds_all_data_in_export(temp_dir):
    project = "test-project"

    SQLiteStorage.bulk_log(
        project=project,
        run="run1",
        metrics_list=[{"acc": 0.8}],
        steps=[0],
        space_id="user/space",
    )
    pending = SQLiteStorage.get_pending_logs(project)
    SQLiteStorage.clear_pending_logs(project, pending["ids"])

    with tempfile.TemporaryDirectory() as d:
        SQLiteStorage.export_for_static_space(project, Path(d))
        df = pd.read_parquet(Path(d) / "metrics.parquet")
        assert len(df) == 1

    SQLiteStorage.bulk_log(
        project=project,
        run="run1",
        metrics_list=[{"acc": 0.9}],
        steps=[1],
        space_id="user/space",
    )
    pending = SQLiteStorage.get_pending_logs(project)
    SQLiteStorage.clear_pending_logs(project, pending["ids"])

    with tempfile.TemporaryDirectory() as d:
        SQLiteStorage.export_for_static_space(project, Path(d))
        df = pd.read_parquet(Path(d) / "metrics.parquet")
        assert len(df) == 2
        steps = sorted(df["step"].tolist())
        assert steps == [0, 1]
