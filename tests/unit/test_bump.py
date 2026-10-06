import sqlite3
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from huggingface_hub.errors import HfHubHTTPError

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
