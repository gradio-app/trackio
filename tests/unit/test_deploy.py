import importlib
import io
import json
from types import SimpleNamespace
from unittest.mock import patch

import huggingface_hub
import pytest

from trackio import deploy
from trackio.bucket_storage import _list_bucket_file_paths
from trackio.frontend_config import ResolvedFrontend

hub_httpx = importlib.import_module(
    "httpx2" if int(huggingface_hub.__version__.split(".")[0]) >= 2 else "httpx"
)


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
        "abidlabs/example-bucket", prefix="trackio/media/proj/", token=False
    )

    assert paths == ["trackio/media/proj/image.png"]
    mock_list_bucket_tree.assert_called_once_with(
        "abidlabs/example-bucket",
        prefix="trackio/media/proj/",
        recursive=True,
        token=False,
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

    deploy.deploy_as_static_space(
        "abidlabs/static-space",
        None,
        "demo-project",
        frontend_dir=frontend_dir,
    )

    assert any(
        call["folder_path"] == str(frontend_dir) for call in fake_api.uploaded_folders
    )


def _make_static_deploy_env(tmp_path, monkeypatch):
    frontend_dir = tmp_path / "static-frontend"
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
    return fake_api, frontend_dir


def _get_uploaded_config(fake_api):
    config_upload = next(
        item
        for item in fake_api.uploaded_files
        if item["path_in_repo"] == "config.json"
    )
    return json.loads(config_upload["payload"])


def test_deploy_as_static_space_config_omits_hf_token(tmp_path, monkeypatch):
    fake_api, frontend_dir = _make_static_deploy_env(tmp_path, monkeypatch)

    deploy.deploy_as_static_space(
        "abidlabs/static-space",
        None,
        "demo-project",
        bucket_id="abidlabs/static-bucket",
        hf_token="hf_supersecrettoken",
        frontend_dir=frontend_dir,
    )

    config = _get_uploaded_config(fake_api)
    assert config["version"] == deploy.trackio.__version__
    assert "hf_token" not in config
    assert "token" not in config
    assert "hf_supersecrettoken" not in json.dumps(config)


def test_deploy_as_static_space_rejects_private_true(tmp_path, monkeypatch):
    _, frontend_dir = _make_static_deploy_env(tmp_path, monkeypatch)

    with pytest.raises(ValueError, match="private=True is not supported"):
        deploy.deploy_as_static_space(
            "abidlabs/static-space",
            None,
            "demo-project",
            bucket_id="abidlabs/static-bucket",
            private=True,
            frontend_dir=frontend_dir,
        )


@pytest.mark.parametrize("login_required", [False, True])
def test_deploy_as_space_uses_supported_create_repo_arguments(
    monkeypatch, login_required
):
    class CreatedSpace(Exception):
        pass

    errors = [CreatedSpace()]
    if login_required:
        errors.insert(
            0,
            deploy.HfHubHTTPError(
                "Unauthorized",
                response=hub_httpx.Response(
                    401, request=hub_httpx.Request("POST", "https://huggingface.co")
                ),
            ),
        )
    monkeypatch.setattr(deploy, "on_spaces", lambda: False)
    with (
        patch.object(deploy.huggingface_hub, "create_repo", autospec=True) as create,
        patch.object(deploy.huggingface_hub, "login") as login,
    ):
        create.side_effect = errors
        with pytest.raises(CreatedSpace):
            deploy.deploy_as_space("username/trackio")
        assert create.call_count == 1 + login_required
        for call in create.call_args_list:
            assert "space_storage" not in call.kwargs
        assert login.call_count == login_required


@pytest.mark.parametrize("hub_version", ["1.10.0", "2.2.0"])
def test_deploy_as_space_explicit_legacy_storage(monkeypatch, hub_version):
    monkeypatch.setattr(deploy, "on_spaces", lambda: False)
    monkeypatch.setattr(deploy.huggingface_hub, "__version__", hub_version)
    with patch.object(deploy.huggingface_hub, "create_repo") as create:
        if hub_version.startswith("2."):
            with pytest.raises(ValueError, match="Use bucket_id"):
                deploy.deploy_as_space("username/trackio", space_storage="small")
            create.assert_not_called()
        else:
            create.side_effect = RuntimeError("created")
            with pytest.raises(RuntimeError, match="created"):
                deploy.deploy_as_space("username/trackio", space_storage="small")
            assert create.call_args.kwargs["space_storage"] == "small"


@pytest.mark.parametrize(
    "wait", [deploy.wait_until_space_exists, deploy._wait_until_space_running]
)
def test_space_wait_retries_hub_transport_errors(monkeypatch, wait):
    monkeypatch.setattr(deploy.time, "sleep", lambda _: None)
    with patch.object(deploy.huggingface_hub, "HfApi") as api:
        api.return_value.space_info.side_effect = [
            hub_httpx.ConnectError("temporary connection failure"),
            SimpleNamespace(runtime=SimpleNamespace(stage="RUNNING")),
        ]
        wait("username/trackio")
        assert api.return_value.space_info.call_count == 2


def test_retry_hf_write_retries_hub_read_timeout(monkeypatch):
    from unittest.mock import Mock

    monkeypatch.setattr(deploy.time, "sleep", lambda _: None)
    write = Mock(side_effect=[hub_httpx.ReadTimeout("timeout"), "uploaded"])
    assert deploy._retry_hf_write("upload", write) == "uploaded"
    assert write.call_count == 2
