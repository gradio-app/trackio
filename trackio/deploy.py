import importlib.metadata
import io
import json as json_mod
import os
import re
import shutil
import sys
import tempfile
import threading
import time
from importlib.resources import files
from pathlib import Path
from typing import Literal

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

import gradio
import huggingface_hub
from gradio_client import Client, handle_file
from httpx import ReadTimeout
from huggingface_hub.errors import HfHubHTTPError, RepositoryNotFoundError

import trackio
from trackio.sqlite_storage import SQLiteStorage
from trackio.utils import (
    MEDIA_DIR,
    get_or_create_project_hash,
    preprocess_space_and_dataset_ids,
)

SPACE_HOST_URL = "https://{user_name}-{space_name}.hf.space/"
SPACE_URL = "https://huggingface.co/spaces/{space_id}"


def detect_space_sdk(space_id: str) -> str | None:
    hf_api = huggingface_hub.HfApi()
    try:
        info = hf_api.space_info(space_id)
        if info.sdk:
            s = info.sdk.lower()
            if s in ("gradio", "static"):
                return s
    except (RepositoryNotFoundError, HfHubHTTPError, ReadTimeout):
        pass
    try:
        readme_path = huggingface_hub.hf_hub_download(
            repo_id=space_id, filename="README.md", repo_type="space"
        )
        text = Path(readme_path).read_text(encoding="utf-8", errors="replace")
        m = re.search(r"(?m)^sdk:\s*(\S+)", text)
        if m:
            s = m.group(1).lower().strip().strip("'\"")
            if s in ("gradio", "static"):
                return s
    except Exception:
        pass
    cfg = fetch_space_config_json(space_id)
    if cfg and cfg.get("mode") == "static":
        return "static"
    return None


def fetch_space_config_json(space_id: str) -> dict | None:
    try:
        p = huggingface_hub.hf_hub_download(
            repo_id=space_id, filename="config.json", repo_type="space"
        )
        with open(p, encoding="utf-8") as f:
            return json_mod.load(f)
    except Exception:
        return None


def _safe_delete_space_path(
    hf_api: huggingface_hub.HfApi, space_id: str, path: str
) -> None:
    try:
        _retry_hf_write(
            f"Delete {path}",
            lambda: hf_api.delete_file(
                path_in_repo=path, repo_id=space_id, repo_type="space"
            ),
        )
    except HfHubHTTPError as e:
        if e.response is not None and e.response.status_code == 404:
            return
        raise
    except Exception:
        pass


def _safe_delete_space_folder(
    hf_api: huggingface_hub.HfApi, space_id: str, path: str
) -> None:
    try:
        _retry_hf_write(
            f"Delete folder {path}",
            lambda: hf_api.delete_folder(
                path_in_repo=path, repo_id=space_id, repo_type="space"
            ),
        )
    except HfHubHTTPError as e:
        if e.response is not None and e.response.status_code == 404:
            return
        raise
    except Exception:
        pass


def remove_gradio_files_from_space(space_id: str) -> None:
    hf_api = huggingface_hub.HfApi()
    _safe_delete_space_path(hf_api, space_id, "app.py")
    _safe_delete_space_path(hf_api, space_id, "requirements.txt")
    _safe_delete_space_folder(hf_api, space_id, "trackio")


def remove_static_files_from_space(space_id: str) -> None:
    hf_api = huggingface_hub.HfApi()
    _safe_delete_space_path(hf_api, space_id, "config.json")
    _safe_delete_space_path(hf_api, space_id, "index.html")
    for name in ("assets", "_app"):
        _safe_delete_space_folder(hf_api, space_id, name)


def _retry_hf_write(op_name: str, fn, retries: int = 4, initial_delay: float = 1.5):
    delay = initial_delay
    for attempt in range(1, retries + 1):
        try:
            return fn()
        except ReadTimeout:
            if attempt == retries:
                raise
            print(
                f"* {op_name} timed out (attempt {attempt}/{retries}). Retrying in {delay:.1f}s..."
            )
            time.sleep(delay)
            delay = min(delay * 2, 12)
        except HfHubHTTPError as e:
            status = e.response.status_code if e.response is not None else None
            if status is None or status < 500 or attempt == retries:
                raise
            print(
                f"* {op_name} failed with HTTP {status} (attempt {attempt}/{retries}). Retrying in {delay:.1f}s..."
            )
            time.sleep(delay)
            delay = min(delay * 2, 12)


def _get_source_install_dependencies() -> str:
    """Get trackio dependencies from pyproject.toml for source installs."""
    trackio_path = files("trackio")
    pyproject_path = Path(trackio_path).parent / "pyproject.toml"
    with open(pyproject_path, "rb") as f:
        pyproject = tomllib.load(f)
    deps = pyproject["project"]["dependencies"]
    spaces_deps = (
        pyproject["project"].get("optional-dependencies", {}).get("spaces", [])
    )
    return "\n".join(deps + spaces_deps)


def _is_trackio_installed_from_source() -> bool:
    """Check if trackio is installed from source/editable install vs PyPI."""
    try:
        trackio_file = trackio.__file__
        if "site-packages" not in trackio_file and "dist-packages" not in trackio_file:
            return True

        dist = importlib.metadata.distribution("trackio")
        if dist.files:
            files = list(dist.files)
            has_pth = any(".pth" in str(f) for f in files)
            if has_pth:
                return True

        return False
    except (
        AttributeError,
        importlib.metadata.PackageNotFoundError,
        importlib.metadata.MetadataError,
        ValueError,
        TypeError,
    ):
        return True


def deploy_as_space(
    space_id: str,
    space_storage: huggingface_hub.SpaceStorage | None = None,
    dataset_id: str | None = None,
    private: bool | None = None,
):
    if (
        os.getenv("SYSTEM") == "spaces"
    ):  # in case a repo with this function is uploaded to spaces
        return

    trackio_path = files("trackio")

    hf_api = huggingface_hub.HfApi()

    try:
        huggingface_hub.create_repo(
            space_id,
            private=private,
            space_sdk="gradio",
            space_storage=space_storage,
            repo_type="space",
            exist_ok=True,
        )
    except HfHubHTTPError as e:
        if e.response.status_code in [401, 403]:  # unauthorized or forbidden
            print("Need 'write' access token to create a Spaces repo.")
            huggingface_hub.login(add_to_git_credential=False)
            huggingface_hub.create_repo(
                space_id,
                private=private,
                space_sdk="gradio",
                space_storage=space_storage,
                repo_type="space",
                exist_ok=True,
            )
        else:
            raise ValueError(f"Failed to create Space: {e}")

    # We can assume pandas, gradio, and huggingface-hub are already installed in a Gradio Space.
    # Make sure necessary dependencies are installed by creating a requirements.txt.
    is_source_install = _is_trackio_installed_from_source()

    with open(Path(trackio_path, "README.md"), "r") as f:
        readme_content = f.read()
        readme_content = readme_content.replace("{GRADIO_VERSION}", gradio.__version__)
        readme_content = readme_content.replace("{APP_FILE}", "app.py")
        readme_buffer = io.BytesIO(readme_content.encode("utf-8"))
        hf_api.upload_file(
            path_or_fileobj=readme_buffer,
            path_in_repo="README.md",
            repo_id=space_id,
            repo_type="space",
        )

    if is_source_install:
        requirements_content = _get_source_install_dependencies()
    else:
        requirements_content = f"trackio[spaces]=={trackio.__version__}"

    requirements_buffer = io.BytesIO(requirements_content.encode("utf-8"))
    hf_api.upload_file(
        path_or_fileobj=requirements_buffer,
        path_in_repo="requirements.txt",
        repo_id=space_id,
        repo_type="space",
    )

    huggingface_hub.utils.disable_progress_bars()

    if is_source_install:
        dist_index = (
            Path(trackio.__file__).resolve().parent / "frontend" / "dist" / "index.html"
        )
        if not dist_index.is_file():
            raise ValueError(
                "The Trackio frontend build is missing. From the repository root run "
                "`cd trackio/frontend && npm ci && npm run build`, then deploy again."
            )
        hf_api.upload_folder(
            repo_id=space_id,
            repo_type="space",
            folder_path=trackio_path,
            path_in_repo="trackio",
            ignore_patterns=[
                "README.md",
                "frontend/node_modules/**",
                "frontend/src/**",
                "frontend/.gitignore",
                "frontend/package.json",
                "frontend/package-lock.json",
                "frontend/vite.config.js",
                "frontend/svelte.config.js",
                "**/__pycache__/**",
                "*.pyc",
            ],
        )

    app_file_content = """import trackio
trackio.show()"""
    app_file_buffer = io.BytesIO(app_file_content.encode("utf-8"))
    hf_api.upload_file(
        path_or_fileobj=app_file_buffer,
        path_in_repo="app.py",
        repo_id=space_id,
        repo_type="space",
    )

    if hf_token := huggingface_hub.utils.get_token():
        huggingface_hub.add_space_secret(space_id, "HF_TOKEN", hf_token)
    if dataset_id is not None:
        huggingface_hub.add_space_variable(space_id, "TRACKIO_DATASET_ID", dataset_id)
    if logo_light_url := os.environ.get("TRACKIO_LOGO_LIGHT_URL"):
        huggingface_hub.add_space_variable(
            space_id, "TRACKIO_LOGO_LIGHT_URL", logo_light_url
        )
    if logo_dark_url := os.environ.get("TRACKIO_LOGO_DARK_URL"):
        huggingface_hub.add_space_variable(
            space_id, "TRACKIO_LOGO_DARK_URL", logo_dark_url
        )
    if plot_order := os.environ.get("TRACKIO_PLOT_ORDER"):
        huggingface_hub.add_space_variable(space_id, "TRACKIO_PLOT_ORDER", plot_order)
    if theme := os.environ.get("TRACKIO_THEME"):
        huggingface_hub.add_space_variable(space_id, "TRACKIO_THEME", theme)
    huggingface_hub.add_space_variable(space_id, "GRADIO_MCP_SERVER", "True")


def create_space_if_not_exists(
    space_id: str,
    space_storage: huggingface_hub.SpaceStorage | None = None,
    dataset_id: str | None = None,
    private: bool | None = None,
) -> None:
    """
    Creates a new Hugging Face Space if it does not exist.

    Args:
        space_id (`str`):
            The ID of the Space to create.
        space_storage ([`~huggingface_hub.SpaceStorage`], *optional*):
            Choice of persistent storage tier for the Space.
        dataset_id (`str`, *optional*):
            The ID of the Dataset to add to the Space as a space variable.
        private (`bool`, *optional*):
            Whether to make the Space private. If `None` (default), the repo will be
            public unless the organization's default is private. This value is ignored
            if the repo already exists.
    """
    if "/" not in space_id:
        raise ValueError(
            f"Invalid space ID: {space_id}. Must be in the format: username/reponame or orgname/reponame."
        )
    if dataset_id is not None and "/" not in dataset_id:
        raise ValueError(
            f"Invalid dataset ID: {dataset_id}. Must be in the format: username/datasetname or orgname/datasetname."
        )
    try:
        huggingface_hub.repo_info(space_id, repo_type="space")
        print(f"* Found existing space: {SPACE_URL.format(space_id=space_id)}")
        return
    except RepositoryNotFoundError:
        pass
    except HfHubHTTPError as e:
        if e.response.status_code in [401, 403]:  # unauthorized or forbidden
            print("Need 'write' access token to create a Spaces repo.")
            huggingface_hub.login(add_to_git_credential=False)
        else:
            raise ValueError(f"Failed to create Space: {e}")

    print(f"* Creating new space: {SPACE_URL.format(space_id=space_id)}")
    deploy_as_space(space_id, space_storage, dataset_id, private)
    print("* Waiting for Space to be ready...")
    _wait_until_space_running(space_id)


def _wait_until_space_running(space_id: str, timeout: int = 300) -> None:
    hf_api = huggingface_hub.HfApi()
    start = time.time()
    delay = 2
    while time.time() - start < timeout:
        try:
            info = hf_api.space_info(space_id)
            if info.runtime and info.runtime.stage == "RUNNING":
                return
        except (huggingface_hub.utils.HfHubHTTPError, ReadTimeout):
            pass
        time.sleep(delay)
        delay = min(delay * 1.5, 15)


def wait_until_space_exists(
    space_id: str,
) -> None:
    """
    Blocks the current thread until the Space exists.

    Args:
        space_id (`str`):
            The ID of the Space to wait for.

    Raises:
        `TimeoutError`: If waiting for the Space takes longer than expected.
    """
    hf_api = huggingface_hub.HfApi()
    delay = 1
    for _ in range(30):
        try:
            hf_api.space_info(space_id)
            return
        except (huggingface_hub.utils.HfHubHTTPError, ReadTimeout):
            time.sleep(delay)
            delay = min(delay * 2, 60)
    raise TimeoutError("Waiting for space to exist took longer than expected")


def upload_db_to_space(
    project: str,
    space_id: str,
    force: bool = False,
    db_path: Path | None = None,
) -> None:
    """
    Uploads the database of a local Trackio project to a Hugging Face Space.

    This uses the Gradio Client to upload since we do not want to trigger a new build of
    the Space, which would happen if we used `huggingface_hub.upload_file`.

    Args:
        project (`str`):
            The name of the project to upload.
        space_id (`str`):
            The ID of the Space to upload to.
        force (`bool`, *optional*, defaults to `False`):
            If `True`, overwrites the existing database without prompting. If `False`,
            prompts for confirmation.
        db_path (`Path`, *optional*):
            If set, uploads this file instead of the default project database path.
    """
    db_path = db_path or SQLiteStorage.get_project_db_path(project)
    client = Client(space_id, verbose=False, httpx_kwargs={"timeout": 90})

    if not force:
        try:
            existing_projects = client.predict(api_name="/get_all_projects")
            if project in existing_projects:
                response = input(
                    f"Database for project '{project}' already exists on Space '{space_id}'. "
                    f"Overwrite it? (y/N): "
                )
                if response.lower() not in ["y", "yes"]:
                    print("* Upload cancelled.")
                    return
        except Exception as e:
            print(f"* Warning: Could not check if project exists on Space: {e}")
            print("* Proceeding with upload...")

    client.predict(
        api_name="/upload_db_to_space",
        project=project,
        uploaded_db=handle_file(str(db_path)),
        hf_token=huggingface_hub.utils.get_token(),
    )


def push_static_dataset_from_gradio_space(
    project: str, space_id: str, dataset_id: str
) -> None:
    print(
        f"* Pushing dataset export from Space to {dataset_id} (requires Trackio with push_static_dataset_from_space API on the Space)..."
    )
    client = Client(space_id, verbose=False, httpx_kwargs={"timeout": 180})
    hf_token = huggingface_hub.utils.get_token()
    client.predict(
        api_name="/push_static_dataset_from_space",
        project=project,
        dataset_id=dataset_id,
        hf_token=hf_token,
    )


def upload_media_tree_to_space(project: str, space_id: str, media_root: Path) -> None:
    if not media_root.is_dir():
        return
    uploads = []
    for run_dir in sorted(media_root.iterdir()):
        if not run_dir.is_dir():
            continue
        run_name = run_dir.name
        for step_dir in sorted(run_dir.iterdir()):
            if not step_dir.is_dir():
                continue
            try:
                step = int(step_dir.name)
            except ValueError:
                continue
            for fp in step_dir.rglob("*"):
                if fp.is_file():
                    rel = fp.relative_to(step_dir)
                    uploads.append(
                        {
                            "project": project,
                            "run": run_name,
                            "step": step,
                            "relative_path": str(rel),
                            "uploaded_file": handle_file(str(fp)),
                        }
                    )
    if not uploads:
        return
    client = Client(space_id, verbose=False, httpx_kwargs={"timeout": 120})
    hf_token = huggingface_hub.utils.get_token()
    batch_size = 40
    for i in range(0, len(uploads), batch_size):
        batch = uploads[i : i + batch_size]
        print(
            f"* Uploading media files: {min(i + batch_size, len(uploads))}/{len(uploads)}..."
        )
        client.predict(api_name="/bulk_upload_media", uploads=batch, hf_token=hf_token)


def _convert_gradio_space_to_static(
    project: str,
    space_id: str,
    dataset_id: str,
    private: bool | None,
) -> None:
    push_static_dataset_from_gradio_space(project, space_id, dataset_id)
    remove_gradio_files_from_space(space_id)
    hf_token = huggingface_hub.utils.get_token() if private else None
    deploy_as_static_space(
        space_id,
        dataset_id,
        project,
        private=private,
        hf_token=hf_token,
    )


def _convert_static_space_to_gradio(
    project: str,
    space_id: str,
    dataset_id: str,
    private: bool | None,
    force: bool,
) -> None:
    tmp_root = Path(tempfile.mkdtemp())
    try:
        tok = huggingface_hub.utils.get_token()
        huggingface_hub.snapshot_download(
            repo_id=dataset_id,
            repo_type="dataset",
            local_dir=str(tmp_root),
            token=tok,
        )
        tmp_db = tmp_root / SQLiteStorage.get_project_db_filename(project)
        SQLiteStorage.import_project_from_static_dataset_layout(
            tmp_root, project, tmp_db
        )
        remove_static_files_from_space(space_id)
        deploy_as_space(space_id, None, dataset_id, private)
        print("* Waiting for Space to rebuild as Gradio...")
        _wait_until_space_running(space_id)
        upload_db_to_space(project, space_id, force=force, db_path=tmp_db)
        media_root = tmp_root / "media"
        upload_media_tree_to_space(project, space_id, media_root)
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)


SYNC_BATCH_SIZE = 500


def sync_incremental(
    project: str,
    space_id: str,
    private: bool | None = None,
    pending_only: bool = False,
) -> None:
    """
    Syncs a local Trackio project to a Space via the bulk_log API endpoints
    instead of uploading the entire DB file. Supports incremental sync.

    Args:
        project: The name of the project to sync.
        space_id: The HF Space ID to sync to.
        private: Whether to make the Space private if creating.
        pending_only: If True, only sync rows tagged with space_id (pending data).
    """
    print(
        f"* Syncing project '{project}' to: {SPACE_URL.format(space_id=space_id)} (please wait...)"
    )
    create_space_if_not_exists(space_id, private=private)
    wait_until_space_exists(space_id)

    client = Client(space_id, verbose=False, httpx_kwargs={"timeout": 90})
    hf_token = huggingface_hub.utils.get_token()

    if pending_only:
        pending_logs = SQLiteStorage.get_pending_logs(project)
        if pending_logs:
            logs = pending_logs["logs"]
            for i in range(0, len(logs), SYNC_BATCH_SIZE):
                batch = logs[i : i + SYNC_BATCH_SIZE]
                print(
                    f"  Syncing metrics: {min(i + SYNC_BATCH_SIZE, len(logs))}/{len(logs)}..."
                )
                client.predict(api_name="/bulk_log", logs=batch, hf_token=hf_token)
            SQLiteStorage.clear_pending_logs(project, pending_logs["ids"])

        pending_sys = SQLiteStorage.get_pending_system_logs(project)
        if pending_sys:
            logs = pending_sys["logs"]
            for i in range(0, len(logs), SYNC_BATCH_SIZE):
                batch = logs[i : i + SYNC_BATCH_SIZE]
                print(
                    f"  Syncing system metrics: {min(i + SYNC_BATCH_SIZE, len(logs))}/{len(logs)}..."
                )
                client.predict(
                    api_name="/bulk_log_system", logs=batch, hf_token=hf_token
                )
            SQLiteStorage.clear_pending_system_logs(project, pending_sys["ids"])

        pending_uploads = SQLiteStorage.get_pending_uploads(project)
        if pending_uploads:
            upload_entries = []
            for u in pending_uploads["uploads"]:
                fp = u["file_path"]
                if os.path.exists(fp):
                    upload_entries.append(
                        {
                            "project": u["project"],
                            "run": u["run"],
                            "step": u["step"],
                            "relative_path": u["relative_path"],
                            "uploaded_file": handle_file(fp),
                        }
                    )
            if upload_entries:
                print(f"  Syncing {len(upload_entries)} media files...")
                client.predict(
                    api_name="/bulk_upload_media",
                    uploads=upload_entries,
                    hf_token=hf_token,
                )
            SQLiteStorage.clear_pending_uploads(project, pending_uploads["ids"])
    else:
        all_logs = SQLiteStorage.get_all_logs_for_sync(project)
        if all_logs:
            for i in range(0, len(all_logs), SYNC_BATCH_SIZE):
                batch = all_logs[i : i + SYNC_BATCH_SIZE]
                print(
                    f"  Syncing metrics: {min(i + SYNC_BATCH_SIZE, len(all_logs))}/{len(all_logs)}..."
                )
                client.predict(api_name="/bulk_log", logs=batch, hf_token=hf_token)

        all_sys_logs = SQLiteStorage.get_all_system_logs_for_sync(project)
        if all_sys_logs:
            for i in range(0, len(all_sys_logs), SYNC_BATCH_SIZE):
                batch = all_sys_logs[i : i + SYNC_BATCH_SIZE]
                print(
                    f"  Syncing system metrics: {min(i + SYNC_BATCH_SIZE, len(all_sys_logs))}/{len(all_sys_logs)}..."
                )
                client.predict(
                    api_name="/bulk_log_system", logs=batch, hf_token=hf_token
                )

    SQLiteStorage.set_project_metadata(project, "space_id", space_id)
    print(f"* Synced successfully to space: {SPACE_URL.format(space_id=space_id)}")


def upload_dataset_for_static(
    project: str,
    dataset_id: str,
    private: bool | None = None,
) -> None:
    hf_api = huggingface_hub.HfApi()

    try:
        huggingface_hub.create_repo(
            dataset_id,
            private=private,
            repo_type="dataset",
            exist_ok=True,
        )
    except HfHubHTTPError as e:
        if e.response.status_code in [401, 403]:
            print("Need 'write' access token to create a Dataset repo.")
            huggingface_hub.login(add_to_git_credential=False)
            huggingface_hub.create_repo(
                dataset_id,
                private=private,
                repo_type="dataset",
                exist_ok=True,
            )
        else:
            raise ValueError(f"Failed to create Dataset: {e}")

    with tempfile.TemporaryDirectory() as tmp_dir:
        output_dir = Path(tmp_dir)
        SQLiteStorage.export_for_static_space(project, output_dir)

        media_dir = MEDIA_DIR / project
        if media_dir.exists():
            dest = output_dir / "media"
            shutil.copytree(media_dir, dest)

        _retry_hf_write(
            "Dataset upload",
            lambda: hf_api.upload_folder(
                repo_id=dataset_id,
                repo_type="dataset",
                folder_path=str(output_dir),
            ),
        )

    print(f"* Dataset uploaded: https://huggingface.co/datasets/{dataset_id}")


def deploy_as_static_space(
    space_id: str,
    dataset_id: str,
    project: str,
    private: bool | None = None,
    hf_token: str | None = None,
) -> None:
    if os.getenv("SYSTEM") == "spaces":
        return

    hf_api = huggingface_hub.HfApi()

    try:
        huggingface_hub.create_repo(
            space_id,
            private=private,
            space_sdk="static",
            repo_type="space",
            exist_ok=True,
        )
    except HfHubHTTPError as e:
        if e.response.status_code in [401, 403]:
            print("Need 'write' access token to create a Spaces repo.")
            huggingface_hub.login(add_to_git_credential=False)
            huggingface_hub.create_repo(
                space_id,
                private=private,
                space_sdk="static",
                repo_type="space",
                exist_ok=True,
            )
        else:
            raise ValueError(f"Failed to create Space: {e}")

    readme_content = "---\nsdk: static\npinned: false\ntags:\n - trackio\n---\n"
    _retry_hf_write(
        "Static Space README upload",
        lambda: hf_api.upload_file(
            path_or_fileobj=io.BytesIO(readme_content.encode("utf-8")),
            path_in_repo="README.md",
            repo_id=space_id,
            repo_type="space",
        ),
    )

    trackio_path = files("trackio")
    dist_dir = Path(trackio_path).parent / "trackio" / "frontend" / "dist"
    if not dist_dir.is_dir():
        dist_dir = Path(trackio.__file__).resolve().parent / "frontend" / "dist"
    if not dist_dir.is_dir():
        raise ValueError(
            "The Trackio frontend build is missing. From the repository root run "
            "`cd trackio/frontend && npm ci && npm run build`, then deploy again."
        )

    _retry_hf_write(
        "Static Space frontend upload",
        lambda: hf_api.upload_folder(
            repo_id=space_id,
            repo_type="space",
            folder_path=str(dist_dir),
        ),
    )

    config = {
        "mode": "static",
        "dataset_id": dataset_id,
        "project": project,
        "private": bool(private),
    }
    if hf_token and private:
        config["hf_token"] = hf_token

    _retry_hf_write(
        "Static Space config upload",
        lambda: hf_api.upload_file(
            path_or_fileobj=io.BytesIO(json_mod.dumps(config).encode("utf-8")),
            path_in_repo="config.json",
            repo_id=space_id,
            repo_type="space",
        ),
    )

    assets_dir = Path(trackio.__file__).resolve().parent / "assets"
    if assets_dir.is_dir():
        _retry_hf_write(
            "Static Space assets upload",
            lambda: hf_api.upload_folder(
                repo_id=space_id,
                repo_type="space",
                folder_path=str(assets_dir),
                path_in_repo="assets",
            ),
        )

    print(f"* Static Space deployed: {SPACE_URL.format(space_id=space_id)}")


def sync(
    project: str,
    space_id: str | None = None,
    private: bool | None = None,
    force: bool = False,
    run_in_background: bool = False,
    sdk: str = "gradio",
    dataset_id: str | None = None,
    space_mode: Literal["auto", "gradio", "static"] = "auto",
) -> str:
    """
    Syncs a local Trackio project's database to a Hugging Face Space.
    If the Space does not exist, it will be created.

    Args:
        project (`str`): The name of the project to upload.
        space_id (`str`, *optional*): The ID of the Space to upload to (e.g., `"username/space_id"`).
            If not provided, checks project metadata first, then generates a random space_id.
        private (`bool`, *optional*):
            Whether to make the Space private. If None (default), the repo will be
            public unless the organization's default is private. This value is ignored
            if the repo already exists.
        force (`bool`, *optional*, defaults to `False`):
            If `True`, overwrite the existing database without prompting for confirmation.
            If `False`, prompt the user before overwriting an existing database.
        run_in_background (`bool`, *optional*, defaults to `False`):
            If `True`, the Space creation and database upload will be run in a background thread.
            If `False`, all the steps will be run synchronously.
        sdk (`str`, *optional*, defaults to `"gradio"`):
            The type of Space to deploy. `"gradio"` deploys a Gradio Space with a live
            server. `"static"` deploys a static Space that reads from an HF Dataset
            (no server needed).
        dataset_id (`str`, *optional*):
            The ID of the HF Dataset for static mode. Auto-generated from space_id if not provided.
        space_mode (`str`, *optional*, defaults to `"auto"`):
            How to determine the Space's current SDK when deciding whether to convert.
            `"auto"` uses the Hub (`space_info`, README, or `config.json`). Use `"gradio"`
            or `"static"` only if auto-detection fails.
    Returns:
        `str`: The Space ID of the synced project.
    """
    if sdk not in ("gradio", "static"):
        raise ValueError(f"sdk must be 'gradio' or 'static', got '{sdk}'")
    if space_id is None:
        space_id = SQLiteStorage.get_space_id(project)
    if space_id is None:
        space_id = f"{project}-{get_or_create_project_hash(project)}"
    space_id, dataset_id = preprocess_space_and_dataset_ids(space_id, dataset_id)

    def _do_sync():
        repo_exists = False
        try:
            huggingface_hub.repo_info(space_id, repo_type="space")
            repo_exists = True
        except RepositoryNotFoundError:
            pass
        except HfHubHTTPError:
            repo_exists = True

        if space_mode == "auto":
            current = detect_space_sdk(space_id) if repo_exists else None
        elif space_mode == "gradio":
            current = "gradio"
        else:
            current = "static"

        if repo_exists and current is None:
            raise ValueError(
                "Could not detect this Space's SDK. Pass space_mode='gradio' or space_mode='static'."
            )
        if current is not None and current not in ("gradio", "static"):
            raise ValueError(
                f"Unsupported Space SDK for conversion: {current}. Only gradio and static are supported."
            )

        if not repo_exists:
            if sdk == "static":
                upload_dataset_for_static(project, dataset_id, private=private)
                hf_tok = huggingface_hub.utils.get_token() if private else None
                deploy_as_static_space(
                    space_id,
                    dataset_id,
                    project,
                    private=private,
                    hf_token=hf_tok,
                )
            else:
                sync_incremental(project, space_id, private=private, pending_only=False)
            SQLiteStorage.set_project_metadata(project, "space_id", space_id)
            return

        if current == sdk:
            if sdk == "static":
                upload_dataset_for_static(project, dataset_id, private=private)
                hf_tok = huggingface_hub.utils.get_token() if private else None
                deploy_as_static_space(
                    space_id,
                    dataset_id,
                    project,
                    private=private,
                    hf_token=hf_tok,
                )
            else:
                sync_incremental(project, space_id, private=private, pending_only=False)
            SQLiteStorage.set_project_metadata(project, "space_id", space_id)
            return

        if current == "gradio" and sdk == "static":
            _convert_gradio_space_to_static(project, space_id, dataset_id, private)
            SQLiteStorage.set_project_metadata(project, "space_id", space_id)
            return

        if current == "static" and sdk == "gradio":
            cfg = fetch_space_config_json(space_id)
            resolved_dataset_id = dataset_id
            if cfg and cfg.get("dataset_id"):
                resolved_dataset_id = cfg["dataset_id"]
            if not resolved_dataset_id:
                raise ValueError(
                    "dataset_id is required to convert a static Space to Gradio "
                    "(no dataset_id in Space config.json)."
                )
            _convert_static_space_to_gradio(
                project, space_id, resolved_dataset_id, private, force
            )
            SQLiteStorage.set_project_metadata(project, "space_id", space_id)
            return

        raise ValueError(f"Unsupported conversion from {current!r} to {sdk!r}")

    if run_in_background:
        threading.Thread(target=_do_sync).start()
    else:
        _do_sync()
    return space_id
