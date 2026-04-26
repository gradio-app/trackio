import io
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from trackio import deploy
from trackio.bucket_storage import _list_bucket_file_paths
from trackio.frontend_config import ResolvedFrontend


def test_get_source_install_dependencies_includes_mcp():
    dependencies = deploy._get_source_install_dependencies().splitlines()

    assert any(dep.startswith("pyarrow>=") for dep in dependencies)
    assert any(dep.startswith("mcp>=") for dep in dependencies)


def test_get_space_install_requirement_includes_mcp_extra():
    requirement = deploy._get_space_install_requirement()

    assert requirement == f"trackio[spaces,mcp]=={deploy.trackio.__version__}"


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


class _FakeHfApi:
    def __init__(self):
        self.uploaded_files = []
        self.uploaded_folders = []

    def upload_file(self, **kwargs):
        fileobj = kwargs["path_or_fileobj"]
        if isinstance(fileobj, io.BytesIO):
            payload = fileobj.getvalue().decode("utf-8")
        else:
            payload = fileobj.read().decode("utf-8")
        self.uploaded_files.append(
            {
                "path_in_repo": kwargs["path_in_repo"],
                "payload": payload,
            }
        )

    def upload_folder(self, **kwargs):
        self.uploaded_folders.append(kwargs)


def test_deploy_as_space_uploads_custom_frontend(tmp_path, monkeypatch):
    frontend_dir = tmp_path / "custom-frontend"
    frontend_dir.mkdir()
    (frontend_dir / "index.html").write_text("<!doctype html>")

    fake_api = _FakeHfApi()
    monkeypatch.setattr(deploy.huggingface_hub, "HfApi", lambda: fake_api)
    monkeypatch.setattr(deploy.huggingface_hub, "create_repo", lambda *a, **k: None)
    monkeypatch.setattr(
        deploy.huggingface_hub, "add_space_variable", lambda *a, **k: None
    )
    monkeypatch.setattr(
        deploy.huggingface_hub.utils, "disable_progress_bars", lambda: None
    )
    monkeypatch.setattr(deploy.huggingface_hub.utils, "get_token", lambda: None)
    monkeypatch.setattr(deploy, "_is_trackio_installed_from_source", lambda: False)
    monkeypatch.setattr(
        deploy,
        "resolve_frontend_dir",
        lambda frontend_dir=None, announce=False: ResolvedFrontend(
            path=frontend_dir.resolve(),
            source="argument",
            is_custom=True,
        ),
    )

    deploy.deploy_as_space("abidlabs/demo-space", frontend_dir=frontend_dir)

    custom_uploads = [
        call
        for call in fake_api.uploaded_folders
        if call.get("path_in_repo") == "trackio_custom_frontend"
    ]
    assert len(custom_uploads) == 1
    assert custom_uploads[0]["folder_path"] == str(frontend_dir)

    app_upload = next(
        item for item in fake_api.uploaded_files if item["path_in_repo"] == "app.py"
    )
    assert (
        'trackio.show(frontend_dir="trackio_custom_frontend")' in app_upload["payload"]
    )


def test_deploy_as_static_space_uploads_resolved_frontend(tmp_path, monkeypatch):
    frontend_dir = tmp_path / "custom-static"
    frontend_dir.mkdir()
    (frontend_dir / "index.html").write_text("<!doctype html>")

    fake_api = _FakeHfApi()
    monkeypatch.setattr(deploy.huggingface_hub, "HfApi", lambda: fake_api)
    monkeypatch.setattr(deploy.huggingface_hub, "create_repo", lambda *a, **k: None)
    monkeypatch.setattr(
        deploy,
        "resolve_frontend_dir",
        lambda frontend_dir=None, announce=False: ResolvedFrontend(
            path=frontend_dir.resolve(),
            source="argument",
            is_custom=True,
        ),
    )

    with pytest.warns(UserWarning, match="private=True is ignored"):
        deploy.deploy_as_static_space(
            "abidlabs/static-space",
            None,
            "demo-project",
            private=True,
            frontend_dir=frontend_dir,
        )

    assert any(
        call["folder_path"] == str(frontend_dir) for call in fake_api.uploaded_folders
    )
    config_upload = next(
        item for item in fake_api.uploaded_files if item["path_in_repo"] == "config.json"
    )
    config = json.loads(config_upload["payload"])
    assert config["private"] is False
