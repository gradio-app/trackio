from types import SimpleNamespace
from unittest.mock import patch

from huggingface_hub import Volume
from huggingface_hub.errors import BucketNotFoundError, RepositoryNotFoundError

from trackio import deploy
from trackio.bucket_storage import _list_bucket_file_paths


def test_get_source_install_dependencies_includes_mcp():
    dependencies = deploy._get_source_install_dependencies().splitlines()

    assert any(dep.startswith("pyarrow>=") for dep in dependencies)
    assert any(dep.startswith("mcp>=") for dep in dependencies)


def test_get_space_install_requirement_includes_mcp_extra():
    requirement = deploy._get_space_install_requirement()

    assert requirement == f"trackio[spaces,mcp]=={deploy.trackio.__version__}"


@patch("trackio.deploy.huggingface_hub.add_space_variable")
@patch("trackio.deploy.huggingface_hub.HfApi")
def test_get_source_bucket_falls_back_to_space_info_runtime(
    mock_hf_api, mock_add_space_variable
):
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
    mock_add_space_variable.assert_called_once_with(
        "abidlabs/example-space", "TRACKIO_DIR", "/data/trackio"
    )


def _not_found_response():
    return SimpleNamespace(status_code=404, headers={}, request=None)


def _make_hf_api(*, space_exists, volumes=(), existing_bucket_ids=()):
    def space_info(space_id):
        if space_exists:
            return SimpleNamespace(runtime=SimpleNamespace(volumes=list(volumes)))
        raise RepositoryNotFoundError("missing", response=_not_found_response())

    def bucket_info(bucket_id):
        if bucket_id in existing_bucket_ids:
            return SimpleNamespace(id=bucket_id)
        raise BucketNotFoundError("missing", response=_not_found_response())

    return SimpleNamespace(
        space_info=space_info,
        bucket_info=bucket_info,
        get_space_runtime=lambda space_id: SimpleNamespace(volumes=list(volumes)),
    )


def test_resolve_auto_bucket_reuses_bucket_mounted_at_data():
    hf_api = _make_hf_api(
        space_exists=True,
        volumes=[
            Volume(type="bucket", source="u/old-bucket", mount_path="/data"),
        ],
    )

    result = deploy.resolve_auto_bucket_id("u/space", "u/space-bucket", hf_api=hf_api)

    assert result == "u/old-bucket"


def test_resolve_auto_bucket_uses_preferred_when_space_exists_without_data_mount():
    hf_api = _make_hf_api(space_exists=True, volumes=[])

    result = deploy.resolve_auto_bucket_id("u/space", "u/space-bucket", hf_api=hf_api)

    assert result == "u/space-bucket"


def test_resolve_auto_bucket_suffixes_when_existing_space_without_data_mount_bucket_taken():
    hf_api = _make_hf_api(
        space_exists=True,
        volumes=[],
        existing_bucket_ids={"u/space-bucket", "u/space-bucket-2"},
    )

    result = deploy.resolve_auto_bucket_id("u/space", "u/space-bucket", hf_api=hf_api)

    assert result == "u/space-bucket-3"


def test_resolve_auto_bucket_uses_preferred_when_neither_space_nor_bucket_exist():
    hf_api = _make_hf_api(space_exists=False, existing_bucket_ids=())

    result = deploy.resolve_auto_bucket_id("u/space", "u/space-bucket", hf_api=hf_api)

    assert result == "u/space-bucket"


def test_resolve_auto_bucket_suffixes_when_default_bucket_is_taken():
    hf_api = _make_hf_api(
        space_exists=False, existing_bucket_ids={"u/space-bucket", "u/space-bucket-2"}
    )

    result = deploy.resolve_auto_bucket_id("u/space", "u/space-bucket", hf_api=hf_api)

    assert result == "u/space-bucket-3"


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
