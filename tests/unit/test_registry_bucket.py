from pathlib import Path

import pytest

import trackio
from trackio import registry_bucket as rb
from trackio.registry_bucket import BucketRegistryStorage
from trackio.run import Run

BUCKET = "me/models-registry"


class FakeBucket:
    """An in-memory stand-in for a Hugging Face bucket: remote path -> bytes."""

    def __init__(self):
        self.objects: dict[str, bytes] = {}
        self.created: list[tuple[str, bool | None]] = []

    def install(self, monkeypatch):
        monkeypatch.setattr(rb, "create_bucket_if_not_exists", self._create)
        monkeypatch.setattr(rb, "_list_bucket_file_paths", self._list)
        monkeypatch.setattr(rb.huggingface_hub, "batch_bucket_files", self._batch)
        monkeypatch.setattr(rb.huggingface_hub, "download_bucket_files", self._download)
        return self

    def _create(self, bucket_id, private=None):
        self.created.append((bucket_id, private))

    def _list(self, bucket_id, prefix=None):
        return [p for p in self.objects if prefix is None or p.startswith(prefix)]

    def _batch(self, bucket_id, *, add=None, copy=None, delete=None, token=None):
        for data, remote_path in add or []:
            self.objects[remote_path] = (
                data if isinstance(data, bytes) else Path(data).read_bytes()
            )

    def _download(self, bucket_id, files, *, raise_on_missing_files=False, token=None):
        for remote_path, local_path in files:
            if remote_path not in self.objects:
                continue
            local = Path(local_path)
            local.parent.mkdir(parents=True, exist_ok=True)
            local.write_bytes(self.objects[remote_path])

    def event_paths(self, registry="models"):
        prefix = f"trackio/registries/{registry}/events/"
        return sorted(p for p in self.objects if p.startswith(prefix))


@pytest.fixture
def bucket(monkeypatch):
    return FakeBucket().install(monkeypatch)


def _link(storage, source_version=0, source_artifact="resnet", aliases=None, **kwargs):
    return storage.link_artifact_version(
        registry="models",
        collection="churn",
        type="model",
        source_project="exp",
        source_artifact=source_artifact,
        source_version=source_version,
        aliases=aliases,
        run_name="run-1",
        run_id="id-1",
        **kwargs,
    )


def test_bucket_registry_round_trip(temp_dir, bucket):
    storage = BucketRegistryStorage(BUCKET)
    storage.create_registry("models", description="Our models")
    assert bucket.created == [(BUCKET, True)]
    assert f"trackio/registries/models/{rb.MANIFEST_FILENAME}" in bucket.objects
    assert storage.get_registry("models")["description"] == "Our models"

    first = _link(storage, source_version=0)
    second = _link(storage, source_version=1, aliases=["production"])
    assert (first["collection_version"], second["collection_version"]) == (0, 1)

    collection = storage.get_collection("models", "churn")
    aliases = {
        link["collection_version"]: link["aliases"] for link in collection["links"]
    }
    assert aliases == {0: [], 1: ["latest", "production"]}
    assert [event["kind"] for event in storage.get_events("models")] == [
        "create",
        "create",
        "link",
        "link",
        "promote",
    ]
    assert len(bucket.event_paths()) == 5


def test_registry_state_is_a_fold_of_the_bucket(temp_dir, bucket):
    """Every reader rebuilds the same state from the event objects alone, so a
    machine that has never seen the registry (or lost its cache) is not
    special."""
    writer = BucketRegistryStorage(BUCKET)
    writer.create_registry("models")
    _link(writer, source_version=0)
    _link(writer, source_version=1, aliases=["staging"])
    expected = writer.get_collection("models", "churn")

    Path(writer.cache_db_path("models")).unlink()
    reader = BucketRegistryStorage(BUCKET)
    assert reader.get_collection("models", "churn") == expected
    assert reader.get_collection("models", "churn") == expected


def test_concurrent_writers_get_distinct_versions(temp_dir, bucket):
    """Two machines link at the same time against their own projections. Neither
    can reserve a version number, so the fold assigns them in event order."""
    machine_a = BucketRegistryStorage(BUCKET)
    machine_b = BucketRegistryStorage(BUCKET)
    machine_a.create_registry("models")
    _link(machine_a, source_artifact="resnet", source_version=0)

    Path(machine_b.cache_db_path("models")).unlink(missing_ok=True)
    _link(machine_b, source_artifact="vgg", source_version=0)

    for machine in (machine_a, machine_b):
        links = machine.get_collection("models", "churn")["links"]
        assert {
            (link["source_artifact"], link["collection_version"]) for link in links
        } == {("resnet", 0), ("vgg", 1)}
        assert links[0]["aliases"] == ["latest"]


def test_unlink_against_a_bucket(temp_dir, bucket):
    storage = BucketRegistryStorage(BUCKET)
    storage.create_registry("models")
    _link(storage, source_version=0)
    _link(storage, source_version=1)

    removed = storage.unlink("models", "churn", 1)
    assert removed["removed_aliases"] == ["latest"]
    assert removed["latest_version"] == 0
    links = storage.get_collection("models", "churn")["links"]
    assert [link["collection_version"] for link in links] == [0]
    assert links[0]["aliases"] == ["latest"]


def test_api_registry_with_bucket_id(temp_dir, bucket):
    registry = trackio.Api().create_registry("models", bucket_id=BUCKET)
    assert registry.bucket_id == BUCKET
    with pytest.raises(ValueError, match="already exists"):
        trackio.Api().create_registry("models", bucket_id=BUCKET)
    with pytest.raises(ValueError, match="does not exist in bucket"):
        trackio.Api().registry("missing", bucket_id=BUCKET)

    fetched = trackio.Api().registry("models", bucket_id=BUCKET)
    fetched.create_collection("churn", "model", description="the churn scorer")
    assert fetched.collection("churn").description == "the churn scorer"

    with pytest.raises(ValueError, match="does not exist"):
        trackio.Api().registry("models")


def test_space_backed_run_publishes_into_a_bucket_registry(temp_dir, bucket):
    """The point of a bucket registry: a run whose bytes live on a Space can
    publish, and the link records where to find them."""
    BucketRegistryStorage(BUCKET).create_registry("models")
    run = Run(
        url="fake_url",
        project="exp",
        client=None,
        name="run",
        space_id="user/space",
        existing_runs=[],
        initial_last_step=0,
    )
    artifact = trackio.Artifact(name="m", type="model")
    artifact._hydrate_from_db(
        project="exp",
        version=3,
        aliases=["latest"],
        manifest=[{"path": "w.bin", "digest": "a" * 64, "size": 3}],
        manifest_digest="a" * 64,
        size_bytes=3,
    )
    artifact._remote_source = {"space_id": "user/space", "write_token": None}

    linked = run.link_artifact(
        artifact, "registry-models/churn", aliases=["staging"], bucket_id=BUCKET
    )
    assert linked.version == "v0"
    assert sorted(linked.aliases) == ["latest", "staging"]
    assert linked.source_qualified_name == "exp/m:v3"

    link = BucketRegistryStorage(BUCKET).get_collection("models", "churn")["links"][0]
    assert link["source_space_id"] == "user/space"

    linked.unlink()
    assert (
        BucketRegistryStorage(BUCKET).get_collection("models", "churn")["links"] == []
    )
