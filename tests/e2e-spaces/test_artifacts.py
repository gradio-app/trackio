import hashlib
import secrets
import shutil
from pathlib import Path

import huggingface_hub
import pytest

import trackio
from trackio import utils
from trackio.remote_client import RemoteClient as Client


def _drop_local_blobs(project: str) -> None:
    """Remove the project's local content-addressed cache so a subsequent
    download is forced to fetch blobs from the Space over HTTP."""
    shutil.rmtree(utils.project_artifacts_dir(project), ignore_errors=True)


def test_artifact_dir_round_trip_downloads_from_remote(
    test_space_id, temp_dir, tmp_path, wait_for_client
):
    """A producer logs a multi-file directory artifact (with metadata and a
    user alias) to the Space; a separate consumer run resolves it by alias and
    downloads it after the local cache has been wiped, so the bytes come back
    over the wire from the Space's blob endpoint."""
    project = f"test_artifacts_rt_{secrets.token_urlsafe(8)}"

    src = tmp_path / "model"
    (src / "tokenizer").mkdir(parents=True)
    (src / "weights.bin").write_bytes(b"\x00\x01\x02weights")
    (src / "config.json").write_bytes(b'{"lr": 0.01}')
    (src / "tokenizer" / "vocab.txt").write_bytes(b"alpha\nbeta\n")

    run = trackio.init(project=project, name="producer", space_id=test_space_id)
    wait_for_client(run)
    art = trackio.Artifact(name="bundle", type="model", metadata={"acc": 0.95})
    art.add_dir(src)
    logged = trackio.log_artifact(art, aliases=["best"])
    assert logged.version == "v0"
    assert sorted(logged.aliases) == ["best", "latest"]
    trackio.finish()

    _drop_local_blobs(project)

    consumer = trackio.init(project=project, name="consumer", space_id=test_space_id)
    wait_for_client(consumer)
    fetched = trackio.use_artifact("bundle:latest")
    assert fetched.version == "v0"
    assert fetched.type == "model"
    assert fetched.metadata == {"acc": 0.95}
    assert sorted(fetched.aliases) == ["best", "latest"]

    out = Path(fetched.download(tmp_path / "dl"))
    trackio.finish()

    assert (out / "weights.bin").read_bytes() == b"\x00\x01\x02weights"
    assert (out / "config.json").read_bytes() == b'{"lr": 0.01}'
    assert (out / "tokenizer" / "vocab.txt").read_bytes() == b"alpha\nbeta\n"

    verify = Client(test_space_id, verbose=False)
    record = verify.predict(
        api_name="/get_artifact_manifest", project=project, name="bundle", spec="latest"
    )
    assert record["version"] == 0
    assert sorted(record["aliases"]) == ["best", "latest"]
    assert len(record["manifest"]) == 3


def test_artifact_versioning_dedup_and_alias_resolution(
    test_space_id, temp_dir, tmp_path, wait_for_client
):
    """Versions increment on new content, identical content de-duplicates back
    to the existing version without regressing `latest`, and every spec form
    (`latest`, a moving alias, and `vN`) resolves to the right version through
    the Space."""
    project = f"test_artifacts_ver_{secrets.token_urlsafe(8)}"

    def _log(run_name: str, payload: bytes, aliases=None) -> trackio.Artifact:
        f = tmp_path / f"{run_name}.bin"
        f.write_bytes(payload)
        run = trackio.init(project=project, name=run_name, space_id=test_space_id)
        wait_for_client(run)
        art = trackio.Artifact(name="model", type="model")
        art.add_file(f)
        logged = trackio.log_artifact(art, aliases=aliases)
        trackio.finish()
        return logged

    assert _log("r0", b"content-A", aliases=["best"]).version == "v0"
    assert _log("r1", b"content-B").version == "v1"
    assert _log("r2", b"content-A").version == "v0"

    consumer = trackio.init(project=project, name="consumer", space_id=test_space_id)
    wait_for_client(consumer)
    assert trackio.use_artifact("model").version == "v1"
    assert trackio.use_artifact("model:latest").version == "v1"
    assert trackio.use_artifact("model:best").version == "v0"
    assert trackio.use_artifact("model:v0").version == "v0"
    assert trackio.use_artifact("model:v1").version == "v1"

    out_v0 = Path(trackio.use_artifact("model:v0").download(tmp_path / "v0"))
    out_v1 = Path(trackio.use_artifact("model:v1").download(tmp_path / "v1"))
    trackio.finish()

    assert (out_v0 / "r0.bin").read_bytes() == b"content-A"
    assert (out_v1 / "r1.bin").read_bytes() == b"content-B"


def test_identical_bytes_dedup_across_runs(
    test_space_id, temp_dir, tmp_path, wait_for_client
):
    """Two runs logging byte-identical content produce a single version on the
    Space, and the shared blob is reported present by `/check_artifact_blobs`
    (an authenticated endpoint) so the second run skips re-uploading it."""
    project = f"test_artifacts_dedup_{secrets.token_urlsafe(8)}"
    payload = b"shared-checkpoint-bytes"
    digest = hashlib.sha256(payload).hexdigest()

    f = tmp_path / "w.bin"
    f.write_bytes(payload)

    for run_name in ("run-a", "run-b"):
        run = trackio.init(project=project, name=run_name, space_id=test_space_id)
        wait_for_client(run)
        art = trackio.Artifact(name="shared", type="model")
        art.add_file(f)
        logged = trackio.log_artifact(art)
        assert logged.version == "v0"
        trackio.finish()

    verify = Client(test_space_id, verbose=False)
    assert (
        verify.predict(
            api_name="/get_artifact_manifest",
            project=project,
            name="shared",
            spec="v1",
        )
        is None
    )

    present = verify.predict(
        api_name="/check_artifact_blobs",
        project=project,
        digests=[digest, "f" * 64],
        hf_token=huggingface_hub.get_token(),
    )
    assert present["present"] == [digest]

    _drop_local_blobs(project)
    consumer = trackio.init(project=project, name="consumer", space_id=test_space_id)
    wait_for_client(consumer)
    out = Path(trackio.use_artifact("shared:latest").download(tmp_path / "dl"))
    trackio.finish()
    assert (out / "w.bin").read_bytes() == payload


def test_use_artifact_errors_and_path_logging(
    test_space_id, temp_dir, tmp_path, wait_for_client
):
    """`use_artifact` raises on a missing artifact and on a type mismatch, while
    logging a bare file path defaults the artifact name to the file's basename
    and is retrievable by that name."""
    project = f"test_artifacts_err_{secrets.token_urlsafe(8)}"

    run = trackio.init(project=project, name="worker", space_id=test_space_id)
    wait_for_client(run)

    with pytest.raises(ValueError, match="not found"):
        trackio.use_artifact("does-not-exist:latest")
    with pytest.raises(ValueError, match="not found"):
        trackio.use_artifact("does-not-exist")

    weights = tmp_path / "weights.bin"
    weights.write_bytes(b"path-logged-bytes")
    logged = trackio.log_artifact(str(weights), name="weights", type="model")
    assert logged.name == "weights"
    assert logged.version == "v0"

    with pytest.raises(ValueError, match="type"):
        trackio.use_artifact("weights", type="dataset")

    fetched = trackio.use_artifact("weights", type="model")
    assert fetched.version == "v0"
    out = Path(fetched.download(tmp_path / "dl"))
    trackio.finish()
    assert (out / "weights.bin").read_bytes() == b"path-logged-bytes"
