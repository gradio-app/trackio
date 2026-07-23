from pathlib import Path

import pytest

import trackio
from trackio.registry import Collection
from trackio.registry_storage import (
    RegistryStorage,
    parse_collection_target,
    registry_project_name,
    validate_registry_name,
)
from trackio.run import Run
from trackio.sqlite_storage import SQLiteStorage


def _ensure_registry(name="models"):
    if not RegistryStorage.registry_exists(name):
        RegistryStorage.create_registry(name)


def _link(
    registry="models",
    collection="churn",
    type="model",
    source_project="proj-a",
    source_artifact="resnet",
    source_version=0,
    aliases=None,
):
    _ensure_registry(registry)
    return RegistryStorage.link_artifact_version(
        registry=registry,
        collection=collection,
        type=type,
        source_project=source_project,
        source_artifact=source_artifact,
        source_version=source_version,
        aliases=aliases,
        run_name="run-1",
        run_id="id-1",
    )


def test_link_round_trip(temp_dir):
    result = _link(aliases=["staging"])
    assert result["collection_version"] == 0
    assert result["created"] is True
    assert result["aliases"] == ["latest", "staging"]

    described = RegistryStorage.get_collection("models", "churn")
    assert described["type"] == "model"
    assert len(described["links"]) == 1
    link = described["links"][0]
    assert link["collection_version"] == 0
    assert link["source_project"] == "proj-a"
    assert link["source_artifact"] == "resnet"
    assert link["source_version"] == 0
    assert link["aliases"] == ["latest", "staging"]


def test_collection_version_increments_across_source_artifacts(temp_dir):
    first = _link(source_artifact="resnet", source_version=0)
    second = _link(source_artifact="vgg", source_version=0)
    third = _link(source_project="proj-b", source_artifact="resnet", source_version=3)
    assert first["collection_version"] == 0
    assert second["collection_version"] == 1
    assert third["collection_version"] == 2


def test_duplicate_link_is_idempotent(temp_dir):
    first = _link()
    duplicate = _link()
    assert duplicate["collection_version"] == first["collection_version"]
    assert duplicate["created"] is False
    assert len(RegistryStorage.get_collection("models", "churn")["links"]) == 1


def test_duplicate_link_still_moves_aliases(temp_dir):
    _link(source_version=0)
    _link(source_version=1, aliases=["production"])
    relink = _link(source_version=0, aliases=["production"])
    assert relink["created"] is False
    links = RegistryStorage.get_collection("models", "churn")["links"]
    aliases = {link["collection_version"]: link["aliases"] for link in links}
    assert "production" in aliases[0]
    assert aliases[1] == ["latest"]


def test_type_mismatch_rejected_at_link_time(temp_dir):
    _link(type="model")
    with pytest.raises(ValueError, match="accepts type 'model', not 'dataset'"):
        _link(type="dataset", source_artifact="raw-data")


def test_registry_accepts_collections_of_different_types(temp_dir):
    _link(collection="churn", type="model")
    _link(collection="eval-set", type="dataset", source_artifact="golden")
    summaries = {
        c["name"]: c["type"] for c in RegistryStorage.list_collections("models")
    }
    assert summaries == {"churn": "model", "eval-set": "dataset"}


def test_create_collection_type_is_immutable(temp_dir):
    _ensure_registry()
    RegistryStorage.create_collection("models", "churn", "model")
    with pytest.raises(ValueError, match="accepts type 'model', not 'dataset'"):
        RegistryStorage.create_collection("models", "churn", "dataset")


def test_create_collection_idempotent_refreshes_description(temp_dir):
    _ensure_registry()
    created = RegistryStorage.create_collection("models", "churn", "model")
    assert created["created"] is True
    fetched = RegistryStorage.create_collection(
        "models", "churn", "model", description="the churn scorer"
    )
    assert fetched["created"] is False
    assert fetched["description"] == "the churn scorer"

    kinds = [event["kind"] for event in RegistryStorage.get_events("models")]
    assert kinds == ["create", "create", "update"]
    update = RegistryStorage.get_events("models")[-1]
    assert update["payload"]["collection"] == "churn"
    assert update["payload"]["description"] == "the churn scorer"

    RegistryStorage.create_collection(
        "models", "churn", "model", description="the churn scorer"
    )
    kinds = [event["kind"] for event in RegistryStorage.get_events("models")]
    assert kinds == ["create", "create", "update"]


def test_registry_must_be_created_explicitly(temp_dir):
    with pytest.raises(ValueError, match="does not exist"):
        RegistryStorage.link_artifact_version(
            registry="models",
            collection="churn",
            type="model",
            source_project="p",
            source_artifact="m",
            source_version=0,
            aliases=None,
        )
    with pytest.raises(ValueError, match="does not exist"):
        RegistryStorage.create_collection("models", "churn", "model")

    created = RegistryStorage.create_registry("models")
    assert created["name"] == "models"
    assert RegistryStorage.registry_exists("models")
    with pytest.raises(ValueError, match="already exists"):
        RegistryStorage.create_registry("models")

    events = RegistryStorage.get_events("models")
    assert [event["kind"] for event in events] == ["create"]
    assert "collection" not in events[0]["payload"]


def test_api_create_and_fetch_registry(temp_dir):
    registry = trackio.Api().create_registry("models")
    assert registry.name == "models"
    with pytest.raises(ValueError, match="already exists"):
        trackio.Api().create_registry("models")
    assert trackio.Api().registry("models").name == "models"
    with pytest.raises(ValueError, match="does not exist"):
        trackio.Api().registry("missing")


def test_create_registry_description(temp_dir):
    registry = trackio.Api().create_registry("models", description="Our models")
    assert registry.description == "Our models"
    assert trackio.Api().registry("models").description == "Our models"
    create = registry.events()[0]
    assert create["payload"] == {"registry": "models", "description": "Our models"}


def test_create_registry_without_description(temp_dir):
    registry = trackio.Api().create_registry("models")
    assert registry.description is None
    assert "description" not in registry.events()[0]["payload"]


def test_user_supplied_latest_alias_is_noop(temp_dir):
    linked = _link(source_version=0, aliases=["latest", "staging"])
    assert linked["aliases"] == ["latest", "staging"]
    _link(source_version=1)
    links = RegistryStorage.get_collection("models", "churn")["links"]
    aliases = {link["collection_version"]: link["aliases"] for link in links}
    assert aliases[0] == ["staging"]
    assert aliases[1] == ["latest"]


def test_alias_upsert_is_promotion(temp_dir):
    _link(source_version=0, aliases=["staging"])
    _link(source_version=1, aliases=["staging"])
    links = RegistryStorage.get_collection("models", "churn")["links"]
    aliases = {link["collection_version"]: link["aliases"] for link in links}
    assert aliases[0] == []
    assert aliases[1] == ["latest", "staging"]


def test_alias_rollback_via_relink(temp_dir):
    _link(source_version=0)
    _link(source_version=1, aliases=["production"])
    _link(source_version=0, aliases=["production"])
    links = RegistryStorage.get_collection("models", "churn")["links"]
    aliases = {link["collection_version"]: link["aliases"] for link in links}
    assert aliases[0] == ["production"]
    assert aliases[1] == ["latest"]


def test_latest_follows_newest_link(temp_dir):
    _link(source_version=0)
    _link(source_version=1)
    _link(source_version=0)
    links = RegistryStorage.get_collection("models", "churn")["links"]
    aliases = {link["collection_version"]: link["aliases"] for link in links}
    assert aliases[1] == ["latest"]
    assert aliases[0] == []


def test_unlink_removes_aliases_and_never_reuses_version(temp_dir):
    _link(source_version=0)
    _link(source_version=1, aliases=["production"])
    removed = RegistryStorage.unlink("models", "churn", 1)
    assert removed["removed_aliases"] == ["latest", "production"]
    assert [
        link["collection_version"]
        for link in RegistryStorage.get_collection("models", "churn")["links"]
    ] == [0]
    replacement = _link(source_artifact="vgg", source_version=5)
    assert replacement["collection_version"] == 2


def test_relink_after_unlink_gets_new_version(temp_dir):
    _link(source_version=0)
    RegistryStorage.unlink("models", "churn", 0)
    relinked = _link(source_version=0)
    assert relinked["created"] is True
    assert relinked["collection_version"] == 1


def test_events_written_for_every_mutation(temp_dir):
    _ensure_registry()
    RegistryStorage.create_collection("models", "churn", "model")
    _link(source_version=0)
    _link(source_version=1, aliases=["production"])
    _link(source_version=0, aliases=["production"])
    RegistryStorage.unlink("models", "churn", 1)

    events = RegistryStorage.get_events("models")
    assert [event["kind"] for event in events] == [
        "create",
        "create",
        "link",
        "link",
        "promote",
        "promote",
        "unlink",
    ]
    registry_create, create, link0, _link1, promote_new, promote_rollback, unlink = (
        events
    )
    assert registry_create["payload"] == {"registry": "models"}
    assert create["payload"]["collection"] == "churn"
    assert create["payload"]["type"] == "model"
    assert link0["payload"]["collection_version"] == 0
    assert link0["payload"]["source_artifact"] == "resnet"
    assert link0["payload"]["run_name"] == "run-1"
    assert link0["payload"]["run_id"] == "id-1"
    assert promote_new["payload"]["alias"] == "production"
    assert promote_new["payload"]["collection_version"] == 1
    assert promote_new["payload"]["previous_version"] is None
    assert promote_rollback["payload"]["collection_version"] == 0
    assert promote_rollback["payload"]["previous_version"] == 1
    assert unlink["payload"]["collection_version"] == 1
    assert unlink["payload"]["removed_aliases"] == ["latest"]
    assert all(event["ts"] for event in events)


def test_noop_promotion_writes_no_event(temp_dir):
    _link(source_version=0, aliases=["staging"])
    _link(source_version=0, aliases=["staging"])
    kinds = [event["kind"] for event in RegistryStorage.get_events("models")]
    assert kinds == ["create", "create", "link", "promote"]


def test_registry_db_coexists_with_standard_schema(temp_dir):
    _link()
    project = registry_project_name("models")
    assert project in SQLiteStorage.get_projects()
    assert SQLiteStorage.get_runs(project) == []
    assert SQLiteStorage.get_run_records(project) == []
    assert SQLiteStorage.list_artifacts(project) == []
    flags = SQLiteStorage.get_tab_availability_flags(project)
    assert flags["metrics"] is False


def test_registry_prefix_reserved_for_projects(temp_dir):
    with pytest.raises(ValueError, match="reserved for trackio registries"):
        SQLiteStorage.validate_project_name("registry-models")
    with pytest.raises(ValueError, match="reserved for trackio registries"):
        SQLiteStorage.validate_project_name("registry.-models")
    SQLiteStorage.validate_project_name("registry")
    SQLiteStorage.validate_project_name("my-registry-models")


def test_registry_and_collection_name_validation(temp_dir):
    for bad in ("", "with space", "with/slash", "with.dot", None):
        with pytest.raises(ValueError, match="Registry name"):
            validate_registry_name(bad)
    bad_targets = (
        "no-slash",
        "models/churn",
        "registry-a/b/c",
        "",
        "registry-bad name/coll",
        "registry-reg/bad name",
    )
    for bad_target in bad_targets:
        with pytest.raises(ValueError):
            parse_collection_target(bad_target)
    assert parse_collection_target("registry-models/churn.v2-final") == (
        "models",
        "churn.v2-final",
    )


def test_version_shaped_alias_rejected(temp_dir):
    with pytest.raises(ValueError, match="reserved for version pointers"):
        _link(aliases=["v3"])
    with pytest.raises(ValueError, match="Collection type must be a non-empty"):
        _link(type="")


def test_reads_on_missing_registry(temp_dir):
    assert RegistryStorage.list_collections("missing") == []
    assert RegistryStorage.get_collection("missing", "churn") is None
    assert RegistryStorage.get_events("missing") == []


def test_list_collections_summaries(temp_dir):
    _link(collection="churn", source_version=0)
    _link(collection="churn", source_version=1)
    RegistryStorage.create_collection("models", "empty", "model")
    summaries = {c["name"]: c for c in RegistryStorage.list_collections("models")}
    assert summaries["churn"]["num_links"] == 2
    assert summaries["churn"]["latest_version"] == 1
    assert summaries["empty"]["num_links"] == 0
    assert summaries["empty"]["latest_version"] is None


def test_link_artifact_e2e_round_trip(temp_dir, tmp_path):
    weights = tmp_path / "model.pt"
    weights.write_bytes(b"weights-v0")

    registry = trackio.Api().create_registry("models")
    run = trackio.init(project="churn-experiments", name="exp-1")
    artifact = trackio.log_artifact(
        weights, name="resnet", type="model", aliases=["best"]
    )
    linked = run.link_artifact(
        artifact, "registry-models/churn-model", aliases=["staging"]
    )
    trackio.finish()

    assert isinstance(linked, trackio.Artifact)
    assert linked.name == "churn-model"
    assert linked.project == "registry-models"
    assert linked.type == "model"
    assert linked.version == "v0"
    assert sorted(linked.aliases) == ["latest", "staging"]
    assert linked.qualified_name == "registry-models/churn-model:v0"
    assert linked.manifest_digest == artifact.manifest_digest
    assert linked.size == artifact.size
    assert linked.manifest == artifact.manifest

    assert linked.is_link is True
    assert linked.source_name == "resnet"
    assert linked.source_version == "v0"
    assert linked.source_project == "churn-experiments"
    assert linked.source_qualified_name == artifact.qualified_name
    assert artifact.is_link is False
    assert artifact.source_name == artifact.name
    assert artifact.source_version == artifact.version
    assert artifact.source_project == artifact.project
    assert artifact.source_qualified_name == artifact.qualified_name

    collection = registry.collection("churn-model")
    assert collection.type == "model"
    assert collection.num_links == 1
    assert collection.latest_version == 0
    link = collection.links[0]
    assert link["source_project"] == "churn-experiments"
    assert link["source_artifact"] == "resnet"
    assert link["source_version"] == 0
    kinds = [event["kind"] for event in registry.events()]
    assert kinds == ["create", "create", "link", "promote"]


def test_link_of_linked_artifact_links_the_source(temp_dir, tmp_path):
    weights = tmp_path / "model.pt"
    weights.write_bytes(b"weights")
    trackio.Api().create_registry("models")
    run = trackio.init(project="exp", name="run")
    artifact = trackio.log_artifact(weights, name="m", type="model")
    linked = run.link_artifact(artifact, "registry-models/churn")
    relinked = run.link_artifact(linked, "registry-models/other")
    trackio.finish()

    assert relinked.source_qualified_name == artifact.qualified_name
    links = trackio.Api().registry("models").collection("other").links
    assert links[0]["source_project"] == "exp"
    assert links[0]["source_artifact"] == "m"
    assert links[0]["source_version"] == 0


def test_download_on_linked_artifact_raises(temp_dir, tmp_path):
    weights = tmp_path / "model.pt"
    weights.write_bytes(b"weights")
    trackio.Api().create_registry("models")
    run = trackio.init(project="exp", name="run")
    artifact = trackio.log_artifact(weights, name="m", type="model")
    linked = run.link_artifact(artifact, "registry-models/churn")
    trackio.finish()

    with pytest.raises(NotImplementedError, match="registry resolution"):
        linked.download()
    assert Path(artifact.download(tmp_path / "dl"), "model.pt").exists()


def test_artifact_link_local(temp_dir, tmp_path):
    weights = tmp_path / "model.pt"
    weights.write_bytes(b"weights")
    trackio.Api().create_registry("models")
    trackio.init(project="exp", name="run")
    artifact = trackio.log_artifact(weights, name="m", type="model")
    linked = artifact.link("registry-models/churn", aliases=["staging"])
    trackio.finish()

    assert linked.is_link is True
    assert linked.qualified_name == "registry-models/churn:v0"
    assert sorted(linked.aliases) == ["latest", "staging"]
    links = trackio.Api().registry("models").collection("churn").links
    assert links[0]["source_artifact"] == "m"
    link_event = next(
        e for e in trackio.Api().registry("models").events() if e["kind"] == "link"
    )
    assert link_event["payload"]["run_name"] is None


def test_artifact_link_requires_logged(temp_dir):
    trackio.Api().create_registry("models")
    artifact = trackio.Artifact(name="m", type="model")
    with pytest.raises(RuntimeError, match="has not been logged"):
        artifact.link("registry-models/churn")


def test_artifact_unlink_local(temp_dir, tmp_path):
    weights = tmp_path / "model.pt"
    weights.write_bytes(b"weights")
    trackio.Api().create_registry("models")
    run = trackio.init(project="exp", name="run")
    artifact = trackio.log_artifact(weights, name="m", type="model")
    linked = run.link_artifact(artifact, "registry-models/churn", aliases=["staging"])
    trackio.finish()

    assert trackio.Api().registry("models").collection("churn").num_links == 1
    linked.unlink()
    assert trackio.Api().registry("models").collection("churn").num_links == 0
    assert trackio.Api().registry("models").events()[-1]["kind"] == "unlink"


def test_artifact_unlink_requires_link(temp_dir, tmp_path):
    weights = tmp_path / "model.pt"
    weights.write_bytes(b"weights")
    trackio.init(project="exp", name="run")
    artifact = trackio.log_artifact(weights, name="m", type="model")
    trackio.finish()
    with pytest.raises(ValueError, match="removes a registry link"):
        artifact.unlink()


def test_link_into_missing_registry_raises(temp_dir, tmp_path):
    weights = tmp_path / "model.pt"
    weights.write_bytes(b"weights")
    run = trackio.init(project="exp", name="run")
    artifact = trackio.log_artifact(weights, name="m", type="model")
    with pytest.raises(ValueError, match="does not exist"):
        run.link_artifact(artifact, "registry-models/churn")
    trackio.finish()
    with pytest.raises(ValueError, match="does not exist"):
        trackio.Api().registry("models").create_collection("churn", "model")


def test_link_artifact_requires_artifact_instance(temp_dir, tmp_path):
    for i in (0, 1):
        weights = tmp_path / f"model{i}.pt"
        weights.write_bytes(b"weights-%d" % i)
        trackio.init(project="exp", name=f"run-{i}")
        trackio.log_artifact(
            weights, name="m", type="model", aliases=["best"] if i == 0 else None
        )
        trackio.finish()

    trackio.Api().create_registry("models")
    run = trackio.init(project="exp", name="publisher")
    by_alias = run.link_artifact(
        trackio.use_artifact("m:best"), "registry-models/churn"
    )
    by_version = run.link_artifact(
        trackio.use_artifact("m:v1"), "registry-models/churn"
    )
    with pytest.raises(TypeError, match="expects an Artifact instance"):
        run.link_artifact("m:v0", "registry-models/churn")
    trackio.finish()

    assert by_alias.version == "v0"
    assert by_version.version == "v1"
    links = trackio.Api().registry("models").collection("churn").links
    source_by_collection_version = {
        link["collection_version"]: link["source_version"] for link in links
    }
    assert source_by_collection_version == {0: 0, 1: 1}


def test_link_artifact_cross_project_instance(temp_dir, tmp_path):
    weights = tmp_path / "model.pt"
    weights.write_bytes(b"weights")
    trackio.init(project="team-a", name="producer")
    trackio.log_artifact(weights, name="m", type="model")
    fetched = trackio.use_artifact("m:latest")
    trackio.finish()

    trackio.Api().create_registry("models")
    run = trackio.init(project="team-b", name="publisher")
    linked = run.link_artifact(fetched, "registry-models/shared")
    trackio.finish()
    assert linked.version == "v0"
    links = trackio.Api().registry("models").collection("shared").links
    assert links[0]["source_project"] == "team-a"


def test_link_artifact_auto_creates_typed_collection(temp_dir, tmp_path):
    weights = tmp_path / "model.pt"
    weights.write_bytes(b"weights")
    data = tmp_path / "data.csv"
    data.write_text("a,b\n")

    trackio.Api().create_registry("models")
    run = trackio.init(project="exp", name="run")
    model_artifact = trackio.log_artifact(weights, name="m", type="model")
    run.link_artifact(model_artifact, "registry-models/churn")
    data_artifact = trackio.log_artifact(data, name="d", type="dataset")
    with pytest.raises(ValueError, match="accepts type 'model', not 'dataset'"):
        run.link_artifact(data_artifact, "registry-models/churn")
    trackio.finish()

    assert trackio.Api().registry("models").collection("churn").type == "model"


def test_reference_artifact_links_regardless_of_checksum(temp_dir, tmp_path):
    data = tmp_path / "data.csv"
    data.write_text("a,b\n1,2\n")

    trackio.Api().create_registry("datasets")
    run = trackio.init(project="exp", name="run")
    unchecksummed = trackio.Artifact(name="raw", type="dataset")
    unchecksummed.add_reference(data.as_uri(), checksum=False)
    logged_unchecksummed = trackio.log_artifact(unchecksummed)
    run.link_artifact(logged_unchecksummed, "registry-datasets/raw")

    checksummed = trackio.Artifact(name="hashed", type="dataset")
    checksummed.add_reference(data.as_uri(), checksum=True)
    logged_checksummed = trackio.log_artifact(checksummed)
    run.link_artifact(logged_checksummed, "registry-datasets/hashed")
    trackio.finish()

    registry = trackio.Api().registry("datasets")
    assert registry.collection("raw").links[0]["source_artifact"] == "raw"
    assert registry.collection("hashed").links[0]["source_artifact"] == "hashed"


def test_link_artifact_auto_logs_unlogged_instance(temp_dir, tmp_path):
    weights = tmp_path / "model.pt"
    weights.write_bytes(b"weights")
    trackio.Api().create_registry("models")
    run = trackio.init(project="exp", name="run")
    artifact = trackio.Artifact(name="m", type="model")
    artifact.add_file(weights)
    linked = run.link_artifact(artifact, "registry-models/churn")
    trackio.finish()

    assert artifact.version == "v0"
    assert artifact.project == "exp"
    assert linked.version == "v0"
    assert SQLiteStorage.resolve_artifact_version("exp", "m", "latest") is not None
    links = trackio.Api().registry("models").collection("churn").links
    assert links[0]["source_project"] == "exp"
    assert links[0]["source_version"] == 0


def test_link_remotely_fetched_artifact_locally_raises(temp_dir, tmp_path):
    weights = tmp_path / "model.pt"
    weights.write_bytes(b"weights")
    trackio.Api().create_registry("models")
    run = trackio.init(project="exp", name="run")
    artifact = trackio.log_artifact(weights, name="m", type="model")
    artifact._remote_source = {"space_id": "user/space", "write_token": None}
    with pytest.raises(NotImplementedError, match="not supported yet"):
        run.link_artifact(artifact, "registry-models/churn")
    trackio.finish()


class _StubClient:
    def __init__(self):
        self.calls = []

    def predict(self, api_name=None, **kwargs):
        self.calls.append((api_name, kwargs))
        return None


def test_link_artifact_remote_run_not_supported(temp_dir):
    run = Run(
        url="fake_url",
        project="exp",
        client=_StubClient(),
        name="run",
        space_id="user/space",
        existing_runs=[],
        initial_last_step=0,
    )
    art = trackio.Artifact(name="m", type="model")
    art._hydrate_from_db(
        project="exp",
        version=0,
        aliases=["latest"],
        manifest=[{"path": "w.bin", "digest": "a" * 64, "size": 3}],
        manifest_digest="a" * 64,
        size_bytes=3,
    )
    with pytest.raises(NotImplementedError, match="not supported yet"):
        run.link_artifact(art, "registry-models/churn", aliases=["staging"])


def test_init_rejects_reserved_registry_prefix(temp_dir):
    with pytest.raises(ValueError, match="reserved for trackio registries"):
        trackio.init(project="registry-models")


def test_registry_handle_validates_name(temp_dir):
    with pytest.raises(ValueError, match="Registry name"):
        trackio.Api().create_registry("bad/name")
    with pytest.raises(ValueError, match="Registry name"):
        trackio.Api().registry("bad/name")
    registry = trackio.Api().create_registry("models")
    assert registry.name == "models"
    assert repr(registry) == "Registry('models')"
    assert registry.collections() == []


def test_registry_handle_create_and_describe(temp_dir):
    registry = trackio.Api().create_registry("models")
    collection = registry.create_collection(
        "churn", "model", description="the churn scorer"
    )
    assert isinstance(collection, Collection)
    assert collection.name == "churn"
    assert collection.type == "model"
    assert collection.description == "the churn scorer"
    assert collection.num_links == 0
    assert collection.latest_version is None
    assert collection.links == []

    listed = registry.collections()
    assert [c.name for c in listed] == ["churn"]
    assert listed[0].links == []

    assert registry.collection("missing") is None
    assert Path(temp_dir, "registry-models.db").exists()
