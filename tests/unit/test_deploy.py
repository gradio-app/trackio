from types import SimpleNamespace
from unittest.mock import patch

import pytest
from huggingface_hub import Volume

from trackio import deploy
from trackio.bucket_storage import _list_bucket_file_paths


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


@patch("trackio.deploy.time.sleep", return_value=None)
@patch("trackio.deploy._supports_http_api", side_effect=[False, True])
@patch("trackio.deploy.huggingface_hub.HfApi")
def test_wait_until_space_running_returns_when_http_api_ready(
    mock_hf_api, mock_supports_http_api, _mock_sleep
):
    api = mock_hf_api.return_value
    api.space_info.return_value = SimpleNamespace(
        runtime=SimpleNamespace(stage="BUILDING")
    )

    deploy._wait_until_space_running("abidlabs/example-space", timeout=5)

    assert mock_supports_http_api.call_count == 2
    assert api.space_info.call_count == 1


@patch("trackio.deploy.time.sleep", return_value=None)
@patch("trackio.deploy._supports_http_api", return_value=False)
@patch("trackio.deploy.huggingface_hub.HfApi")
def test_wait_until_space_running_raises_for_terminal_stage(
    mock_hf_api, _mock_supports_http_api, _mock_sleep
):
    api = mock_hf_api.return_value
    api.space_info.return_value = SimpleNamespace(
        runtime=SimpleNamespace(stage="BUILD_ERROR")
    )

    with pytest.raises(RuntimeError, match="terminal stage BUILD_ERROR"):
        deploy._wait_until_space_running("abidlabs/example-space", timeout=5)
