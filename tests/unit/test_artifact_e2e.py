"""End-to-end scenarios for the local artifact path.

`test_artifact.py` covers individual methods. This file covers cohesive
multi-step user workflows at the public module-level API. These also serve as
regression tests for the example in the docs.
"""

from pathlib import Path

import pytest

import trackio
from trackio.sqlite_storage import SQLiteStorage


def test_master_plan_example_runs_verbatim(temp_dir, tmp_path, monkeypatch):
    weights = tmp_path / "weights.bin"
    weights.write_bytes(b"\x00" * 1024)
    monkeypatch.chdir(tmp_path)

    trackio.init(project="art-demo")
    art = trackio.Artifact(name="my-model", type="model", metadata={"acc": 0.91})
    art.add_file(weights)
    trackio.log_artifact(art, aliases=["best"])
    trackio.finish()

    trackio.init(project="art-demo")
    fetched = trackio.use_artifact("my-model:latest")
    out = fetched.download()
    trackio.finish()

    materialized = Path(out) / "weights.bin"
    assert materialized.is_file()
    assert materialized.read_bytes() == weights.read_bytes()
    assert fetched.metadata == {"acc": 0.91}
    assert sorted(fetched.aliases) == ["best", "latest"]


def test_download_after_finish_still_works(temp_dir, tmp_path):
    weights = tmp_path / "w.bin"
    weights.write_bytes(b"data")

    trackio.init(project="art-after-finish", name="producer")
    art = trackio.Artifact(name="m", type="model")
    art.add_file(weights)
    trackio.log_artifact(art)
    trackio.finish()

    trackio.init(project="art-after-finish", name="consumer")
    fetched = trackio.use_artifact("m:latest")
    trackio.finish()

    out = fetched.download(tmp_path / "dl")
    assert (Path(out) / "w.bin").read_bytes() == b"data"


def test_add_dir_round_trip(temp_dir, tmp_path):
    src = tmp_path / "model"
    src.mkdir()
    (src / "weights.bin").write_bytes(b"weights")
    (src / "config.json").write_bytes(b'{"lr": 0.01}')
    sub = src / "tokenizer"
    sub.mkdir()
    (sub / "vocab.txt").write_bytes(b"alpha\nbeta\n")

    trackio.init(project="art-dir", name="producer")
    art = trackio.Artifact(name="bundle", type="model")
    art.add_dir(src)
    trackio.log_artifact(art)
    trackio.finish()

    trackio.init(project="art-dir", name="consumer")
    fetched = trackio.use_artifact("bundle:latest")
    out = Path(fetched.download(tmp_path / "dl"))
    trackio.finish()

    assert (out / "weights.bin").read_bytes() == b"weights"
    assert (out / "config.json").read_bytes() == b'{"lr": 0.01}'
    assert (out / "tokenizer" / "vocab.txt").read_bytes() == b"alpha\nbeta\n"


def test_multi_version_lifecycle_with_alias_rotation(temp_dir, tmp_path):
    versions = {
        0: b"weights-v0",
        1: b"weights-v1",
        2: b"weights-v2",
    }
    for i, payload in versions.items():
        p = tmp_path / f"w{i}.bin"
        p.write_bytes(payload)
        trackio.init(project="art-multi", name=f"run-{i}")
        art = trackio.Artifact(name="m", type="model")
        art.add_file(p)
        aliases = ["best"] if i == 1 else None
        trackio.log_artifact(art, aliases=aliases)
        trackio.finish()

    trackio.init(project="art-multi", name="consumer")
    assert trackio.use_artifact("m").version == 2
    assert trackio.use_artifact("m:latest").version == 2
    assert trackio.use_artifact("m:best").version == 1
    assert trackio.use_artifact("m:v0").version == 0
    assert trackio.use_artifact("m:v1").version == 1
    assert trackio.use_artifact("m:v2").version == 2
    trackio.finish()


def test_projects_are_isolated(temp_dir, tmp_path):
    payload_a = tmp_path / "a.bin"
    payload_a.write_bytes(b"alpha")
    payload_b = tmp_path / "b.bin"
    payload_b.write_bytes(b"beta")

    trackio.init(project="proj-a", name="p")
    art_a = trackio.Artifact(name="m", type="model")
    art_a.add_file(payload_a)
    trackio.log_artifact(art_a)
    trackio.finish()

    trackio.init(project="proj-b", name="p")
    art_b = trackio.Artifact(name="m", type="model")
    art_b.add_file(payload_b)
    trackio.log_artifact(art_b)
    trackio.finish()

    trackio.init(project="proj-a", name="c")
    a = trackio.use_artifact("m:latest")
    assert a.project == "proj-a"
    out_a = Path(a.download(tmp_path / "dl-a"))
    assert (out_a / "a.bin").read_bytes() == b"alpha"
    trackio.finish()

    trackio.init(project="proj-b", name="c")
    b = trackio.use_artifact("m:latest")
    assert b.project == "proj-b"
    out_b = Path(b.download(tmp_path / "dl-b"))
    assert (out_b / "b.bin").read_bytes() == b"beta"
    trackio.finish()


def test_two_runs_co_produce_same_bytes(temp_dir, tmp_path):
    weights = tmp_path / "w.bin"
    weights.write_bytes(b"shared")

    for run_name in ("run-a", "run-b"):
        trackio.init(project="art-coprod", name=run_name)
        art = trackio.Artifact(name="m", type="model")
        art.add_file(weights)
        trackio.log_artifact(art)
        trackio.finish()

    versions = SQLiteStorage.list_artifact_versions("art-coprod", "m")
    assert len(versions) == 1
    assert versions[0]["version"] == 0

    lineage_a = SQLiteStorage.get_run_artifacts("art-coprod", "run-a", None)
    lineage_b = SQLiteStorage.get_run_artifacts("art-coprod", "run-b", None)
    assert len(lineage_a["output"]) == 1
    assert len(lineage_b["output"]) == 1
    assert lineage_a["output"][0]["version_id"] == lineage_b["output"][0]["version_id"]


def test_v3_alias_rejected_writes_no_blobs(temp_dir, tmp_path):
    weights = tmp_path / "w.bin"
    weights.write_bytes(b"x")
    trackio.init(project="art-rej", name="p")
    art = trackio.Artifact(name="m", type="model")
    art.add_file(weights)
    with pytest.raises(ValueError, match="reserved"):
        trackio.log_artifact(art, aliases=["v3"])
    trackio.finish()

    blobs_dir = Path(temp_dir) / "artifacts" / "art-rej" / "blobs"
    has_blobs = blobs_dir.exists() and any(p.is_file() for p in blobs_dir.rglob("*"))
    assert not has_blobs

    arts = SQLiteStorage.list_artifacts("art-rej")
    assert arts == []
