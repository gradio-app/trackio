import pytest

import trackio
from trackio.registry_storage import resolve_collection_link
from trackio.run import Run
from trackio.sqlite_storage import SQLiteStorage


class _StubClient:
    def predict(self, api_name=None, **kwargs):
        return None


def _publish(tmp_path):
    """Two source versions linked into registry-models/churn-model:
    v0 (staging) and v1 (production, latest)."""
    trackio.Api().create_registry("models")
    run = trackio.init(project="churn-experiments", name="exp-1")
    w0 = tmp_path / "w0.pt"
    w0.write_bytes(b"weights-v0")
    a0 = trackio.log_artifact(w0, name="resnet", type="model")
    run.link_artifact(a0, "registry-models/churn-model", aliases=["staging"])
    w1 = tmp_path / "w1.pt"
    w1.write_bytes(b"weights-v1")
    a1 = trackio.log_artifact(w1, name="resnet", type="model")
    run.link_artifact(a1, "registry-models/churn-model", aliases=["production"])
    trackio.finish()
    return a0, a1


def test_resolve_collection_link_specs():
    links = [
        {"collection_version": 1, "aliases": ["latest", "production"]},
        {"collection_version": 0, "aliases": ["staging"]},
    ]
    assert resolve_collection_link(links, None)["collection_version"] == 1
    assert resolve_collection_link(links, "latest")["collection_version"] == 1
    assert resolve_collection_link(links, "v0")["collection_version"] == 0
    assert resolve_collection_link(links, "staging")["collection_version"] == 0
    with pytest.raises(ValueError, match="v7"):
        resolve_collection_link(links, "v7")
    with pytest.raises(ValueError, match="nope"):
        resolve_collection_link(links, "nope")
    with pytest.raises(ValueError, match="empty"):
        resolve_collection_link([], None)


def test_use_artifact_resolves_alias_from_registry(temp_dir, tmp_path):
    a0, a1 = _publish(tmp_path)
    consumer = trackio.init(project="deploy", name="deploy-1")
    art = consumer.use_artifact("registry-models/churn-model:production")
    trackio.finish()

    assert art.is_link is True
    assert art.name == "churn-model"
    assert art.project == "registry-models"
    assert art.version == "v1"
    assert art.qualified_name == "registry-models/churn-model:v1"
    assert sorted(art.aliases) == ["latest", "production"]
    assert art.type == "model"
    assert art.manifest == a1.manifest
    assert art.manifest_digest == a1.manifest_digest
    assert art.size == a1.size
    assert art.source_qualified_name == a1.qualified_name
    assert art.source_project == "churn-experiments"

    consumers = SQLiteStorage.get_artifact_consumers(
        "churn-experiments",
        SQLiteStorage.get_artifact_manifest("churn-experiments", "resnet", "v1")[
            "version_id"
        ],
    )
    assert [c["run_name"] for c in consumers] == ["deploy-1"]


def test_use_artifact_registry_version_and_latest(temp_dir, tmp_path):
    a0, a1 = _publish(tmp_path)
    consumer = trackio.init(project="deploy", name="deploy-2")
    staged = consumer.use_artifact("registry-models/churn-model:v0")
    latest = consumer.use_artifact("registry-models/churn-model")
    trackio.finish()

    assert staged.version == "v0"
    assert staged.source_qualified_name == a0.qualified_name
    assert latest.version == "v1"
    assert latest.source_qualified_name == a1.qualified_name


def test_linked_artifact_downloads_source_bytes(temp_dir, tmp_path):
    _publish(tmp_path)
    consumer = trackio.init(project="deploy", name="deploy-3")
    art = consumer.use_artifact("registry-models/churn-model:staging")
    out = art.download(root=tmp_path / "out")
    trackio.finish()

    assert (tmp_path / "out" / "w0.pt").read_bytes() == b"weights-v0"
    assert out == str(tmp_path / "out")


def test_linked_artifact_default_download_root_uses_registry_location(
    temp_dir, tmp_path, monkeypatch
):
    _publish(tmp_path)
    monkeypatch.chdir(tmp_path)
    consumer = trackio.init(project="deploy", name="deploy-4")
    out = consumer.use_artifact("registry-models/churn-model:v1").download()
    trackio.finish()

    assert out.endswith("registry-models/churn-model_v1")


def test_use_artifact_accepts_linked_artifact_instance(temp_dir, tmp_path):
    a0, a1 = _publish(tmp_path)
    linked = trackio.Api().registry("models")
    consumer = trackio.init(project="deploy", name="deploy-5")
    first = consumer.use_artifact("registry-models/churn-model:production")
    again = consumer.use_artifact(first)
    trackio.finish()

    assert linked.collection("churn-model").num_links == 2
    assert again.qualified_name == first.qualified_name
    assert again.source_qualified_name == a1.qualified_name


def test_use_artifact_registry_type_mismatch(temp_dir, tmp_path):
    _publish(tmp_path)
    consumer = trackio.init(project="deploy", name="deploy-6")
    with pytest.raises(ValueError, match="has type 'model', not 'dataset'"):
        consumer.use_artifact("registry-models/churn-model:production", type="dataset")
    trackio.finish()


def test_use_artifact_registry_errors(temp_dir, tmp_path):
    _publish(tmp_path)
    consumer = trackio.init(project="deploy", name="deploy-7")
    with pytest.raises(ValueError, match="Registry 'nope' does not exist"):
        consumer.use_artifact("registry-nope/churn-model:production")
    with pytest.raises(ValueError, match="Collection 'other' not found"):
        consumer.use_artifact("registry-models/other")
    with pytest.raises(ValueError, match="'canary'"):
        consumer.use_artifact("registry-models/churn-model:canary")
    with pytest.raises(ValueError, match="empty version/alias"):
        consumer.use_artifact("registry-models/churn-model:")
    trackio.finish()


def test_use_artifact_registry_from_remote_run_not_supported(temp_dir):
    run = Run(
        url="fake_url",
        project="exp",
        client=_StubClient(),
        name="run",
        space_id="user/space",
        existing_runs=[],
        initial_last_step=0,
    )
    with pytest.raises(NotImplementedError, match="registry"):
        run.use_artifact("registry-models/churn-model:production")
