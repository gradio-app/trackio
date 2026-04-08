import importlib.metadata
import io
import json as json_mod
import os
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
import httpx
import huggingface_hub
from gradio_client import Client, handle_file
from httpx import ReadTimeout
from huggingface_hub import Volume
from huggingface_hub.errors import HfHubHTTPError, RepositoryNotFoundError

import trackio
from trackio.bucket_storage import (
    create_bucket_if_not_exists,
    upload_project_to_bucket,
    upload_project_to_bucket_for_static,
)
from trackio.sqlite_storage import SQLiteStorage
from trackio.utils import (
    MEDIA_DIR,
    get_or_create_project_hash,
    preprocess_space_and_dataset_ids,
)

SPACE_HOST_URL = "https://{user_name}-{space_name}.hf.space/"
SPACE_URL = "https://huggingface.co/spaces/{space_id}"
_BOLD_ORANGE = "\033[1m\033[38;5;208m"
_RESET = "\033[0m"


def raise_if_space_is_frozen_for_logging(space_id: str) -> None:
    try:
        info = huggingface_hub.HfApi().space_info(space_id)
    except RepositoryNotFoundError:
        return
    if getattr(info, "sdk", None) == "static":
        raise RuntimeError(
            f"Cannot log to Hugging Face Space '{space_id}' because it has been frozen "
            f"(it uses the static SDK: a read-only dashboard with no live Trackio server).\n\n"
            f"Use a different space_id for training, or create a new Gradio Trackio Space. "
            f"Freezing converts a live Gradio Space to static after a run; a frozen Space "
            f'cannot accept new logs. See trackio.sync(..., sdk="static") in the Trackio docs.'
        )


def _readme_linked_hub_yaml(dataset_id: str | None) -> str:
    if dataset_id is not None:
        return f"datasets:\n - {dataset_id}\n"
    return ""


_SPACE_APP_PY = "import trackio\ntrackio.show()\n"


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
    bucket_id: str | None = None,
    private: bool | None = None,
):
    if (
        os.getenv("SYSTEM") == "spaces"
    ):  # in case a repo with this function is uploaded to spaces
        return

    if dataset_id is not None and bucket_id is not None:
        raise ValueError(
            "Cannot use bucket volume options together with dataset_id; use one persistence mode."
        )

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

    if bucket_id is not None:
        create_bucket_if_not_exists(bucket_id, private=private)

    with open(Path(trackio_path, "README.md"), "r") as f:
        readme_content = f.read()
        readme_content = readme_content.replace("{GRADIO_VERSION}", gradio.__version__)
        readme_content = readme_content.replace("{APP_FILE}", "app.py")
        readme_content = readme_content.replace(
            "{LINKED_HUB_METADATA}", _readme_linked_hub_yaml(dataset_id)
        )
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

    app_file_content = _SPACE_APP_PY
    app_file_buffer = io.BytesIO(app_file_content.encode("utf-8"))
    hf_api.upload_file(
        path_or_fileobj=app_file_buffer,
        path_in_repo="app.py",
        repo_id=space_id,
        repo_type="space",
    )

    if hf_token := huggingface_hub.utils.get_token():
        huggingface_hub.add_space_secret(space_id, "HF_TOKEN", hf_token)
    if bucket_id is not None:
        runtime = hf_api.get_space_runtime(space_id)
        existing = list(runtime.volumes) if runtime.volumes else []
        already_mounted = any(
            v.type == "bucket" and v.source == bucket_id and v.mount_path == "/data"
            for v in existing
        )
        if not already_mounted:
            non_bucket = [
                v
                for v in existing
                if not (v.type == "bucket" and v.source == bucket_id)
            ]
            hf_api.set_space_volumes(
                space_id,
                non_bucket
                + [Volume(type="bucket", source=bucket_id, mount_path="/data")],
            )
            print(f"* Attached bucket {bucket_id} at '/data'")
        huggingface_hub.add_space_variable(space_id, "TRACKIO_DIR", "/data/trackio")
    elif dataset_id is not None:
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
    bucket_id: str | None = None,
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
            Deprecated. Use `bucket_id` instead.
        bucket_id (`str`, *optional*):
            Full Hub bucket id (`namespace/name`) to attach via the Hub volumes API (platform mount).
            Sets `TRACKIO_DIR` to the mount path.
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
    if bucket_id is not None and "/" not in bucket_id:
        raise ValueError(
            f"Invalid bucket ID: {bucket_id}. Must be in the format: username/bucketname or orgname/bucketname."
        )
    try:
        huggingface_hub.repo_info(space_id, repo_type="space")
        print(
            f"* Found existing space: {_BOLD_ORANGE}{SPACE_URL.format(space_id=space_id)}{_RESET}"
        )
        return
    except RepositoryNotFoundError:
        pass
    except HfHubHTTPError as e:
        if e.response.status_code in [401, 403]:  # unauthorized or forbidden
            print("Need 'write' access token to create a Spaces repo.")
            huggingface_hub.login(add_to_git_credential=False)
        else:
            raise ValueError(f"Failed to create Space: {e}")

    print(
        f"* Creating new space: {_BOLD_ORANGE}{SPACE_URL.format(space_id=space_id)}{_RESET}"
    )
    deploy_as_space(
        space_id,
        space_storage,
        dataset_id,
        bucket_id,
        private,
    )
    print("* Waiting for Space to be ready...")
    _wait_until_space_running(space_id)


def _wait_until_space_running(space_id: str, timeout: int = 300) -> None:
    hf_api = huggingface_hub.HfApi()
    start = time.time()
    delay = 2
    request_timeout = 45.0
    failure_stages = frozenset(
        ("NO_APP_FILE", "CONFIG_ERROR", "BUILD_ERROR", "RUNTIME_ERROR")
    )
    while time.time() - start < timeout:
        try:
            info = hf_api.space_info(space_id, timeout=request_timeout)
            if info.runtime:
                stage = str(info.runtime.stage)
                if stage in failure_stages:
                    raise RuntimeError(
                        f"Space {space_id} entered terminal stage {stage}. "
                        "Fix README.md or app files; see build logs on the Hub."
                    )
                if stage == "RUNNING":
                    return
        except RuntimeError:
            raise
        except (huggingface_hub.utils.HfHubHTTPError, httpx.RequestError):
            pass
        time.sleep(delay)
        delay = min(delay * 1.5, 15)
    raise TimeoutError(
        f"Space {space_id} did not reach RUNNING within {timeout}s. "
        "Check status and build logs on the Hub."
    )


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
        except (huggingface_hub.utils.HfHubHTTPError, httpx.RequestError):
            time.sleep(delay)
            delay = min(delay * 2, 60)
    raise TimeoutError("Waiting for space to exist took longer than expected")


def upload_db_to_space(project: str, space_id: str, force: bool = False) -> None:
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
    """
    db_path = SQLiteStorage.get_project_db_path(project)
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
        uploaded_db=handle_file(db_path),
        hf_token=huggingface_hub.utils.get_token(),
    )


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
    print(
        f"* Synced successfully to space: {_BOLD_ORANGE}{SPACE_URL.format(space_id=space_id)}{_RESET}"
    )


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
    dataset_id: str | None,
    project: str,
    bucket_id: str | None = None,
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

    linked = _readme_linked_hub_yaml(dataset_id)
    readme_content = (
        f"---\nsdk: static\npinned: false\ntags:\n - trackio\n{linked}---\n"
    )
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
        "project": project,
        "private": bool(private),
    }
    if bucket_id is not None:
        config["bucket_id"] = bucket_id
    if dataset_id is not None:
        config["dataset_id"] = dataset_id
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

    print(
        f"* Static Space deployed: {_BOLD_ORANGE}{SPACE_URL.format(space_id=space_id)}{_RESET}"
    )


def sync(
    project: str,
    space_id: str | None = None,
    private: bool | None = None,
    force: bool = False,
    run_in_background: bool = False,
    sdk: Literal["gradio", "static"] = "gradio",
    dataset_id: str | None = None,
    bucket_id: str | None = None,
) -> str:
    """
    Syncs a local Trackio project's database to a Hugging Face Space.
    If the Space does not exist, it will be created.

    **Freezing:** Passing ``sdk="static"`` *freezes* the Space: it converts a live Gradio
    Space into a static Space backed by an HF Bucket (read-only dashboard, no Gradio
    server). You cannot log new metrics to a frozen Space; use a different ``space_id``
    or a new Gradio Space for further training runs.

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
            server. `"static"` freezes the Space: deploys a static Space that reads from an HF Bucket
            (no server needed).
        dataset_id (`str`, *optional*):
            Deprecated. Use `bucket_id` instead.
        bucket_id (`str`, *optional*):
            The ID of the HF Bucket to sync to. By default, a bucket is auto-generated
            from the space_id.
    Returns:
        `str`: The Space ID of the synced project.
    """
    if sdk not in ("gradio", "static"):
        raise ValueError(f"sdk must be 'gradio' or 'static', got '{sdk}'")
    if space_id is None:
        space_id = SQLiteStorage.get_space_id(project)
    if space_id is None:
        space_id = f"{project}-{get_or_create_project_hash(project)}"
    space_id, dataset_id, bucket_id = preprocess_space_and_dataset_ids(
        space_id, dataset_id, bucket_id
    )

    def _do_sync():
        if sdk == "static":
            try:
                info = huggingface_hub.HfApi().space_info(space_id)
                if info.sdk == "gradio":
                    if not force:
                        answer = input(
                            f"Space '{space_id}' is currently a Gradio Space. "
                            f"Convert to static? [y/N] "
                        )
                        if answer.lower() not in ("y", "yes"):
                            print("Aborted.")
                            return
            except RepositoryNotFoundError:
                pass

            if dataset_id is not None:
                upload_dataset_for_static(project, dataset_id, private=private)
                hf_token = huggingface_hub.utils.get_token() if private else None
                deploy_as_static_space(
                    space_id,
                    dataset_id,
                    project,
                    private=private,
                    hf_token=hf_token,
                )
            elif bucket_id is not None:
                create_bucket_if_not_exists(bucket_id, private=private)
                upload_project_to_bucket_for_static(project, bucket_id)
                print(
                    f"* Project data uploaded to bucket: https://huggingface.co/buckets/{bucket_id}"
                )
                deploy_as_static_space(
                    space_id,
                    None,
                    project,
                    bucket_id=bucket_id,
                    private=private,
                    hf_token=huggingface_hub.utils.get_token() if private else None,
                )
        else:
            if bucket_id is not None:
                create_bucket_if_not_exists(bucket_id, private=private)
                upload_project_to_bucket(project, bucket_id)
                print(
                    f"* Project data uploaded to bucket: https://huggingface.co/buckets/{bucket_id}"
                )
                create_space_if_not_exists(
                    space_id, bucket_id=bucket_id, private=private
                )
            else:
                sync_incremental(project, space_id, private=private, pending_only=False)
        SQLiteStorage.set_project_metadata(project, "space_id", space_id)

    if run_in_background:
        threading.Thread(target=_do_sync).start()
    else:
        _do_sync()
    return space_id
