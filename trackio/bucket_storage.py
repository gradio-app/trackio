import shutil
import sqlite3
import tempfile
from pathlib import Path

import huggingface_hub
from huggingface_hub import sync_bucket

from trackio.sqlite_storage import SQLiteStorage
from trackio.utils import MEDIA_DIR, TRACKIO_DIR


def create_bucket_if_not_exists(bucket_id: str, private: bool | None = None) -> None:
    huggingface_hub.create_bucket(bucket_id, private=private or False, exist_ok=True)


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

    with SQLiteStorage._get_connection(
        db_path, timeout=30.0, configure_pragmas=False, row_factory=None
    ) as conn:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    files_to_add = [(str(db_path), f"trackio/{db_path.name}")]

    media_dir = MEDIA_DIR / project
    if media_dir.exists():
        for media_file in media_dir.rglob("*"):
            if media_file.is_file():
                rel = media_file.relative_to(TRACKIO_DIR)
                files_to_add.append((str(media_file), f"trackio/{rel}"))

    huggingface_hub.batch_bucket_files(bucket_id, add=files_to_add)


def _download_db_from_bucket(project: str, bucket_id: str) -> bool:
    db_filename = SQLiteStorage.get_project_db_filename(project)
    remote_path = f"trackio/{db_filename}"
    local_path = SQLiteStorage.get_project_db_path(project)
    local_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        huggingface_hub.download_bucket_files(
            bucket_id,
            files=[(remote_path, str(local_path))],
        )
        return local_path.exists()
    except Exception:
        return False


def _local_db_has_data(project: str) -> bool:
    db_path = SQLiteStorage.get_project_db_path(project)
    if not db_path.exists() or db_path.stat().st_size == 0:
        return False
    conn = sqlite3.connect(str(db_path), timeout=5.0)
    try:
        count = conn.execute("SELECT COUNT(*) FROM metrics").fetchone()[0]
        return count > 0
    except Exception:
        return False
    finally:
        conn.close()


def upload_project_to_bucket_for_static(project: str, bucket_id: str) -> None:
    if not _local_db_has_data(project):
        _download_db_from_bucket(project, bucket_id)

    with tempfile.TemporaryDirectory() as tmp_dir:
        output_dir = Path(tmp_dir)
        SQLiteStorage.export_for_static_space(project, output_dir)

        media_dir = MEDIA_DIR / project
        if media_dir.exists():
            shutil.copytree(media_dir, output_dir / "media")

        files_to_add = []
        for f in output_dir.rglob("*"):
            if f.is_file():
                rel = f.relative_to(output_dir)
                files_to_add.append((str(f), str(rel)))

        huggingface_hub.batch_bucket_files(bucket_id, add=files_to_add)
