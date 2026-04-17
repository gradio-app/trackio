from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from huggingface_hub import Volume

from trackio import deploy
from trackio.bucket_storage import _list_bucket_file_paths


def test_get_source_install_dependencies_includes_mcp():
    dependencies = deploy._get_source_install_dependencies().splitlines()

    assert any(dep.startswith("pyarrow>=") for dep in dependencies)
    assert any(dep.startswith("mcp>=") for dep in dependencies)


def test_get_source_install_space_extra_dependencies_includes_spaces_and_mcp():
    dependencies = deploy._get_source_install_space_extra_dependencies()

    assert any(dep.startswith("pyarrow>=") for dep in dependencies)
    assert any(dep.startswith("mcp>=") for dep in dependencies)
    assert not any(dep.startswith("huggingface-hub>=") for dep in dependencies)


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


@patch("trackio.deploy.create_bucket_if_not_exists")
@patch("trackio.deploy._is_trackio_installed_from_source", return_value=False)
@patch("trackio.deploy.huggingface_hub")
def test_deploy_as_space_docker_uploads_dockerfile_and_docker_readme(
    mock_hub, _mock_source, _mock_bucket
):
    hf_api = mock_hub.HfApi.return_value
    hf_api.upload_file = MagicMock()
    mock_hub.utils.get_token.return_value = None

    deploy.deploy_as_space("user/space", sdk="docker")

    mock_hub.create_repo.assert_called_with(
        "user/space",
        private=None,
        space_sdk="docker",
        space_storage=None,
        repo_type="space",
        exist_ok=True,
    )

    uploaded = {
        call.kwargs["path_in_repo"]: call.kwargs["path_or_fileobj"].getvalue().decode()
        for call in hf_api.upload_file.call_args_list
    }
    assert "Dockerfile" in uploaded
    assert uploaded["Dockerfile"].startswith("FROM python:3.11-slim")
    assert "sdk: docker" in uploaded["README.md"]
    assert "app_port: 7860" in uploaded["README.md"]
    assert "sdk: gradio" not in uploaded["README.md"]


@patch("trackio.deploy.create_bucket_if_not_exists")
@patch("trackio.deploy._is_trackio_installed_from_source", return_value=False)
@patch("trackio.deploy.huggingface_hub")
def test_deploy_as_space_gradio_still_works(mock_hub, _mock_source, _mock_bucket):
    hf_api = mock_hub.HfApi.return_value
    hf_api.upload_file = MagicMock()
    mock_hub.utils.get_token.return_value = None

    deploy.deploy_as_space("user/space", sdk="gradio")

    mock_hub.create_repo.assert_called_with(
        "user/space",
        private=None,
        space_sdk="gradio",
        space_storage=None,
        repo_type="space",
        exist_ok=True,
    )
    uploaded = {
        call.kwargs["path_in_repo"]: call.kwargs["path_or_fileobj"].getvalue().decode()
        for call in hf_api.upload_file.call_args_list
    }
    assert "Dockerfile" not in uploaded
    assert "sdk: gradio" in uploaded["README.md"]
    assert "app_port" not in uploaded["README.md"]


def test_deploy_as_space_rejects_unknown_sdk():
    with pytest.raises(ValueError, match="sdk must be"):
        deploy.deploy_as_space("user/space", sdk="streamlit")


@patch("trackio.deploy.create_bucket_if_not_exists")
@patch("trackio.deploy._build_source_install_wheel")
@patch("trackio.deploy._is_trackio_installed_from_source", return_value=True)
@patch("trackio.deploy.huggingface_hub")
def test_deploy_as_space_docker_source_install_uploads_wheel_not_source_tree(
    mock_hub, _mock_source, mock_build_wheel, _mock_bucket
):
    hf_api = mock_hub.HfApi.return_value
    hf_api.upload_file = MagicMock()
    hf_api.upload_folder = MagicMock()
    mock_hub.utils.get_token.return_value = None
    mock_build_wheel.return_value = Path("/tmp/trackio-0.0.1-py3-none-any.whl")

    deploy.deploy_as_space("user/space", sdk="docker")

    uploaded_text = {}
    uploaded_paths = {}
    for call in hf_api.upload_file.call_args_list:
        path_in_repo = call.kwargs["path_in_repo"]
        payload = call.kwargs["path_or_fileobj"]
        if hasattr(payload, "getvalue"):
            uploaded_text[path_in_repo] = payload.getvalue().decode()
        else:
            uploaded_paths[path_in_repo] = payload

    assert uploaded_paths["trackio-0.0.1-py3-none-any.whl"] == "/tmp/trackio-0.0.1-py3-none-any.whl"
    assert "COPY --chown=user trackio-0.0.1-py3-none-any.whl" in uploaded_text["Dockerfile"]
    assert "./trackio-0.0.1-py3-none-any.whl" in uploaded_text["requirements.txt"]
    assert "pyarrow>=" in uploaded_text["requirements.txt"]
    assert "mcp>=" in uploaded_text["requirements.txt"]
    hf_api.upload_folder.assert_not_called()


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
