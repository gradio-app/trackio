import atexit
import logging
import sqlite3
import threading
import time
from concurrent.futures import Future

import huggingface_hub
from huggingface_hub import HfApi, sync_bucket

from trackio.sqlite_storage import SQLiteStorage
from trackio.utils import MEDIA_DIR, TRACKIO_DIR

logger = logging.getLogger(__name__)

DB_EXT = ".db"


def create_bucket_if_not_exists(bucket_id: str, private: bool | None = None) -> None:
    huggingface_hub.create_bucket(bucket_id, private=private or False, exist_ok=True)


def download_bucket_to_trackio_dir(bucket_id: str) -> None:
    TRACKIO_DIR.mkdir(parents=True, exist_ok=True)
    sync_bucket(source=f"hf://buckets/{bucket_id}", dest=str(TRACKIO_DIR))


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


def upload_all_projects_to_bucket(bucket_id: str) -> None:
    if not TRACKIO_DIR.exists():
        return
    for db_file in TRACKIO_DIR.glob(f"*{DB_EXT}"):
        project = db_file.stem
        try:
            upload_project_to_bucket(project, bucket_id)
        except FileNotFoundError:
            continue


class BucketSyncScheduler:
    def __init__(self, bucket_id: str, every: float = 5.0) -> None:
        self.bucket_id = bucket_id
        self.every = every
        self.lock = threading.Lock()
        self._api = HfApi(token=huggingface_hub.utils.get_token())
        self._stopped = False
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        atexit.register(self._atexit_upload)

    def _run(self) -> None:
        while not self._stopped:
            time.sleep(self.every * 60)
            if self._stopped:
                break
            try:
                self._push()
            except Exception as e:
                logger.error("Bucket background upload failed: %s", e)

    def _push(self) -> None:
        with self.lock:
            upload_all_projects_to_bucket(self.bucket_id)

    def _atexit_upload(self) -> None:
        if self._stopped:
            return
        try:
            self._push()
        except Exception as e:
            logger.error("Bucket exit upload failed: %s", e)

    def trigger(self) -> Future:
        return self._api.run_as_future(self._push)

    def stop(self) -> None:
        self._stopped = True
