"""Upgrade an existing Trackio Space to the locally installed Trackio version.

`bump()` either upgrades a Space in place or duplicates it (and its bucket) into
a new Space running the local version. The Space's SQLite databases live in the
Hugging Face Bucket mounted at `/data`; the new Trackio server migrates them when
it opens them on boot. While an in-place bump is in progress the Space is paused,
so training clients write their logs to the bucket inbox as JSONL fragments,
which the upgraded Space imports once it is running again.
"""

import io
import json
import re
import sqlite3
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
import huggingface_hub
from huggingface_hub.errors import (
    BucketNotFoundError,
    HfHubHTTPError,
    RepositoryNotFoundError,
)

import trackio
from trackio import deploy
from trackio.bucket_storage import _list_bucket_file_paths, create_bucket_if_not_exists
from trackio.remote_client import RemoteClient, _space_id_to_url
from trackio.sqlite_storage import DB_EXT, SCHEMA_VERSION, SQLiteStorage
from trackio.utils import preprocess_space_and_dataset_ids

MIN_BUMPABLE_VERSION = "0.21.0"
BACKUP_PREFIX = "trackio-backups"
DB_PREFIX = "trackio/"
_JOURNAL_SUFFIX = "-journal"
_REQUIREMENT_PATTERN = re.compile(
    r"^\s*trackio(?:\[[^\]]*\])?\s*==\s*([0-9][0-9A-Za-z.+\-]*)\s*$"
)
_VERSION_PATTERN = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
_MANAGED_VARIABLES = frozenset({"TRACKIO_DIR", "TRACKIO_BUCKET_ID"})
_FAILURE_STAGES = frozenset(
    ("NO_APP_FILE", "CONFIG_ERROR", "BUILD_ERROR", "RUNTIME_ERROR")
)


class BumpError(RuntimeError):
    pass


def _version_tuple(version: str) -> tuple[int, int, int] | None:
    match = _VERSION_PATTERN.match(version)
    if match is None:
        return None
    return tuple(int(part) for part in match.groups())


def get_space_trackio_version(
    space_id: str, hf_api: huggingface_hub.HfApi | None = None
) -> str | None:
    """
    Returns the Trackio version a Space is configured to run, read from its
    `requirements.txt` pin, or from `trackio/package.json` for Spaces deployed from
    a source install. Returns `None` when the version cannot be determined.
    """
    hf_api = hf_api or huggingface_hub.HfApi()
    try:
        path = hf_api.hf_hub_download(space_id, "requirements.txt", repo_type="space")
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            if match := _REQUIREMENT_PATTERN.match(line):
                return match.group(1)
    except (HfHubHTTPError, OSError):
        pass
    try:
        path = hf_api.hf_hub_download(
            space_id, "trackio/package.json", repo_type="space"
        )
        return json.loads(Path(path).read_text(encoding="utf-8")).get("version")
    except (HfHubHTTPError, OSError, ValueError):
        return None


def _check_bumpable(space_id: str, space_version: str | None) -> str:
    local = _version_tuple(trackio.__version__)
    if local is None:
        raise BumpError(
            f"The local Trackio version {trackio.__version__!r} is not a final "
            "release, so it cannot be compared safely with the Space's version."
        )
    if space_version is None:
        raise BumpError(
            f"Could not determine which Trackio version Space '{space_id}' runs. "
            "`trackio bump` only supports Spaces deployed by Trackio."
        )
    remote = _version_tuple(space_version)
    if remote is None:
        raise BumpError(
            f"Space '{space_id}' pins Trackio {space_version!r}, which is not a final "
            "release that `trackio bump` can compare safely."
        )
    if remote < _version_tuple(MIN_BUMPABLE_VERSION):
        raise BumpError(
            f"Space '{space_id}' runs Trackio {space_version}, which is older than "
            f"{MIN_BUMPABLE_VERSION}, the oldest version `trackio bump` supports."
        )
    if remote > local:
        raise BumpError(
            f"Space '{space_id}' runs Trackio {space_version}, which is newer than the "
            f"local Trackio {trackio.__version__}. Upgrade Trackio locally instead of downgrading the Space."
        )
    return space_version


def _bucket_db_paths(bucket_id: str, prefix: str = DB_PREFIX) -> list[str]:
    return sorted(
        path
        for path in _list_bucket_file_paths(bucket_id, prefix=prefix)
        if "/" not in path[len(prefix) :]
        and (path.endswith(DB_EXT) or path.endswith(DB_EXT + _JOURNAL_SUFFIX))
    )


def _db_inventory(db_path: Path) -> dict:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro&immutable=1", uri=True)
    try:
        tables = [
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            )
        ]
        counts = {
            table: conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            for table in tables
        }
        runs = {}
        if "metrics" in tables:
            runs = dict(
                conn.execute("SELECT run_name, COUNT(*) FROM metrics GROUP BY run_name")
            )
        return {"tables": counts, "metric_rows_per_run": runs}
    finally:
        conn.close()


def bucket_inventory(bucket_id: str, prefix: str = DB_PREFIX) -> dict[str, dict]:
    """
    Downloads every project database under `prefix` in a bucket and returns, per
    database filename, the row count of each table and the metric rows per run.
    """
    db_paths = [p for p in _bucket_db_paths(bucket_id, prefix) if p.endswith(DB_EXT)]
    inventory = {}
    with tempfile.TemporaryDirectory() as work_dir:
        for remote_path in db_paths:
            filename = remote_path.rsplit("/", 1)[-1]
            local_path = Path(work_dir) / filename
            huggingface_hub.download_bucket_files(
                bucket_id,
                files=[(remote_path, str(local_path))],
                token=huggingface_hub.utils.get_token(),
            )
            inventory[filename] = _db_inventory(local_path)
    return inventory


def _remote_client(space_id: str) -> RemoteClient:
    return RemoteClient(
        space_id, hf_token=huggingface_hub.utils.get_token(), verbose=False
    )


def _served_version(space_id: str) -> str | None:
    headers = {}
    if token := huggingface_hub.utils.get_token():
        headers["Authorization"] = f"Bearer {token}"
    try:
        response = httpx.get(
            _space_id_to_url(space_id) + "version", headers=headers, timeout=30
        )
        response.raise_for_status()
        return response.json().get("version")
    except (httpx.HTTPError, ValueError):
        return None


def verify_space_serves_inventory(
    space_id: str, inventory: dict[str, dict], timeout: int = 300
) -> None:
    """
    Checks that a running Space serves the local Trackio version, that every
    project database reached the local `SCHEMA_VERSION`, and that every table
    still holds at least the rows recorded in `inventory`. Rows can only grow,
    since the Space may import inbox fragments.
    """
    expected_version = trackio.__version__
    deadline = time.time() + timeout
    served = None
    while time.time() < deadline:
        served = _served_version(space_id)
        if served == expected_version:
            break
        time.sleep(5)
    if served != expected_version:
        raise BumpError(
            f"Space '{space_id}' serves Trackio {served}, expected {expected_version}."
        )

    client = _remote_client(space_id)
    projects = client.predict(api_name="/get_all_projects")
    by_filename = {SQLiteStorage.get_project_db_filename(p): p for p in projects}
    for filename, expected in inventory.items():
        project = by_filename.get(filename)
        if project is None:
            raise BumpError(
                f"Space '{space_id}' no longer lists the project stored in {filename}."
            )
        result = client.predict(
            project, "PRAGMA user_version", api_name="/query_project"
        )
        schema_version = result["rows"][0]["user_version"]
        if schema_version != SCHEMA_VERSION:
            raise BumpError(
                f"Project '{project}' is at schema version {schema_version} after the "
                f"bump, expected {SCHEMA_VERSION}."
            )
        for table, count in expected["tables"].items():
            result = client.predict(
                project,
                f'SELECT COUNT(*) AS n FROM "{table}"',
                api_name="/query_project",
            )
            actual = result["rows"][0]["n"]
            if actual < count:
                raise BumpError(
                    f"Project '{project}' table '{table}' has {actual} rows after the "
                    f"bump, expected at least {count}."
                )
        result = client.predict(
            project,
            "SELECT run_name, COUNT(*) AS n FROM metrics GROUP BY run_name",
            api_name="/query_project",
        )
        actual_runs = {row["run_name"]: row["n"] for row in result["rows"]}
        for run, count in expected["metric_rows_per_run"].items():
            if actual_runs.get(run, 0) < count:
                raise BumpError(
                    f"Run '{run}' in project '{project}' has {actual_runs.get(run, 0)} "
                    f"metric rows after the bump, expected at least {count}."
                )


def _wait_for_stage(
    space_id: str,
    targets: frozenset[str],
    timeout: int,
    hf_api: huggingface_hub.HfApi,
) -> None:
    deadline = time.time() + timeout
    stage = None
    while time.time() < deadline:
        try:
            runtime = hf_api.get_space_runtime(space_id)
            stage = str(runtime.stage)
        except (HfHubHTTPError, httpx.RequestError):
            stage = None
        if stage in targets:
            return
        if stage in _FAILURE_STAGES and not targets & _FAILURE_STAGES:
            raise BumpError(
                f"Space '{space_id}' entered {stage}. Check its logs on the Hub."
            )
        time.sleep(5)
    raise BumpError(
        f"Space '{space_id}' did not reach {'/'.join(sorted(targets))} within "
        f"{timeout}s (last stage: {stage})."
    )


def _runtime_operations(
    space_id: str, hf_api: huggingface_hub.HfApi, revision: str
) -> list[huggingface_hub.CommitOperationAdd]:
    repo_files = set(
        hf_api.list_repo_files(space_id, repo_type="space", revision=revision)
    )
    has_custom_frontend = any(
        f.startswith(deploy._CUSTOM_SPACE_FRONTEND_DIR + "/") for f in repo_files
    )
    if deploy._is_trackio_installed_from_source():
        requirements = deploy._get_source_install_dependencies()
    else:
        requirements = deploy._get_space_install_requirement()
    app_py = deploy._space_app_py(
        deploy._CUSTOM_SPACE_FRONTEND_DIR if has_custom_frontend else None
    )
    return [
        huggingface_hub.CommitOperationAdd(
            "requirements.txt", io.BytesIO(requirements.encode("utf-8"))
        ),
        huggingface_hub.CommitOperationAdd(
            "app.py", io.BytesIO(app_py.encode("utf-8"))
        ),
    ]


def _copy_bucket_paths(bucket_id: str, pairs: list[tuple[str, str]]) -> None:
    for source, destination in pairs:
        huggingface_hub.copy_files(
            f"hf://buckets/{bucket_id}/{source}",
            f"hf://buckets/{bucket_id}/{destination}",
        )


def _bump_in_place(
    space_id: str,
    bucket_id: str,
    space_version: str,
    hf_api: huggingface_hub.HfApi,
    timeout: int,
) -> str:
    local_version = trackio.__version__
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_prefix = f"{BACKUP_PREFIX}/{space_version}-to-{local_version}-{stamp}/"

    base_commit = hf_api.repo_info(space_id, repo_type="space").sha
    with tempfile.TemporaryDirectory() as snapshot_dir:
        hf_api.snapshot_download(
            space_id,
            repo_type="space",
            revision=base_commit,
            local_dir=snapshot_dir,
            max_workers=4,
        )
        print(f"* Pausing {space_id}; new logs will queue in the bucket inbox")
        hf_api.pause_space(space_id)
        _wait_for_stage(space_id, frozenset({"PAUSED"}), 300, hf_api)

        try:
            db_paths = _bucket_db_paths(bucket_id)
            backups = [
                (path, backup_prefix + path[len(DB_PREFIX) :]) for path in db_paths
            ]
            _copy_bucket_paths(bucket_id, backups)
            print(
                f"* Backed up {len(db_paths)} database files to "
                f"hf://buckets/{bucket_id}/{backup_prefix}"
            )
            inventory = bucket_inventory(bucket_id, prefix=backup_prefix)
        except Exception as e:
            hf_api.restart_space(space_id)
            raise BumpError(
                f"Backing up '{space_id}' failed before anything was changed, so the "
                f"Space was restarted on Trackio {space_version}: {e}"
            ) from e

        bump_commit = None
        try:
            print(
                f"* Updating {space_id} from Trackio {space_version} to {local_version}"
            )
            bump_commit = hf_api.create_commit(
                space_id,
                operations=_runtime_operations(space_id, hf_api, base_commit),
                commit_message=f"Bump Trackio to {local_version}",
                repo_type="space",
                parent_commit=base_commit,
            ).oid
            if deploy._is_trackio_installed_from_source():
                bump_commit = deploy._upload_source_tree(
                    hf_api, space_id, parent_commit=bump_commit
                ).oid
            hf_api.restart_space(space_id)
            print("* Waiting for the Space to rebuild and migrate its data")
            _wait_for_stage(space_id, frozenset({"RUNNING"}), timeout, hf_api)
            verify_space_serves_inventory(space_id, inventory)
        except Exception as e:
            print(f"* Bump failed ({e}); restoring Trackio {space_version}")
            _rollback(
                space_id,
                bucket_id,
                backups,
                Path(snapshot_dir),
                bump_commit,
                hf_api,
                timeout,
            )
            raise BumpError(
                f"Bumping '{space_id}' failed and was rolled back to Trackio "
                f"{space_version}: {e}"
            ) from e

    print(
        f"* {space_id} now runs Trackio {local_version}: "
        f"{deploy.SPACE_URL.format(space_id=space_id)}"
    )
    return space_id


def _rollback(
    space_id: str,
    bucket_id: str,
    backups: list[tuple[str, str]],
    snapshot_dir: Path,
    bump_commit: str | None,
    hf_api: huggingface_hub.HfApi,
    timeout: int,
) -> None:
    hf_api.pause_space(space_id)
    _wait_for_stage(space_id, frozenset({"PAUSED"}), 300, hf_api)
    _copy_bucket_paths(bucket_id, [(backup, path) for path, backup in backups])
    try:
        if bump_commit is not None:
            hf_api.upload_folder(
                repo_id=space_id,
                repo_type="space",
                folder_path=snapshot_dir,
                ignore_patterns=[".cache/**"],
                delete_patterns=["*", "**/*"],
                commit_message="Roll back failed Trackio bump",
                parent_commit=bump_commit,
            )
    finally:
        hf_api.restart_space(space_id)
    _wait_for_stage(space_id, frozenset({"RUNNING"}) | _FAILURE_STAGES, timeout, hf_api)


def _bump_into_new_space(
    space_id: str,
    bucket_id: str,
    new_space_id: str,
    new_bucket_id: str,
    hf_api: huggingface_hub.HfApi,
    timeout: int,
) -> str:
    try:
        hf_api.space_info(new_space_id)
        raise BumpError(f"Space '{new_space_id}' already exists.")
    except RepositoryNotFoundError:
        pass
    try:
        if _list_bucket_file_paths(new_bucket_id):
            raise BumpError(
                f"Bucket '{new_bucket_id}' already exists and is not empty."
            )
    except BucketNotFoundError:
        pass

    private = bool(hf_api.space_info(space_id).private)
    created_bucket = not deploy._bucket_exists(new_bucket_id, hf_api)
    try:
        create_bucket_if_not_exists(
            new_bucket_id, private=bool(hf_api.bucket_info(bucket_id).private)
        )
        if _list_bucket_file_paths(bucket_id):
            print(f"* Copying hf://buckets/{bucket_id} to hf://buckets/{new_bucket_id}")
            huggingface_hub.copy_files(
                f"hf://buckets/{bucket_id}/",
                f"hf://buckets/{new_bucket_id}/",
            )
        inventory = bucket_inventory(new_bucket_id)

        print(f"* Creating {new_space_id} with Trackio {trackio.__version__}")
        deploy.deploy_as_space(new_space_id, bucket_id=new_bucket_id, private=private)
        for key, variable in hf_api.get_space_variables(space_id).items():
            if key not in _MANAGED_VARIABLES:
                hf_api.add_space_variable(new_space_id, key, variable.value)
        _wait_for_stage(new_space_id, frozenset({"RUNNING"}), timeout, hf_api)
        verify_space_serves_inventory(new_space_id, inventory)
    except Exception as e:
        print(f"* Bump failed ({e}); removing {new_space_id} and its copied data")
        try:
            _remove_new_space(new_space_id, new_bucket_id, created_bucket, hf_api)
        except Exception as cleanup_error:
            print(f"* Could not remove {new_space_id}: {cleanup_error}")
        raise BumpError(
            f"Copying '{space_id}' into '{new_space_id}' failed and the new Space "
            f"was removed; '{space_id}' was not modified: {e}"
        ) from e
    print(
        f"* {new_space_id} runs Trackio {trackio.__version__} with a copy of "
        f"{space_id}'s data: {deploy.SPACE_URL.format(space_id=new_space_id)}"
    )
    return new_space_id


def _remove_new_space(
    new_space_id: str,
    new_bucket_id: str,
    created_bucket: bool,
    hf_api: huggingface_hub.HfApi,
) -> None:
    hf_api.delete_repo(new_space_id, repo_type="space", missing_ok=True)
    if created_bucket:
        hf_api.delete_bucket(new_bucket_id, missing_ok=True)
        return
    copied = _list_bucket_file_paths(new_bucket_id)
    if copied:
        huggingface_hub.batch_bucket_files(new_bucket_id, delete=copied)


def bump(
    space_id: str,
    new_space_id: str | None = None,
    new_bucket_id: str | None = None,
    timeout: int = 1800,
) -> str:
    """
    Upgrades a Trackio Space to the locally installed Trackio version.

    Without `new_space_id`, the Space is upgraded in place: it is paused (clients
    keep logging to the bucket inbox), its databases are backed up inside its
    bucket, its Trackio pin is updated and it is restarted so the new server
    migrates the data. If the Space fails to come back or loses data, the backup
    and the previous Space files are restored.

    With `new_space_id`, the source Space is left untouched and its bucket data is
    copied into `new_bucket_id`, which backs a new Space running the local version.

    Args:
        space_id (`str`):
            The Trackio Space to upgrade. Must run Trackio 0.21.0 or newer with a
            bucket mounted at `/data`.
        new_space_id (`str`, *optional*):
            Create this Space from a copy of `space_id` instead of upgrading in place.
        new_bucket_id (`str`, *optional*):
            The bucket for `new_space_id`. Defaults to `{new_space_id}-bucket`.
        timeout (`int`, *optional*, defaults to `1800`):
            Seconds to wait for the upgraded Space to build and start.

    Returns:
        `str`: The ID of the Space now running the local Trackio version.
    """
    if new_bucket_id is not None and new_space_id is None:
        raise BumpError("new_bucket_id requires new_space_id.")
    space_id, _, _ = preprocess_space_and_dataset_ids(space_id, None, None)
    hf_api = huggingface_hub.HfApi()
    try:
        info = hf_api.space_info(space_id)
    except RepositoryNotFoundError:
        raise BumpError(f"Space '{space_id}' not found.")
    if info.sdk != "gradio":
        raise BumpError(
            f"Space '{space_id}' is not a Trackio Gradio Space (sdk={info.sdk!r})."
        )
    bucket_id = deploy._get_existing_space_bucket(space_id, hf_api=hf_api)
    if bucket_id is None:
        raise BumpError(
            f"Space '{space_id}' has no bucket mounted at '/data'. "
            "`trackio bump` requires bucket storage."
        )
    space_version = _check_bumpable(
        space_id, get_space_trackio_version(space_id, hf_api)
    )

    if new_space_id is not None:
        new_space_id, _, auto_bucket_id = preprocess_space_and_dataset_ids(
            new_space_id, None, new_bucket_id
        )
        return _bump_into_new_space(
            space_id,
            bucket_id,
            new_space_id,
            auto_bucket_id,
            hf_api,
            timeout,
        )

    if (
        space_version == trackio.__version__
        and not deploy._is_trackio_installed_from_source()
    ):
        print(f"* {space_id} already runs Trackio {space_version}")
        return space_id
    return _bump_in_place(space_id, bucket_id, space_version, hf_api, timeout)
