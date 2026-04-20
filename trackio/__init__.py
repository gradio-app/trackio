import atexit
import glob
import json
import logging
import os
import shutil
import warnings
import webbrowser
from pathlib import Path
from typing import Any

import huggingface_hub
from gradio_client import handle_file
from huggingface_hub import SpaceStorage
from huggingface_hub.errors import LocalTokenNotFoundError

from trackio import context_vars, deploy, utils
from trackio.alerts import AlertLevel
from trackio.api import Api
from trackio.apple_gpu import apple_gpu_available
from trackio.apple_gpu import log_apple_gpu as _log_apple_gpu
from trackio.deploy import freeze, sync
from trackio.gpu import gpu_available
from trackio.gpu import log_gpu as _log_nvidia_gpu
from trackio.histogram import Histogram
from trackio.imports import import_csv, import_tf_events
from trackio.launch import launch_trackio_dashboard
from trackio.markdown import Markdown
from trackio.media import (
    TrackioAudio,
    TrackioImage,
    TrackioVideo,
    get_project_media_path,
)
from trackio.remote_client import RemoteClient
from trackio.run import Run
from trackio.server import TrackioDashboardApp, build_starlette_app_only
from trackio.sqlite_storage import SQLiteStorage
from trackio.table import Table
from trackio.typehints import UploadEntry
from trackio.utils import TRACKIO_DIR, TRACKIO_LOGO_DIR, _emit_nonfatal_warning
from trackio.watchers import MetricWatcher, WatcherManager

logging.getLogger("httpx").setLevel(logging.WARNING)

__version__ = json.loads(Path(__file__).parent.joinpath("package.json").read_text())[
    "version"
]


class _TupleNoPrint(tuple):
    def __repr__(self) -> str:
        return ""


__all__ = [
    "init",
    "log",
    "log_system",
    "log_gpu",
    "finish",
    "alert",
    "watch",
    "should_stop",
    "AlertLevel",
    "show",
    "sync",
    "freeze",
    "delete_project",
    "import_csv",
    "import_tf_events",
    "save",
    "Image",
    "Video",
    "Audio",
    "Table",
    "Histogram",
    "Markdown",
    "Api",
    "TRACKIO_LOGO_DIR",
]

Audio = TrackioAudio
Image = TrackioImage
Video = TrackioVideo


config = {}

_atexit_registered = False
_projects_notified_auto_log_hw: set[str] = set()


def _cleanup_current_run():
    run = context_vars.current_run.get()
    if run is not None:
        try:
            if not run._finished:
                SQLiteStorage.set_run_status(run.project, run.name, "failed")
            run.finish()
        except Exception:
            pass


def _safe_get_runs_for_init(
    project: str,
    space_id: str | None,
    server_base_url: str | None,
    write_token: str | None,
    resume: str,
    remote_client: RemoteClient | None = None,
    check_existing_for_never: bool = False,
) -> list[str]:
    if space_id is not None:
        if resume == "never" and not check_existing_for_never:
            return []
        try:
            client = remote_client or RemoteClient(
                space_id,
                hf_token=huggingface_hub.utils.get_token(),
                verbose=False,
            )
            runs = client.predict(project=project, api_name="/get_runs_for_project")
            return runs if isinstance(runs, list) else []
        except Exception as e:
            _emit_nonfatal_warning(
                f"trackio.init() could not inspect existing runs for project '{project}' on Space '{space_id}': {e}. Continuing without resume metadata."
            )
            return []
    if server_base_url is not None:
        if resume == "never" and not check_existing_for_never:
            return []
        try:
            client = remote_client or RemoteClient(
                server_base_url,
                hf_token=None,
                write_token=write_token,
                verbose=False,
            )
            runs = client.predict(project=project, api_name="/get_runs_for_project")
            return runs if isinstance(runs, list) else []
        except Exception as e:
            _emit_nonfatal_warning(
                f"trackio.init() could not inspect existing runs for project '{project}' on self-hosted server '{server_base_url}': {e}. Continuing without resume metadata."
            )
            return []
    try:
        return SQLiteStorage.get_runs(project)
    except Exception as e:
        _emit_nonfatal_warning(
            f"trackio.init() could not inspect existing runs for project '{project}': {e}. Continuing without resume metadata."
        )
        return []


def _safe_get_latest_run_for_init(
    project: str,
    name: str,
    space_id: str | None = None,
    server_base_url: str | None = None,
    write_token: str | None = None,
    remote_client: RemoteClient | None = None,
) -> dict | None:
    if space_id is not None:
        try:
            client = remote_client or RemoteClient(
                space_id,
                hf_token=huggingface_hub.utils.get_token(),
                verbose=False,
            )
            runs = client.predict(project=project, api_name="/get_runs_for_project")
            if not isinstance(runs, list):
                return None
            matches = [r for r in runs if isinstance(r, dict) and r.get("name") == name]
            if not matches:
                return None
            matches.sort(key=lambda r: r.get("created_at") or "", reverse=True)
            return matches[0]
        except Exception as e:
            _emit_nonfatal_warning(
                f"trackio.init() could not inspect existing runs for project '{project}' on Space '{space_id}': {e}. Continuing without resume metadata."
            )
            return None
    if server_base_url is not None:
        try:
            client = remote_client or RemoteClient(
                server_base_url,
                hf_token=None,
                write_token=write_token,
                verbose=False,
            )
            runs = client.predict(project=project, api_name="/get_runs_for_project")
            if not isinstance(runs, list):
                return None
            matches = [r for r in runs if isinstance(r, dict) and r.get("name") == name]
            if not matches:
                return None
            matches.sort(key=lambda r: r.get("created_at") or "", reverse=True)
            return matches[0]
        except Exception as e:
            _emit_nonfatal_warning(
                f"trackio.init() could not inspect existing runs for project '{project}' on self-hosted server '{server_base_url}': {e}. Continuing without resume metadata."
            )
            return None
    try:
        return SQLiteStorage.get_latest_run_record_by_name(project, name)
    except Exception as e:
        _emit_nonfatal_warning(
            f"trackio.init() could not inspect existing runs for project '{project}': {e}. Continuing without resume metadata."
        )
        return None


def _safe_get_last_step_for_init(
    project: str,
    run_name: str,
    space_id: str | None,
    server_base_url: str | None,
    write_token: str | None,
    resumed: bool,
    run_id: str | None = None,
    remote_client: RemoteClient | None = None,
) -> int | None:
    if not resumed:
        return None
    if space_id is not None:
        try:
            client = remote_client or RemoteClient(
                space_id,
                hf_token=huggingface_hub.utils.get_token(),
                verbose=False,
            )
            summary_kwargs: dict[str, Any] = {
                "project": project,
                "api_name": "/get_run_summary",
            }
            if run_id is not None:
                summary_kwargs["run_id"] = run_id
            else:
                summary_kwargs["run"] = run_name
            summary = client.predict(**summary_kwargs)
            if isinstance(summary, dict):
                last_step = summary.get("last_step")
                return last_step if isinstance(last_step, int) else None
            return None
        except Exception as e:
            _emit_nonfatal_warning(
                f"trackio.init() could not recover the previous step for run '{run_name}' on Space '{space_id}': {e}. Continuing from step 0."
            )
            return None
    if server_base_url is not None:
        try:
            client = remote_client or RemoteClient(
                server_base_url,
                hf_token=None,
                write_token=write_token,
                verbose=False,
            )
            summary_kwargs = {
                "project": project,
                "api_name": "/get_run_summary",
            }
            if run_id is not None:
                summary_kwargs["run_id"] = run_id
            else:
                summary_kwargs["run"] = run_name
            summary = client.predict(**summary_kwargs)
            if isinstance(summary, dict):
                last_step = summary.get("last_step")
                return last_step if isinstance(last_step, int) else None
            return None
        except Exception as e:
            _emit_nonfatal_warning(
                f"trackio.init() could not recover the previous step for run '{run_name}' on self-hosted server '{server_base_url}': {e}. Continuing from step 0."
            )
            return None
    try:
        return SQLiteStorage.get_max_step_for_run(project, run_name, run_id=run_id)
    except Exception as e:
        _emit_nonfatal_warning(
            f"trackio.init() could not recover the previous step for run '{run_name}': {e}. Continuing from step 0."
        )
        return None


def init(
    project: str,
    name: str | None = None,
    group: str | None = None,
    space_id: str | None = None,
    server_url: str | None = None,
    space_storage: SpaceStorage | None = None,
    dataset_id: str | None = None,
    bucket_id: str | None = None,
    config: dict | None = None,
    resume: str = "never",
    settings: Any = None,
    private: bool | None = None,
    embed: bool = True,
    auto_log_gpu: bool | None = None,
    gpu_log_interval: float = 10.0,
    webhook_url: str | None = None,
    webhook_min_level: AlertLevel | str | None = None,
) -> Run:
    """
    Creates a new Trackio project and returns a [`Run`] object.

    Args:
        project (`str`):
            The name of the project (can be an existing project to continue tracking or
            a new project to start tracking from scratch).
        name (`str`, *optional*):
            The name of the run (if not provided, a default name will be generated).
        group (`str`, *optional*):
            The name of the group which this run belongs to in order to help organize
            related runs together. You can toggle the entire group's visibilitiy in the
            dashboard.
        space_id (`str`, *optional*):
            If provided, the project will be logged to a Hugging Face Space instead of
            a local directory. Should be a complete Space name like
            `"username/reponame"` or `"orgname/reponame"`, or just `"reponame"` in which
            case the Space will be created in the currently-logged-in Hugging Face
            user's namespace. If the Space does not exist, it will be created. If the
            Space already exists, the project will be logged to it. Can also be set
            via the `TRACKIO_SPACE_ID` environment variable. You cannot log to a
            Space that has been **frozen** (converted to the static SDK); use
            ``trackio.sync(..., sdk="static")`` only after you are done logging.
            Takes precedence over `server_url` and `TRACKIO_SERVER_URL` when more than
            one is set.
        server_url (`str`, *optional*):
            Base URL of a self-hosted Trackio server (``http://`` or ``https://``), or the
            write-access URL from ``trackio.show()`` which may include a ``write_token`` query
            parameter. The client sends that token on each request (``X-Trackio-Write-Token``);
            you can also set ``TRACKIO_WRITE_TOKEN`` instead of embedding the token in the URL.
            When set, metrics are sent to that server over HTTP instead of creating or syncing
            to a Hugging Face Space. Can also be set via the ``TRACKIO_SERVER_URL`` environment
            variable. Ignored when ``space_id`` or ``TRACKIO_SPACE_ID`` is set.
        space_storage ([`~huggingface_hub.SpaceStorage`], *optional*):
            Choice of persistent storage tier.
        dataset_id (`str`, *optional*):
            Deprecated. Use `bucket_id` instead.
        bucket_id (`str`, *optional*):
            The ID of the Hugging Face Bucket to use for metric persistence. By default,
            when a `space_id` is provided and `bucket_id` is not explicitly set, a
            bucket is auto-generated from the space_id. Buckets provide
            S3-like storage without git overhead - the SQLite database is stored directly
            via `hf-mount` in the Space. Specify a Bucket with name like
            `"username/bucketname"` or just `"bucketname"`.
        config (`dict`, *optional*):
            A dictionary of configuration options. Provided for compatibility with
            `wandb.init()`.
        resume (`str`, *optional*, defaults to `"never"`):
            Controls how to handle resuming a run. Can be one of:

            - `"must"`: Must resume the run with the given name, raises error if run
              doesn't exist
            - `"allow"`: Resume the run if it exists, otherwise create a new run
            - `"never"`: Never resume a run, always create a new one
        private (`bool`, *optional*):
            Whether to make the Space private. If None (default), the repo will be
            public unless the organization's default is private. This value is ignored
            if the repo already exists.
        settings (`Any`, *optional*):
            Not used. Provided for compatibility with `wandb.init()`.
        embed (`bool`, *optional*, defaults to `True`):
            If running inside a Jupyter/Colab notebook, whether the dashboard should
            automatically be embedded in the cell when trackio.init() is called. For
            local runs, this launches a local Trackio dashboard and embeds it. For Space runs,
            this embeds the Space URL. In Colab, the local dashboard will be accessible
            via a public share URL when `share=True`.
        auto_log_gpu (`bool` or `None`, *optional*, defaults to `None`):
            Controls automatic GPU metrics logging. If `None` (default), GPU logging
            is automatically enabled when `nvidia-ml-py` is installed and an NVIDIA
            GPU or Apple M series is detected. Set to `True` to force enable or
            `False` to disable.
        gpu_log_interval (`float`, *optional*, defaults to `10.0`):
            The interval in seconds between automatic GPU metric logs.
            Only used when `auto_log_gpu=True`.
        webhook_url (`str`, *optional*):
            A webhook URL to POST alert payloads to when `trackio.alert()` is
            called. Supports Slack and Discord webhook URLs natively (payloads
            are formatted automatically). Can also be set via the
            `TRACKIO_WEBHOOK_URL` environment variable. Individual alerts can
            override this URL by passing `webhook_url` to `trackio.alert()`.
        webhook_min_level (`AlertLevel` or `str`, *optional*):
            Minimum alert level that should trigger webhook delivery.
            For example, `AlertLevel.WARN` sends only `WARN` and `ERROR`
            alerts to the webhook destination. Can also be set via
            `TRACKIO_WEBHOOK_MIN_LEVEL`.
    Returns:
        `Run`: A [`Run`] object that can be used to log metrics and finish the run.
    """
    if settings is not None:
        _emit_nonfatal_warning(
            "* Warning: settings is not used. Provided for compatibility with wandb.init(). Please create an issue at: https://github.com/gradio-app/trackio/issues if you need a specific feature implemented."
        )

    previous_run = context_vars.current_run.get()
    if previous_run is not None:
        try:
            previous_run.finish()
        except Exception as e:
            _emit_nonfatal_warning(
                f"trackio.init() could not finish the previous run '{previous_run.name}': {e}. Continuing with new run."
            )
        context_vars.current_run.set(None)

    bucket_id_was_explicit = bucket_id is not None
    space_id, server_url = utils.resolve_space_id_and_server_url(space_id, server_url)
    if bucket_id is None and utils.on_spaces():
        bucket_id = os.environ.get("TRACKIO_BUCKET_ID")
    if server_url is not None and not server_url.startswith(("http://", "https://")):
        raise ValueError(
            f"`server_url` must be a full URL starting with http:// or https://, got: {server_url!r}"
        )
    server_base_url: str | None = None
    write_token_resolved: str | None = None
    if server_url is not None:
        server_base_url, tok = utils.parse_trackio_server_url(server_url)
        write_token_resolved = tok or os.environ.get("TRACKIO_WRITE_TOKEN")
        if not write_token_resolved:
            raise ValueError(
                "Self-hosted logging requires a write token: add write_token to the server URL, "
                "or set the TRACKIO_WRITE_TOKEN environment variable."
            )
    if server_url is not None and (dataset_id is not None or bucket_id is not None):
        raise ValueError(
            "`dataset_id` and `bucket_id` are Hugging Face Spaces concepts and are not "
            "compatible with `server_url`. Configure storage on the self-hosted server."
        )
    if space_id is None and dataset_id is not None:
        raise ValueError("Must provide a `space_id` when `dataset_id` is provided.")
    if dataset_id is not None and bucket_id is not None:
        raise ValueError("Cannot provide both `dataset_id` and `bucket_id`.")
    try:
        space_id, dataset_id, bucket_id = utils.preprocess_space_and_dataset_ids(
            space_id, dataset_id, bucket_id
        )
        if (
            space_id is not None
            and dataset_id is None
            and bucket_id is not None
            and not bucket_id_was_explicit
            and not utils.on_spaces()
        ):
            bucket_id = deploy.resolve_auto_bucket_id(space_id, bucket_id)
    except LocalTokenNotFoundError as e:
        raise LocalTokenNotFoundError(
            f"You must be logged in to Hugging Face locally when `space_id` is provided to deploy to a Space. {e}"
        ) from e

    if space_id is None and bucket_id is not None:
        _emit_nonfatal_warning(
            "trackio.init() has `bucket_id` set but `space_id` is None: metrics will be logged "
            "locally only. Pass `space_id` to create or use a Hugging Face Space, which will be "
            "attached to the Hugging Face Bucket.",
            UserWarning,
            stacklevel=2,
        )

    if space_id is not None:
        deploy.raise_if_space_is_frozen_for_logging(space_id)

    remote_source = space_id or server_base_url

    if remote_source is not None:
        url = remote_source
        context_vars.current_server.set(url)
        if space_id is not None:
            context_vars.current_space_id.set(space_id)
            context_vars.current_server_write_token.set(None)
        else:
            context_vars.current_space_id.set(None)
            context_vars.current_server_write_token.set(write_token_resolved)
    else:
        url = None
        context_vars.current_server.set(None)
        context_vars.current_space_id.set(None)
        context_vars.current_server_write_token.set(None)

    _should_embed_local = False

    if (
        context_vars.current_project.get() is None
        or context_vars.current_project.get() != project
    ):
        print(f"* Trackio project initialized: {project}")

        if bucket_id is not None:
            if utils.on_spaces():
                os.environ["TRACKIO_BUCKET_ID"] = bucket_id
            bucket_url = f"https://huggingface.co/buckets/{bucket_id}"
            print(
                f"* Trackio metrics will be synced to Hugging Face Bucket: {bucket_url}"
            )
        elif dataset_id is not None:
            if utils.on_spaces():
                os.environ["TRACKIO_DATASET_ID"] = dataset_id
            print(
                f"* Trackio metrics will be synced to Hugging Face Dataset: {dataset_id}"
            )
        if remote_source is None:
            print(f"* Trackio metrics logged to: {TRACKIO_DIR}")
            _should_embed_local = embed and utils.is_in_notebook()
            if not _should_embed_local:
                utils.print_dashboard_instructions(project)
        elif server_base_url is not None:
            print(
                f"* Trackio metrics will be sent to self-hosted server: {server_base_url}"
            )
            if utils.is_in_notebook() and embed:
                utils.embed_url_in_notebook(server_base_url)
        else:
            try:
                deploy.create_space_if_not_exists(
                    space_id,
                    space_storage,
                    dataset_id,
                    bucket_id,
                    private,
                )
                user_name, space_name = space_id.split("/")
                space_url = deploy.SPACE_HOST_URL.format(
                    user_name=user_name, space_name=space_name
                )
                if utils.is_in_notebook() and embed:
                    utils.embed_url_in_notebook(space_url)
            except Exception as e:
                _emit_nonfatal_warning(
                    f"trackio.init() could not prepare Space '{space_id}': {e}. Logging will continue in local fallback mode until the Space is reachable."
                )
    context_vars.current_project.set(project)

    remote_client = None
    if space_id is not None:
        try:
            remote_client = RemoteClient(
                space_id,
                hf_token=huggingface_hub.utils.get_token(),
                verbose=False,
            )
        except Exception as e:
            _emit_nonfatal_warning(
                f"trackio.init() could not create a remote client for Space '{space_id}': {e}. Continuing with local fallback metadata lookups."
            )
    elif server_base_url is not None:
        try:
            remote_client = RemoteClient(
                server_base_url,
                hf_token=None,
                write_token=write_token_resolved,
                verbose=False,
            )
        except Exception as e:
            _emit_nonfatal_warning(
                f"trackio.init() could not create a remote client for '{server_base_url}': {e}. Continuing with local fallback metadata lookups."
            )

    existing_run_records = _safe_get_runs_for_init(
        project,
        space_id,
        server_base_url,
        write_token_resolved,
        resume,
        remote_client=remote_client,
        check_existing_for_never=name is not None,
    )
    existing_runs = [
        r["name"] if isinstance(r, dict) else r for r in existing_run_records
    ]

    existing_run = (
        _safe_get_latest_run_for_init(
            project,
            name,
            space_id=space_id,
            server_base_url=server_base_url,
            write_token=write_token_resolved,
            remote_client=remote_client,
        )
        if name is not None
        else None
    )
    resolved_run_id = None

    if resume == "must":
        if name is None:
            raise ValueError("Must provide a run name when resume='must'")
        if existing_run is None:
            raise ValueError(f"Run '{name}' does not exist in project '{project}'")
        resumed = True
        resolved_run_id = existing_run["id"]
    elif resume == "allow":
        resumed = existing_run is not None
        if resumed:
            resolved_run_id = existing_run["id"]
    elif resume == "never":
        resumed = False
    else:
        raise ValueError("resume must be one of: 'must', 'allow', or 'never'")

    initial_last_step = (
        _safe_get_last_step_for_init(
            project,
            name,
            space_id,
            server_base_url,
            write_token_resolved,
            resumed,
            run_id=resolved_run_id,
            remote_client=remote_client,
        )
        if name is not None
        else None
    )

    if auto_log_gpu is None:
        nvidia_available = gpu_available()
        apple_available = apple_gpu_available()
        auto_log_gpu = nvidia_available or apple_available
        if project not in _projects_notified_auto_log_hw:
            if nvidia_available:
                print("* NVIDIA GPU detected, enabling automatic GPU metrics logging")
            elif apple_available:
                print(
                    "* Apple Silicon detected, enabling automatic system metrics logging"
                )
            if nvidia_available or apple_available:
                _projects_notified_auto_log_hw.add(project)

    run = Run(
        url=url,
        project=project,
        client=None,
        name=name,
        run_id=resolved_run_id,
        group=group,
        config=config,
        space_id=space_id,
        server_base_url=server_base_url,
        write_token=write_token_resolved,
        existing_runs=existing_runs,
        initial_last_step=initial_last_step,
        auto_log_gpu=auto_log_gpu,
        gpu_log_interval=gpu_log_interval,
        webhook_url=webhook_url,
        webhook_min_level=webhook_min_level,
    )

    if space_id is not None:
        try:
            SQLiteStorage.set_project_metadata(project, "space_id", space_id)
        except Exception as e:
            _emit_nonfatal_warning(
                f"trackio.init() could not persist Space metadata for project '{project}': {e}. Logging will continue."
            )
        try:
            if SQLiteStorage.has_pending_data(project):
                run._has_local_buffer = True
        except Exception as e:
            _emit_nonfatal_warning(
                f"trackio.init() could not inspect pending buffered data for project '{project}': {e}. Logging will continue."
            )

    global _atexit_registered
    if not _atexit_registered:
        atexit.register(_cleanup_current_run)
        _atexit_registered = True

    if resumed:
        print(f"* Resumed existing run: {run.name}")
    else:
        print(f"* Created new run: {run.name}")

    context_vars.current_run.set(run)
    globals()["config"] = run.config
    _watcher_manager.clear()

    if _should_embed_local:
        try:
            show(project=project, open_browser=False, block_thread=False)
        except Exception as e:
            _emit_nonfatal_warning(
                f"trackio.init() could not auto-launch the dashboard: {e}. Logging will continue."
            )

    return run


def log(metrics: dict, step: int | None = None) -> None:
    """
    Logs metrics to the current run.

    Args:
        metrics (`dict`):
            A dictionary of metrics to log.
        step (`int`, *optional*):
            The step number. If not provided, the step will be incremented
            automatically.
    """
    run = context_vars.current_run.get()
    if run is None:
        raise RuntimeError("Call trackio.init() before trackio.log().")
    run.log(
        metrics=metrics,
        step=step,
    )
    if _watcher_manager._watchers:
        watcher_alerts = _watcher_manager.check(metrics, step=step)
        for wa in watcher_alerts:
            alert(
                title=wa["title"],
                text=wa.get("text"),
                level=wa["level"],
                data=wa.get("data"),
            )


def log_system(metrics: dict) -> None:
    """
    Logs system metrics (GPU, etc.) to the current run using timestamps instead of steps.

    Args:
        metrics (`dict`):
            A dictionary of system metrics to log.
    """
    run = context_vars.current_run.get()
    if run is None:
        raise RuntimeError("Call trackio.init() before trackio.log_system().")
    run.log_system(metrics=metrics)


def log_gpu(run: Run | None = None, device: int | None = None) -> dict:
    """
    Log GPU metrics to the current or specified run as system metrics.
    Automatically detects whether an NVIDIA or Apple GPU is available and calls
    the appropriate logging method.

    Args:
        run: Optional Run instance. If None, uses current run from context.
        device: CUDA device index to collect metrics from (NVIDIA GPUs only).
                If None, collects from all GPUs visible to this process.
                This parameter is ignored for Apple GPUs.

    Returns:
        dict: The GPU metrics that were logged.

    Example:
        ```python
        import trackio

        run = trackio.init(project="my-project")
        trackio.log({"loss": 0.5})
        trackio.log_gpu()
        trackio.log_gpu(device=0)
        ```
    """
    if run is None:
        run = context_vars.current_run.get()
        if run is None:
            raise RuntimeError("Call trackio.init() before trackio.log_gpu().")

    if gpu_available():
        return _log_nvidia_gpu(run=run, device=device)
    elif apple_gpu_available():
        return _log_apple_gpu(run=run)
    else:
        _emit_nonfatal_warning(
            "No GPU detected. Install nvidia-ml-py for NVIDIA GPU support "
            "or psutil for Apple Silicon support."
        )
        return {}


def finish():
    """
    Finishes the current run.
    """
    run = context_vars.current_run.get()
    if run is None:
        raise RuntimeError("Call trackio.init() before trackio.finish().")
    try:
        run.finish()
    finally:
        context_vars.current_run.set(None)


def alert(
    title: str,
    text: str | None = None,
    level: AlertLevel = AlertLevel.WARN,
    webhook_url: str | None = None,
    data: dict | None = None,
) -> None:
    """
    Fires an alert immediately on the current run. The alert is printed to the
    terminal, stored in the database, and displayed in the dashboard. If a
    webhook URL is configured (via `trackio.init()`, the `TRACKIO_WEBHOOK_URL`
    environment variable, or the `webhook_url` parameter here), the alert is
    also POSTed to that URL.

    Args:
        title (`str`):
            A short title for the alert.
        text (`str`, *optional*):
            A longer description with details about the alert.
        level (`AlertLevel`, *optional*, defaults to `AlertLevel.WARN`):
            The severity level. One of `AlertLevel.INFO`, `AlertLevel.WARN`,
            or `AlertLevel.ERROR`.
        webhook_url (`str`, *optional*):
            A webhook URL to send this specific alert to. Overrides any
            URL set in `trackio.init()` or the `TRACKIO_WEBHOOK_URL`
            environment variable. Supports Slack and Discord webhook
            URLs natively.
        data (`dict`, *optional*):
            Structured data to attach to the alert. Stored as JSON and
            returned in alert queries. Useful for machine-readable alert
            payloads that agents can parse programmatically.
    """
    run = context_vars.current_run.get()
    if run is None:
        raise RuntimeError("Call trackio.init() before trackio.alert().")
    run.alert(title=title, text=text, level=level, webhook_url=webhook_url, data=data)


_watcher_manager = WatcherManager()


def watch(
    metric: str,
    nan: bool = True,
    spike_factor: float | None = None,
    patience: int | None = None,
    min_delta: float = 0.0,
    max_value: float | None = None,
    min_value: float | None = None,
    window: int = 5,
) -> None:
    """
    Register a metric watcher that automatically fires alerts when conditions
    are met during ``trackio.log()`` calls.

    Args:
        metric (`str`):
            The metric name to watch (e.g., ``"train/loss"``).
        nan (`bool`, *optional*, defaults to `True`):
            Fire an ERROR alert if the metric becomes NaN or Inf.
        spike_factor (`float`, *optional*):
            Fire a WARN alert if the value exceeds the recent moving average
            by this factor (e.g., ``3.0`` means 3x the recent average).
        patience (`int`, *optional*):
            Fire a WARN alert if no improvement is seen for this many log
            steps. Also sets ``should_stop()`` to True.
        min_delta (`float`, *optional*, defaults to `0.0`):
            Minimum change to qualify as an improvement (used with patience).
        max_value (`float`, *optional*):
            Fire an ERROR alert if the metric exceeds this value. Also sets
            ``should_stop()`` to True.
        min_value (`float`, *optional*):
            Fire a WARN alert if the metric drops below this value.
        window (`int`, *optional*, defaults to `5`):
            Number of recent values to use for spike detection averaging.
    """
    watcher = MetricWatcher(
        metric_name=metric,
        nan=nan,
        spike_factor=spike_factor,
        patience=patience,
        min_delta=min_delta,
        max_value=max_value,
        min_value=min_value,
        window=window,
    )
    _watcher_manager.add(watcher)


def should_stop() -> bool:
    """
    Returns True if any registered watcher has triggered a stop condition
    (NaN/Inf, max_value exceeded, or patience exhausted).

    Designed for use in training loops::

        if trackio.should_stop():
            break
    """
    return _watcher_manager.should_stop


def delete_project(project: str, force: bool = False) -> bool:
    """
    Deletes a project by removing its local SQLite database.

    Args:
        project (`str`):
            The name of the project to delete.
        force (`bool`, *optional*, defaults to `False`):
            If `True`, deletes the project without prompting for confirmation.
            If `False`, prompts the user to confirm before deleting.

    Returns:
        `bool`: `True` if the project was deleted, `False` otherwise.
    """
    db_path = SQLiteStorage.get_project_db_path(project)

    if not db_path.exists():
        print(f"* Project '{project}' does not exist.")
        return False

    if not force:
        response = input(
            f"Are you sure you want to delete project '{project}'? "
            f"This will permanently delete all runs and metrics. (y/N): "
        )
        if response.lower() not in ["y", "yes"]:
            print("* Deletion cancelled.")
            return False

    try:
        db_path.unlink()

        for suffix in ("-wal", "-shm"):
            sidecar = Path(str(db_path) + suffix)
            if sidecar.exists():
                sidecar.unlink()

        print(f"* Project '{project}' has been deleted.")
        return True
    except Exception as e:
        print(f"* Error deleting project '{project}': {e}")
        return False


def save(
    glob_str: str | Path,
    project: str | None = None,
) -> str:
    """
    Saves files to a project (not linked to a specific run). If Trackio is running
    locally, the file(s) will be copied to the project's files directory. If Trackio is
    running in a Space, the file(s) will be uploaded to the Space's files directory.

    Args:
        glob_str (`str` or `Path`):
            The file path or glob pattern to save. Can be a single file or a pattern
            matching multiple files (e.g., `"*.py"`, `"models/**/*.pth"`).
        project (`str`, *optional*):
            The name of the project to save files to. If not provided, uses the current
            project from `trackio.init()`. If no project is initialized, raises an
            error.

    Returns:
        `str`: The path where the file(s) were saved (project's files directory).

    Example:
        ```python
        import trackio

        trackio.init(project="my-project")
        trackio.save("config.yaml")
        trackio.save("models/*.pth")
        ```
    """
    if project is None:
        project = context_vars.current_project.get()
        if project is None:
            raise RuntimeError(
                "No project specified. Either call trackio.init() first or provide a "
                "project parameter to trackio.save()."
            )

    glob_str = Path(glob_str)
    base_path = Path.cwd().resolve()

    matched_files = []
    if glob_str.is_file():
        matched_files = [glob_str.resolve()]
    else:
        pattern = str(glob_str)
        if not glob_str.is_absolute():
            pattern = str((Path.cwd() / glob_str).resolve())
        matched_files = [
            Path(f).resolve()
            for f in glob.glob(pattern, recursive=True)
            if Path(f).is_file()
        ]

    if not matched_files:
        raise ValueError(f"No files found matching pattern: {glob_str}")

    current_run = context_vars.current_run.get()
    is_local = (
        current_run._is_local
        if current_run is not None
        else (
            context_vars.current_space_id.get() is None
            and context_vars.current_server.get() is None
        )
    )

    if is_local:
        for file_path in matched_files:
            try:
                relative_to_base = file_path.relative_to(base_path)
            except ValueError:
                relative_to_base = Path(file_path.name)

            if current_run is not None:
                current_run._queue_upload(
                    file_path,
                    step=None,
                    relative_path=str(relative_to_base.parent),
                    use_run_name=False,
                )
            else:
                media_path = get_project_media_path(
                    project=project,
                    run=None,
                    step=None,
                    relative_path=str(relative_to_base),
                )
                shutil.copy(str(file_path), str(media_path))
    else:
        url = context_vars.current_server.get()

        upload_entries = []
        for file_path in matched_files:
            try:
                relative_to_base = file_path.relative_to(base_path)
            except ValueError:
                relative_to_base = Path(file_path.name)

            if current_run is not None:
                current_run._queue_upload(
                    file_path,
                    step=None,
                    relative_path=str(relative_to_base.parent),
                    use_run_name=False,
                )
            else:
                upload_entry: UploadEntry = {
                    "project": project,
                    "run": None,
                    "step": None,
                    "relative_path": str(relative_to_base),
                    "uploaded_file": handle_file(file_path),
                }
                upload_entries.append(upload_entry)

        if upload_entries:
            if url is None:
                raise RuntimeError(
                    "No server available. Call trackio.init() before trackio.save() to start the server."
                )

            try:
                wt = context_vars.current_server_write_token.get()
                if wt is not None:
                    client = RemoteClient(
                        url,
                        hf_token=None,
                        write_token=wt,
                        httpx_kwargs={"timeout": 90},
                    )
                else:
                    client = RemoteClient(
                        url,
                        hf_token=huggingface_hub.utils.get_token(),
                        httpx_kwargs={"timeout": 90},
                    )
                client.predict(
                    api_name="/bulk_upload_media",
                    uploads=upload_entries,
                    hf_token=huggingface_hub.utils.get_token() if wt is None else None,
                )
            except Exception as e:
                _emit_nonfatal_warning(
                    f"Failed to upload files: {e}. "
                    "Files may not be available in the dashboard."
                )

    return str(utils.MEDIA_DIR / project / "files")


def show(
    project: str | None = None,
    *,
    theme: Any = None,
    mcp_server: bool | None = None,
    footer: bool = True,
    color_palette: list[str] | None = None,
    open_browser: bool = True,
    block_thread: bool | None = None,
    host: str | None = None,
    share: bool | None = None,
    server_port: int | None = None,
):
    """
    Launches the Trackio dashboard.

    Args:
        project (`str`, *optional*):
            The name of the project whose runs to show. If not provided, all projects
            will be shown and the user can select one.
        theme (`Any`, *optional*):
            Ignored. Kept for backward compatibility; Trackio no longer uses Gradio themes.
        mcp_server (`bool`, *optional*):
            If `True`, the dashboard exposes an MCP server at `/mcp` when the optional
            `trackio[mcp]` dependency is installed. If `None` (default), the
            `GRADIO_MCP_SERVER` environment variable is used (e.g. on Spaces).
        footer (`bool`, *optional*, defaults to `True`):
            Whether to include `footer=false` in the write-token URL when `False`.
            This can also be controlled via the `footer` query parameter in the URL.
        color_palette (`list[str]`, *optional*):
            A list of hex color codes to use for plot lines. If not provided, the
            `TRACKIO_COLOR_PALETTE` environment variable will be used (comma-separated
            hex codes), or if that is not set, the default color palette will be used.
            Example: `['#FF0000', '#00FF00', '#0000FF']`
        open_browser (`bool`, *optional*, defaults to `True`):
            If `True` and not in a notebook, a new browser tab will be opened with the
            dashboard. If `False`, the browser will not be opened.
        block_thread (`bool`, *optional*):
            If `True`, the main thread will be blocked until the dashboard is closed.
            If `None` (default behavior), then the main thread will not be blocked if the
            dashboard is launched in a notebook, otherwise the main thread will be blocked.
        host (`str`, *optional*):
            The host to bind the server to. If not provided, defaults to `'127.0.0.1'`
            (localhost only). Set to `'0.0.0.0'` to allow remote access.
        share (`bool`, *optional*):
            If `True`, creates a temporary public URL (Gradio-compatible tunnel). On Colab
            or hosted notebooks, defaults to `True` unless overridden.
        server_port (`int`, *optional*):
            Port to bind. If not set, scans from `GRADIO_SERVER_PORT` (default 7860).

        Returns:
            `app`: The dashboard handle (`.close()` stops the server).
            `url`: The local URL of the dashboard.
            `share_url`: The public share URL, if any.
            `full_url`: The full URL including the write token (share URL when sharing, else local).
    """
    if theme is not None and theme != "default":
        warnings.warn(
            "The theme argument is ignored; Trackio no longer depends on Gradio themes.",
            UserWarning,
            stacklevel=2,
        )

    if color_palette is not None:
        os.environ["TRACKIO_COLOR_PALETTE"] = ",".join(color_palette)

    _mcp_server = (
        mcp_server
        if mcp_server is not None
        else os.environ.get("GRADIO_MCP_SERVER", "False") == "True"
    )

    starlette_app, wt = build_starlette_app_only(mcp_server=_mcp_server)
    local_url, share_url, _local_api_url, uv_server = launch_trackio_dashboard(
        starlette_app,
        server_name=host,
        server_port=server_port,
        share=share,
        mcp_server=_mcp_server,
        quiet=True,
    )
    server = TrackioDashboardApp(starlette_app, uv_server, wt)

    base_root = (share_url or local_url).rstrip("/")
    base_url = base_root + "/"
    dashboard_url = base_url
    if project:
        dashboard_url += f"?project={project}"
    full_url = utils.get_full_url(
        base_root,
        project=project,
        write_token=wt,
        footer=footer,
    )

    if not utils.is_in_notebook():
        print(f"\033[1m\033[38;5;208m* Trackio UI launched at: {dashboard_url}\033[0m")
        utils.print_write_token_instructions(full_url)
        if open_browser:
            webbrowser.open(full_url)
        block_thread = block_thread if block_thread is not None else True
    else:
        utils.embed_url_in_notebook(full_url)
        block_thread = block_thread if block_thread is not None else False

    if block_thread:
        utils.block_main_thread_until_keyboard_interrupt()
    return _TupleNoPrint((server, local_url, share_url, full_url))
