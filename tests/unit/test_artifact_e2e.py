from pathlib import Path

import trackio


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
    assert trackio.use_artifact("m").version == "v2"
    assert trackio.use_artifact("m:latest").version == "v2"
    assert trackio.use_artifact("m:best").version == "v1"
    assert trackio.use_artifact("m:v0").version == "v0"
    assert trackio.use_artifact("m:v1").version == "v1"
    assert trackio.use_artifact("m:v2").version == "v2"
    trackio.finish()
