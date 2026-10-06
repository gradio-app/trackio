import sqlite3
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from huggingface_hub.errors import HfHubHTTPError, RepositoryNotFoundError

import trackio
from trackio import bump as bump_module
from trackio.bump import BumpError


def _fake_api_with_files(tmp_path, files):
    def download(repo_id, filename, repo_type):
        if filename not in files:
            raise HfHubHTTPError("missing", response=MagicMock(status_code=404))
        path = tmp_path / filename.replace("/", "_")
        path.write_text(files[filename])
        return str(path)

    return SimpleNamespace(hf_hub_download=download)


@pytest.mark.parametrize(
    "requirements, expected",
    [
        ("trackio[spaces,mcp]==0.39.0", "0.39.0"),
        ("gradio\ntrackio == 0.40.1\n", "0.40.1"),
        ("trackio[spaces]==1.2.3rc1", "1.2.3rc1"),
    ],
)
def test_space_version_from_requirements_pin(tmp_path, requirements, expected):
    api = _fake_api_with_files(tmp_path, {"requirements.txt": requirements})
    assert bump_module.get_space_trackio_version("u/s", api) == expected


def test_space_version_from_source_deploy(tmp_path):
    api = _fake_api_with_files(
        tmp_path,
        {
            "requirements.txt": "huggingface-hub>=1.10.0,<2\norjson",
            "trackio/package.json": '{"name": "trackio", "version": "0.39.2"}',
        },
    )
    assert bump_module.get_space_trackio_version("u/s", api) == "0.39.2"


def test_space_version_unknown_for_unpinned_space(tmp_path):
    api = _fake_api_with_files(tmp_path, {"requirements.txt": "trackio>=0.30"})
    assert bump_module.get_space_trackio_version("u/s", api) is None


def test_check_bumpable(monkeypatch):
    monkeypatch.setattr(trackio, "__version__", "0.41.0")
    assert bump_module._check_bumpable("u/s", "0.39.0") == "0.39.0"
    assert bump_module._check_bumpable("u/s", "0.41.0") == "0.41.0"
    with pytest.raises(BumpError, match="older than 0.39.0"):
        bump_module._check_bumpable("u/s", "0.38.1")
    with pytest.raises(BumpError, match="newer than the local"):
        bump_module._check_bumpable("u/s", "0.42.0")
    with pytest.raises(BumpError, match="Could not determine"):
        bump_module._check_bumpable("u/s", None)


def test_check_bumpable_rejects_prereleases(monkeypatch):
    monkeypatch.setattr(trackio, "__version__", "1.0.0")
    with pytest.raises(BumpError, match="not a final release"):
        bump_module._check_bumpable("u/s", "0.39.0rc1")
    monkeypatch.setattr(trackio, "__version__", "1.0.0rc1")
    with pytest.raises(BumpError, match="not a final"):
        bump_module._check_bumpable("u/s", "1.0.0")


def _fake_space_api():
    api = MagicMock()
    api.get_space_runtime.return_value = SimpleNamespace(stage="PAUSED")
    return api


def test_in_place_backup_failure_restarts_unchanged_space(monkeypatch):
    api = _fake_space_api()
    monkeypatch.setattr(
        bump_module, "_bucket_db_paths", lambda bucket_id: ["trackio/p.db"]
    )

    def fail_copy(*args, **kwargs):
        raise OSError("bucket unavailable")

    monkeypatch.setattr(bump_module, "_copy_bucket_paths", fail_copy)
    upload = MagicMock()
    monkeypatch.setattr(bump_module, "_upload_runtime_files", upload)

    with pytest.raises(BumpError, match="before anything was changed"):
        bump_module._bump_in_place("u/s", "u/b", "0.39.0", api, timeout=10)

    api.pause_space.assert_called_once_with("u/s")
    api.restart_space.assert_called_once_with("u/s")
    upload.assert_not_called()


@pytest.mark.parametrize("bucket_existed", [False, True])
def test_new_space_failure_removes_created_resources(monkeypatch, bucket_existed):
    api = MagicMock()
    api.space_info.side_effect = [
        RepositoryNotFoundError("missing", response=MagicMock(status_code=404)),
        SimpleNamespace(private=False),
    ]
    api.bucket_info.return_value = SimpleNamespace(private=False)
    bucket_files = {"u/b": ["trackio/p.db", "traces/p/s.json"], "u/new-b": []}
    monkeypatch.setattr(
        bump_module,
        "_list_bucket_file_paths",
        lambda bucket_id, prefix=None: bucket_files[bucket_id],
    )
    monkeypatch.setattr(
        bump_module.deploy, "_bucket_exists", lambda bucket_id, api: bucket_existed
    )
    monkeypatch.setattr(bump_module, "create_bucket_if_not_exists", MagicMock())
    copies = []

    def copy_files(source, destination):
        copies.append((source, destination))
        bucket_files["u/new-b"] = list(bucket_files["u/b"])

    monkeypatch.setattr(bump_module.huggingface_hub, "copy_files", copy_files)
    batch = MagicMock()
    monkeypatch.setattr(bump_module.huggingface_hub, "batch_bucket_files", batch)
    monkeypatch.setattr(bump_module, "bucket_inventory", lambda bucket_id: {})

    def fail_deploy(*args, **kwargs):
        raise RuntimeError("build failed")

    monkeypatch.setattr(bump_module.deploy, "deploy_as_space", fail_deploy)

    with pytest.raises(BumpError, match="was not modified"):
        bump_module._bump_into_new_space(
            "u/s", "u/b", "u/new", "u/new-b", api, timeout=10
        )

    assert copies == [("hf://buckets/u/b/", "hf://buckets/u/new-b/")]
    api.delete_repo.assert_called_once_with("u/new", repo_type="space", missing_ok=True)
    if bucket_existed:
        api.delete_bucket.assert_not_called()
        batch.assert_called_once_with(
            "u/new-b", delete=["trackio/p.db", "traces/p/s.json"]
        )
    else:
        api.delete_bucket.assert_called_once_with("u/new-b", missing_ok=True)


def test_bucket_db_paths_only_lists_top_level_databases(monkeypatch):
    monkeypatch.setattr(
        bump_module,
        "_list_bucket_file_paths",
        lambda bucket_id, prefix: [
            "trackio/a.db",
            "trackio/a.db-journal",
            "trackio/b.db",
            "trackio/media/a/run/0/x.png",
            "trackio/inbox/w/0001.jsonl",
            "trackio/artifacts/blob.db",
        ],
    )
    assert bump_module._bucket_db_paths("u/b") == [
        "trackio/a.db",
        "trackio/a.db-journal",
        "trackio/b.db",
    ]


def test_db_inventory_counts_rows_per_table_and_run(tmp_path):
    db_path = tmp_path / "p.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE metrics (id INTEGER PRIMARY KEY, run_name TEXT)")
    conn.execute("CREATE TABLE configs (id INTEGER PRIMARY KEY)")
    conn.executemany(
        "INSERT INTO metrics (run_name) VALUES (?)", [("a",), ("a",), ("b",)]
    )
    conn.commit()
    conn.close()

    assert bump_module._db_inventory(db_path) == {
        "tables": {"metrics": 3, "configs": 0},
        "metric_rows_per_run": {"a": 2, "b": 1},
    }


def test_bump_rejects_new_bucket_without_new_space():
    with pytest.raises(BumpError, match="requires new_space_id"):
        bump_module.bump("u/s", new_bucket_id="u/b")


@pytest.mark.parametrize(
    "argv",
    [
        ["trackio", "bump", "u/s"],
        ["trackio", "bump", "--space", "u/s"],
        ["trackio", "--space", "u/s", "bump"],
        ["trackio", "bump", "u/s", "--space", "u/s"],
    ],
)
def test_cli_bump_accepts_positional_or_space_flag(monkeypatch, argv):
    from trackio import cli

    calls = []
    monkeypatch.setattr(cli, "bump", lambda *a, **k: calls.append((a, k)))
    monkeypatch.setattr("sys.argv", argv)
    cli.main()
    assert calls == [(("u/s",), {"new_space_id": None, "new_bucket_id": None})]


@pytest.mark.parametrize(
    "argv",
    [
        ["trackio", "bump"],
        ["trackio", "bump", "u/s", "--space", "u/other"],
    ],
)
def test_cli_bump_rejects_missing_or_conflicting_space(monkeypatch, argv):
    from trackio import cli

    monkeypatch.setattr(cli, "bump", MagicMock())
    monkeypatch.setattr("sys.argv", argv)
    with pytest.raises(SystemExit):
        cli.main()
    cli.bump.assert_not_called()
