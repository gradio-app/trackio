import json
import sys

import pytest

import trackio
from trackio.cli import main


def _cli(monkeypatch, capsys, *args):
    monkeypatch.setattr(sys, "argv", ["trackio", "registry", *args])
    main()
    return capsys.readouterr()


def _log_source_versions(tmp_path):
    for version in range(2):
        model = tmp_path / f"model-{version}.pt"
        model.write_bytes(f"weights-{version}".encode())
        trackio.init(project="experiments", name=f"train-{version}")
        trackio.log_artifact(model, name="resnet", type="model")
        trackio.finish()


def test_registry_cli_workflow(temp_dir, tmp_path, monkeypatch, capsys):
    _log_source_versions(tmp_path)
    capsys.readouterr()

    created = _cli(
        monkeypatch,
        capsys,
        "create",
        "models",
        "--description",
        "Deployable models",
        "--json",
    )
    assert json.loads(created.out) == {
        "name": "models",
        "description": "Deployable models",
        "bucket_id": None,
    }

    _cli(
        monkeypatch,
        capsys,
        "create-collection",
        "models/churn",
        "--type",
        "model",
        "--description",
        "Churn predictor",
    )
    first = _cli(
        monkeypatch,
        capsys,
        "link",
        "models/churn",
        "experiments/resnet:v0",
        "--alias",
        "staging",
        "--json",
    )
    assert json.loads(first.out)["collection_version"] == 0

    second = _cli(
        monkeypatch,
        capsys,
        "link",
        "registry-models/churn",
        "experiments/resnet:v1",
        "--json",
    )
    assert json.loads(second.out)["collection_version"] == 1

    _cli(
        monkeypatch,
        capsys,
        "promote",
        "models/churn",
        "production",
        "v0",
    )
    shown = _cli(monkeypatch, capsys, "show", "models/churn", "--json")
    links = {
        link["collection_version"]: link for link in json.loads(shown.out)["links"]
    }
    assert links[0]["aliases"] == ["production", "staging"]
    assert links[1]["aliases"] == ["latest"]

    listed = _cli(monkeypatch, capsys, "list", "models")
    assert "churn (model) latest=v1 versions=2" in listed.out

    events = _cli(monkeypatch, capsys, "events", "models", "--json")
    assert [event["kind"] for event in json.loads(events.out)["events"]] == [
        "create",
        "create",
        "link",
        "promote",
        "link",
        "promote",
    ]

    removed = _cli(
        monkeypatch,
        capsys,
        "unlink",
        "models/churn",
        "1",
        "--json",
    )
    assert json.loads(removed.out)["latest_version"] == 0


def test_registry_cli_reports_missing_local_source(temp_dir, monkeypatch, capsys):
    trackio.Api().create_registry("models")
    with pytest.raises(SystemExit) as exc_info:
        _cli(
            monkeypatch,
            capsys,
            "link",
            "models/churn",
            "experiments/missing:v0",
        )
    assert exc_info.value.code == 1
    assert "not found locally" in capsys.readouterr().err
