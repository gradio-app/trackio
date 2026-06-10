import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import trackio
from trackio import Run, fragments, utils
from trackio.remote_client import RemoteClient as Client
from trackio.sqlite_storage import SQLiteStorage


class FakeBucketHub:
    def __init__(self):
        self.files: dict[str, bytes] = {}
        self.utils = SimpleNamespace(get_token=lambda: "fake-token")

    def batch_bucket_files(
        self, bucket_id, add=None, copy=None, delete=None, token=None
    ):
        for item, remote_path in add or []:
            if isinstance(item, bytes):
                self.files[remote_path] = item
            else:
                self.files[remote_path] = Path(item).read_bytes()
        for remote_path in delete or []:
            self.files.pop(remote_path, None)

    def list_bucket_tree(self, bucket_id, prefix=None, recursive=None, token=None):
        return [
            SimpleNamespace(type="file", path=path)
            for path in sorted(self.files)
            if prefix is None or path.startswith(prefix)
        ]

    def download_bucket_files(
        self, bucket_id, files, raise_on_missing_files=False, token=None
    ):
        for remote_path, local_path in files:
            Path(local_path).write_bytes(self.files[remote_path])


def make_metric_entries(project="proj", run="run1", run_id="rid1", n=3):
    return [
        {
            "project": project,
            "run": run,
            "run_id": run_id,
            "metrics": {"loss": 1.0 / (i + 1)},
            "step": i,
            "timestamp": f"2026-06-10T00:00:0{i}+00:00",
            "config": {"lr": 0.1} if i == 0 else None,
            "log_id": f"log-{i}",
        }
        for i in range(n)
    ]


def test_metric_fragment_roundtrip_and_idempotent_import(temp_dir):
    records = [fragments.metric_record(e) for e in make_metric_entries()]
    data = fragments.FragmentWriter.serialize_records(records)
    parsed = fragments.parse_fragment_bytes(data)
    assert len(parsed) == 3

    assert fragments.import_records(parsed) == 3
    logs = SQLiteStorage.get_logs("proj", "run1")
    assert len(logs) == 3
    assert logs[0]["loss"] == 1.0
    assert [log["step"] for log in logs] == [0, 1, 2]
    config = SQLiteStorage.get_run_config("proj", "run1")
    assert config["lr"] == 0.1

    fragments.import_records(parsed)
    assert len(SQLiteStorage.get_logs("proj", "run1")) == 3


def test_parse_tolerates_corrupt_and_unknown_lines():
    records = [fragments.metric_record(e) for e in make_metric_entries(n=2)]
    data = fragments.FragmentWriter.serialize_records(records)
    data += b'{"kind": "unknown-kind"}\n'
    data += b'{"kind": "metric", "project": "p", "truncated...'
    parsed = fragments.parse_fragment_bytes(data)
    assert len(parsed) == 2
    assert all(r["kind"] == "metric" for r in parsed)


def test_system_and_alert_fragment_roundtrip(temp_dir):
    system_entries = [
        {
            "project": "proj",
            "run": "run1",
            "run_id": "rid1",
            "metrics": {"gpu_util": 0.5},
            "timestamp": "2026-06-10T00:00:00+00:00",
            "log_id": "sys-0",
        }
    ]
    alert_entries = [
        {
            "project": "proj",
            "run": "run1",
            "run_id": "rid1",
            "title": "loss spike",
            "text": "loss exploded",
            "level": "ERROR",
            "step": 5,
            "timestamp": "2026-06-10T00:00:01+00:00",
            "alert_id": "alert-0",
        }
    ]
    records = [fragments.system_metric_record(e) for e in system_entries] + [
        fragments.alert_record(e) for e in alert_entries
    ]
    parsed = fragments.parse_fragment_bytes(
        fragments.FragmentWriter.serialize_records(records)
    )
    assert fragments.import_records(parsed) == 2

    system_logs = SQLiteStorage.get_system_logs("proj", "run1")
    assert len(system_logs) == 1
    assert system_logs[0]["gpu_util"] == 0.5

    alerts = SQLiteStorage.get_alerts("proj")
    assert len(alerts) == 1
    assert alerts[0]["title"] == "loss spike"
    assert alerts[0]["level"] == "ERROR"

    fragments.import_records(parsed)
    assert len(SQLiteStorage.get_alerts("proj")) == 1


def test_write_local_and_import_inbox_dir(temp_dir):
    writer = fragments.FragmentWriter()
    records = [fragments.metric_record(e) for e in make_metric_entries()]
    fragment_path = writer.write_local(records)
    assert fragment_path is not None and fragment_path.exists()
    assert fragment_path.suffix == ".jsonl"
    assert list(fragments.local_inbox_dir().rglob("*.tmp")) == []

    assert fragments.import_inbox_dir() == 3
    assert not fragment_path.exists()
    assert len(SQLiteStorage.get_logs("proj", "run1")) == 3
    assert fragments.import_inbox_dir() == 0


def test_storage_mode_env_overrides(monkeypatch):
    monkeypatch.setenv("TRACKIO_STORAGE_MODE", "jsonl")
    assert utils.get_storage_mode() == "jsonl"
    monkeypatch.setenv("TRACKIO_STORAGE_MODE", "sqlite")
    assert utils.get_storage_mode() == "sqlite"
    monkeypatch.setenv("TRACKIO_STORAGE_MODE", "invalid")
    monkeypatch.setattr(utils, "is_network_filesystem", lambda path: False)
    assert utils.get_storage_mode() == "sqlite"
    monkeypatch.delenv("TRACKIO_STORAGE_MODE")
    monkeypatch.setattr(utils, "is_network_filesystem", lambda path: True)
    assert utils.get_storage_mode() == "jsonl"


def test_local_run_jsonl_mode_writes_fragments(temp_dir, monkeypatch):
    monkeypatch.setenv("TRACKIO_STORAGE_MODE", "jsonl")
    run = Run(url=None, project="proj", client=None, name="run1", space_id=None)
    run.log({"x": 1})
    run.log({"x": 2})
    run.finish()

    assert SQLiteStorage.get_logs("proj", "run1") == []
    fragment_files = list(fragments.local_inbox_dir().rglob("*.jsonl"))
    assert fragment_files

    imported = fragments.import_inbox_dir()
    assert imported == 2
    logs = SQLiteStorage.get_logs("proj", "run1")
    assert len(logs) == 2
    assert logs[0]["x"] == 1
    assert logs[1]["step"] == 1
    config = SQLiteStorage.get_run_config("proj", "run1")
    assert config is not None


def test_remote_run_drains_pending_to_bucket(temp_dir, monkeypatch):
    fake_hub = FakeBucketHub()
    monkeypatch.setattr(fragments, "huggingface_hub", fake_hub)

    failing_client = SimpleNamespace(predict=MagicMock(side_effect=Exception("down")))
    run = Run(
        url="user/space",
        project="proj",
        client=failing_client,
        name="run1",
        space_id="user/space",
        bucket_id="user/bucket",
        config={"lr": 0.01},
    )
    run.log({"x": 1})
    run.log({"x": 2})
    run.finish()

    assert not SQLiteStorage.has_pending_data("proj")
    inbox_files = [
        p for p in fake_hub.files if p.startswith(fragments.BUCKET_INBOX_PREFIX)
    ]
    assert inbox_files

    assert fragments.import_inbox_from_bucket("user/bucket") == 2
    logs = SQLiteStorage.get_logs("proj", "run1")
    assert len(logs) == 2
    assert {log["x"] for log in logs} == {1, 2}
    config = SQLiteStorage.get_run_config("proj", "run1")
    assert config["lr"] == 0.01


def test_cold_start_spills_to_bucket_without_clearing(temp_dir, monkeypatch):
    fake_hub = FakeBucketHub()
    monkeypatch.setattr(fragments, "huggingface_hub", fake_hub)
    monkeypatch.setattr(
        "trackio.run.RemoteClient",
        MagicMock(side_effect=ConnectionError("Space is not running")),
    )

    run = Run(
        url="user/space",
        project="proj",
        client=None,
        name="run1",
        space_id="user/space",
        bucket_id="user/bucket",
    )
    run.log({"x": 1})

    deadline = time.time() + 10
    while time.time() < deadline and not fake_hub.files:
        time.sleep(0.1)
    assert any(p.startswith(fragments.BUCKET_INBOX_PREFIX) for p in fake_hub.files)
    assert SQLiteStorage.has_pending_data("proj")

    run.finish()
    assert not SQLiteStorage.has_pending_data("proj")

    assert fragments.import_inbox_from_bucket("user/bucket") == 1
    logs = SQLiteStorage.get_logs("proj", "run1")
    assert len(logs) == 1
    assert logs[0]["x"] == 1


def test_network_filesystem_jsonl_end_to_end(temp_dir, monkeypatch):
    monkeypatch.setattr(utils, "_filesystem_type_for_path", lambda path: "lustre")
    project = "test-lustre-project"
    run_name = "lustre-run"

    trackio.init(project=project, name=run_name)
    trackio.log(metrics={"loss": 0.1})
    trackio.log(metrics={"loss": 0.05, "acc": 0.9})
    trackio.finish()

    assert SQLiteStorage.get_logs(project=project, run=run_name) == []
    assert list(fragments.local_inbox_dir().rglob("*.jsonl"))

    app, url, _, _ = trackio.show(block_thread=False, open_browser=False)
    try:
        client = Client(url, verbose=False)
        summary = None
        deadline = time.time() + 30
        while time.time() < deadline:
            summary = client.predict(
                project=project, run=run_name, api_name="/get_run_summary"
            )
            if summary and summary.get("num_logs") == 2:
                break
            time.sleep(1)
        assert summary["num_logs"] == 2

        logs = SQLiteStorage.get_logs(project=project, run=run_name)
        assert [entry["loss"] for entry in logs] == [0.1, 0.05]
        assert logs[1]["acc"] == 0.9
    finally:
        app.close()
