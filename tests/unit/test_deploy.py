from types import SimpleNamespace
from unittest.mock import patch

import httpx
from huggingface_hub import Volume
from huggingface_hub.errors import BucketNotFoundError, RepositoryNotFoundError

from trackio import deploy
from trackio.bucket_storage import _list_bucket_file_paths


class StubHfApi:
    def __init__(self, *, spaces=None, buckets=None):
        self.spaces = set(spaces or [])
        self.buckets = set(buckets or [])

    def space_info(self, space_id, timeout=None):
        if space_id not in self.spaces:
            raise RepositoryNotFoundError(
                "space not found",
                response=httpx.Response(
                    404,
                    request=httpx.Request(
                        "GET", f"https://huggingface.co/api/spaces/{space_id}"
                    ),
                ),
            )
        return SimpleNamespace(id=space_id)

    def bucket_info(self, bucket_id, token=None):
        if bucket_id not in self.buckets:
            raise BucketNotFoundError(
                "bucket not found",
                response=httpx.Response(
                    404,
                    request=httpx.Request(
                        "GET", f"https://huggingface.co/api/buckets/{bucket_id}"
                    ),
                ),
            )
        return SimpleNamespace(id=bucket_id)


def test_get_source_install_dependencies_includes_mcp():
    dependencies = deploy._get_source_install_dependencies().splitlines()

    assert any(dep.startswith("pyarrow>=") for dep in dependencies)
    assert any(dep.startswith("mcp>=") for dep in dependencies)


def test_get_space_install_requirement_includes_mcp_extra():
    requirement = deploy._get_space_install_requirement()

    assert requirement == f"trackio[spaces,mcp]=={deploy.trackio.__version__}"


@patch("trackio.deploy.huggingface_hub.HfApi")
def test_get_source_bucket_falls_back_to_space_info_runtime(mock_hf_api):
    api = mock_hf_api.return_value
    api.get_space_runtime.return_value = SimpleNamespace(volumes=None)
    api.space_info.return_value = SimpleNamespace(
        runtime=SimpleNamespace(
            volumes=[
                Volume(
                    type="bucket",
                    source="abidlabs/example-bucket",
                    mount_path="/data",
                )
            ]
        )
    )

    bucket_id = deploy._get_source_bucket("abidlabs/example-space")

    assert bucket_id == "abidlabs/example-bucket"


@patch("trackio.bucket_storage.huggingface_hub.list_bucket_tree")
def test_list_bucket_file_paths_uses_list_bucket_tree(mock_list_bucket_tree):
    mock_list_bucket_tree.return_value = [
        SimpleNamespace(type="folder", path="trackio/media/proj"),
        SimpleNamespace(type="file", path="trackio/media/proj/image.png"),
    ]

    paths = _list_bucket_file_paths(
        "abidlabs/example-bucket", prefix="trackio/media/proj/"
    )

    assert paths == ["trackio/media/proj/image.png"]
    mock_list_bucket_tree.assert_called_once_with(
        "abidlabs/example-bucket",
        prefix="trackio/media/proj/",
        recursive=True,
    )


def test_resolve_auto_bucket_id_reuses_existing_space_bucket(monkeypatch):
    api = StubHfApi(spaces={"user/existing-space"})
    monkeypatch.setattr(
        deploy,
        "_get_space_bucket_at_data_mount",
        lambda _space_id: "user/existing-space-bucket-7",
    )

    bucket_id = deploy.resolve_auto_bucket_id(
        "user/existing-space",
        "user/existing-space-bucket",
        hf_api=api,
    )

    assert bucket_id == "user/existing-space-bucket-7"


def test_resolve_auto_bucket_id_uses_preferred_bucket_for_new_space(monkeypatch):
    api = StubHfApi()
    monkeypatch.setattr(
        deploy, "_get_space_bucket_at_data_mount", lambda _space_id: None
    )

    bucket_id = deploy.resolve_auto_bucket_id(
        "user/new-space",
        "user/new-space-bucket",
        hf_api=api,
    )

    assert bucket_id == "user/new-space-bucket"


def test_resolve_auto_bucket_id_avoids_colliding_bucket_for_new_space(monkeypatch):
    api = StubHfApi(buckets={"user/new-space-bucket", "user/new-space-bucket-2"})
    monkeypatch.setattr(
        deploy, "_get_space_bucket_at_data_mount", lambda _space_id: None
    )

    bucket_id = deploy.resolve_auto_bucket_id(
        "user/new-space",
        "user/new-space-bucket",
        hf_api=api,
    )

    assert bucket_id == "user/new-space-bucket-3"
