import shutil
import tempfile
from pathlib import Path

import huggingface_hub
from huggingface_hub import copy_files, sync_bucket

from trackio.sqlite_storage import SQLiteStorage
from trackio.utils import MEDIA_DIR, TRACKIO_DIR


def create_bucket_if_not_exists(bucket_id: str, private: bool | None = None) -> None:
    huggingface_hub.create_bucket(bucket_id, private=private, exist_ok=True)


def _list_bucket_file_paths(bucket_id: str, prefix: str | None = None) -> list[str]:
    items = huggingface_hub.list_bucket_tree(bucket_id, prefix=prefix, recursive=True)
    return [
        item.path
        for item in items
        if getattr(item, "type", None) == "file" and getattr(item, "path", None)
    ]


def download_bucket_to_trackio_dir(bucket_id: str) -> None:
    TRACKIO_DIR.mkdir(parents=True, exist_ok=True)
    sync_bucket(
        source=f"hf://buckets/{bucket_id}",
        dest=str(TRACKIO_DIR.parent),
        quiet=True,
    )


def upload_project_to_bucket(project: str, bucket_id: str) -> None:
    db_path = SQLiteStorage.get_project_db_path(project)
    if not db_path.exists():
        raise FileNotFoundError(f"No database found for project '{project}'")
    files_to_add = []
    if db_path.is_dir():
        for file_path in db_path.rglob("*"):
            if file_path.is_file():
                rel = file_path.relative_to(db_path)
                files_to_add.append(
                    (str(file_path), f"trackio/{db_path.name}/{rel.as_posix()}")
                )
    else:
        with SQLiteStorage._get_connection(
            db_path, configure_pragmas=False, row_factory=None
        ) as conn:
            if conn is not None:
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        files_to_add.append((str(db_path), f"trackio/{db_path.name}"))

    media_dir = MEDIA_DIR / project
    if media_dir.exists():
        for media_file in media_dir.rglob("*"):
            if media_file.is_file():
                rel = media_file.relative_to(TRACKIO_DIR)
                files_to_add.append((str(media_file), f"trackio/{rel}"))

    huggingface_hub.batch_bucket_files(bucket_id, add=files_to_add)


def _download_db_from_bucket(
    project: str, bucket_id: str, dest_path: Path | None = None
) -> bool:
    db_filename = SQLiteStorage.get_project_db_filename(project)
    local_path = dest_path or SQLiteStorage.get_project_db_path(project)
    local_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        if db_filename.endswith(".trackio"):
            prefix = f"trackio/{db_filename}/"
            remote_files = _list_bucket_file_paths(bucket_id, prefix=prefix)
            if not remote_files:
                return False
            local_path.mkdir(parents=True, exist_ok=True)
            huggingface_hub.download_bucket_files(
                bucket_id,
                files=[
                    (
                        remote_file,
                        str(local_path / Path(remote_file.removeprefix(prefix))),
                    )
                    for remote_file in remote_files
                ],
                token=huggingface_hub.utils.get_token(),
            )
        else:
            remote_path = f"trackio/{db_filename}"
            huggingface_hub.download_bucket_files(
                bucket_id,
                files=[(remote_path, str(local_path))],
                token=huggingface_hub.utils.get_token(),
            )
        return local_path.exists()
    except Exception:
        return False


def _local_db_has_data(project: str) -> bool:
    db_path = SQLiteStorage.get_project_db_path(project)
    if not db_path.exists():
        return False
    try:
        return len(SQLiteStorage.get_runs(project)) > 0
    except Exception:
        return False


def _export_and_upload_static(
    project: str,
    dest_bucket_id: str,
    db_path: Path,
    media_dir: Path | None = None,
) -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        output_dir = Path(tmp_dir)
        SQLiteStorage.export_for_static_space(
            project, output_dir, db_path_override=db_path
        )

        if media_dir and media_dir.exists():
            shutil.copytree(media_dir, output_dir / "media")

        files_to_add = []
        for f in output_dir.rglob("*"):
            if f.is_file():
                rel = f.relative_to(output_dir)
                files_to_add.append((str(f), str(rel)))

        huggingface_hub.batch_bucket_files(dest_bucket_id, add=files_to_add)


def _copy_project_media_between_buckets(
    source_bucket_id: str, dest_bucket_id: str, project: str
) -> None:
    source_media_prefix = f"trackio/media/{project}/"
    media_to_copy = _list_bucket_file_paths(
        source_bucket_id, prefix=source_media_prefix
    )
    if not media_to_copy:
        return

    copy_files(
        f"hf://buckets/{source_bucket_id}/{source_media_prefix}",
        f"hf://buckets/{dest_bucket_id}/media/",
    )


def upload_project_to_bucket_for_static(project: str, bucket_id: str) -> None:
    if not _local_db_has_data(project):
        _download_db_from_bucket(project, bucket_id)

    db_path = SQLiteStorage.get_project_db_path(project)
    _export_and_upload_static(project, bucket_id, db_path, MEDIA_DIR / project)


def export_from_bucket_for_static(
    source_bucket_id: str,
    dest_bucket_id: str,
    project: str,
) -> None:
    with tempfile.TemporaryDirectory() as work_dir:
        work_path = Path(work_dir)
        db_path = work_path / SQLiteStorage.get_project_db_filename(project)

        if not _download_db_from_bucket(project, source_bucket_id, dest_path=db_path):
            raise FileNotFoundError(
                f"Could not download database for project '{project}' "
                f"from bucket '{source_bucket_id}'."
            )

        _export_and_upload_static(project, dest_bucket_id, db_path)
        _copy_project_media_between_buckets(source_bucket_id, dest_bucket_id, project)
