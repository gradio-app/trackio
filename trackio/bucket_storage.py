import sqlite3

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
        dest=str(TRACKIO_DIR),
        quiet=True,
    )


def upload_project_to_bucket(project: str, bucket_id: str) -> None:
    db_path = SQLiteStorage.get_project_db_path(project)
    if not db_path.exists():
        raise FileNotFoundError(f"No database found for project '{project}'")

    with sqlite3.connect(str(db_path), timeout=30.0) as conn:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    files_to_add = [(str(db_path), db_path.name)]

    media_dir = MEDIA_DIR / project
    if media_dir.exists():
        for media_file in media_dir.rglob("*"):
            if media_file.is_file():
                rel = media_file.relative_to(TRACKIO_DIR)
                files_to_add.append((str(media_file), str(rel)))

    huggingface_hub.batch_bucket_files(bucket_id, add=files_to_add)
