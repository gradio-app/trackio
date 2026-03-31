"""
Minimal repro: SQLite disk I/O error on HF Spaces with bucket mount.

Run this script locally. It will:
1. Create a bucket + Space with the bucket mounted at /data
2. The Space app writes to a SQLite DB on the mount at startup
3. Check the Space logs for "disk I/O error" or "readonly" errors

Usage:
    pip install huggingface_hub gradio
    python repro_bucket_sqlite.py
"""

import io
import random
import time

import huggingface_hub
from huggingface_hub.constants import ENDPOINT
from huggingface_hub.utils import get_session, hf_raise_for_status

SPACE_ID_PREFIX = "sqlite-bucket-repro"


def create_bucket(namespace, short_name):
    token = huggingface_hub.get_token()
    base = ENDPOINT.rstrip("/")
    url = f"{base}/api/buckets/{namespace}/{short_name}"
    r = get_session().post(
        url,
        headers={"Authorization": f"Bearer {token}"},
        json={"private": True},
        timeout=60.0,
    )
    if r.status_code == 409:
        return
    hf_raise_for_status(r)


def attach_bucket(space_id, bucket_id, mount_path="/data"):
    token = huggingface_hub.get_token()
    hf_api = huggingface_hub.HfApi(token=token)
    info = hf_api.space_info(space_id)
    existing = list(info.runtime.raw.get("volumes") or []) if info.runtime else []

    new_vol = {"type": "bucket", "source": bucket_id, "mountPath": mount_path}
    namespace, repo = space_id.split("/", 1)
    base = ENDPOINT.rstrip("/")
    url = f"{base}/api/spaces/{namespace}/{repo}/volumes"
    r = get_session().put(
        url,
        headers={"Authorization": f"Bearer {token}"},
        json={"volumes": existing + [new_vol]},
        timeout=120.0,
    )
    hf_raise_for_status(r)


APP_CODE = """\
import os
import sqlite3
import time
from pathlib import Path

import gradio as gr

DB_DIR = Path(os.environ.get("TRACKIO_DIR", "/data/trackio"))
DB_DIR.mkdir(parents=True, exist_ok=True)

def test_plain_file():
    try:
        p = DB_DIR / "test_plain.txt"
        p.write_text(f"written at {time.time()}")
        return f"OK: wrote {len(p.read_text())} bytes"
    except Exception as e:
        return f"FAILED: {type(e).__name__}: {e}"


def test_fsync():
    try:
        p = DB_DIR / "test_fsync.txt"
        fd = os.open(str(p), os.O_WRONLY | os.O_CREAT | os.O_TRUNC)
        os.write(fd, b"hello fsync")
        os.fsync(fd)
        os.close(fd)
        return "OK"
    except Exception as e:
        return f"FAILED: {type(e).__name__}: {e}"


def test_ftruncate():
    try:
        p = DB_DIR / "test_ftrunc.bin"
        fd = os.open(str(p), os.O_RDWR | os.O_CREAT | os.O_TRUNC)
        os.write(fd, b"x" * 100)
        os.ftruncate(fd, 4096)
        size = os.fstat(fd).st_size
        os.close(fd)
        return f"OK: size={size}"
    except Exception as e:
        return f"FAILED: {type(e).__name__}: {e}"


def test_mmap():
    import mmap
    try:
        p = DB_DIR / "test_mmap.bin"
        with open(p, "wb") as f:
            f.write(b"\\x00" * 4096)
        fd = os.open(str(p), os.O_RDWR)
        m = mmap.mmap(fd, 4096)
        m[0:5] = b"hello"
        m.flush()
        m.close()
        os.close(fd)
        return "OK"
    except Exception as e:
        return f"FAILED: {type(e).__name__}: {e}"


def test_fcntl_lock():
    import fcntl, struct
    try:
        p = DB_DIR / "test_lock.bin"
        p.write_bytes(b"\\x00" * 512)
        fd = os.open(str(p), os.O_RDWR)
        lockdata = struct.pack("hhllhh", fcntl.F_WRLCK, 0, 0, 0, 0, 0)
        fcntl.fcntl(fd, fcntl.F_SETLK, lockdata)
        os.close(fd)
        return "OK"
    except Exception as e:
        return f"FAILED: {type(e).__name__}: {e}"


def test_sqlite(name, pragmas, uri_suffix=""):
    try:
        db_file = DB_DIR / f"test_{name}.db"
        if uri_suffix:
            conn_str = f"file:{db_file}{uri_suffix}"
            conn = sqlite3.connect(conn_str, uri=True, timeout=10.0)
        else:
            conn = sqlite3.connect(str(db_file), timeout=10.0)
        for p in pragmas:
            conn.execute(p)
        conn.execute("CREATE TABLE IF NOT EXISTS t (id INTEGER PRIMARY KEY, v TEXT)")
        conn.execute("INSERT INTO t (v) VALUES (?)", (f"at {time.time()}",))
        conn.commit()
        count = conn.execute("SELECT count(*) FROM t").fetchone()[0]
        conn.close()
        return f"OK: {count} rows"
    except Exception as e:
        return f"FAILED: {type(e).__name__}: {e}"


def test_sqlite_from_tmp():
    import shutil, tempfile
    try:
        fd, tmp = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        conn = sqlite3.connect(tmp)
        conn.execute("PRAGMA journal_mode = DELETE")
        conn.execute("CREATE TABLE IF NOT EXISTS t (id INTEGER PRIMARY KEY, v TEXT)")
        conn.execute("INSERT INTO t (v) VALUES ('from_tmp')")
        conn.commit()
        conn.close()
        dst = str(DB_DIR / "test_from_tmp.db")
        shutil.copy2(tmp, dst)
        os.unlink(tmp)
        conn2 = sqlite3.connect(dst, timeout=10.0)
        count = conn2.execute("SELECT count(*) FROM t").fetchone()[0]
        conn2.close()
        return f"OK: copied and read {count} rows"
    except Exception as e:
        return f"FAILED: {type(e).__name__}: {e}"


def test_sqlite_from_tmp_then_write():
    import shutil, tempfile
    try:
        fd, tmp = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        conn = sqlite3.connect(tmp)
        conn.execute("PRAGMA journal_mode = MEMORY")
        conn.execute("CREATE TABLE IF NOT EXISTS t (id INTEGER PRIMARY KEY, v TEXT)")
        conn.commit()
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.close()
        dst = DB_DIR / "test_from_tmp_write.db"
        shutil.copy2(tmp, str(dst))
        os.unlink(tmp)
        conn2 = sqlite3.connect(f"file:{dst}?nolock=1", uri=True, timeout=10.0)
        conn2.execute("PRAGMA journal_mode = MEMORY")
        conn2.execute("PRAGMA synchronous = OFF")
        conn2.execute("PRAGMA mmap_size = 0")
        conn2.execute("INSERT INTO t (v) VALUES ('written on mount')")
        conn2.commit()
        count = conn2.execute("SELECT count(*) FROM t").fetchone()[0]
        conn2.close()
        return f"OK: wrote on mount, {count} rows"
    except Exception as e:
        return f"FAILED: {type(e).__name__}: {e}"


TESTS = [
    ("1. plain file write", test_plain_file),
    ("2. fsync", test_fsync),
    ("3. ftruncate", test_ftruncate),
    ("4. mmap read/write", test_mmap),
    ("5. fcntl F_SETLK", test_fcntl_lock),
    ("6. sqlite default", lambda: test_sqlite("default", [])),
    ("7. sqlite journal=MEMORY sync=OFF", lambda: test_sqlite("mem_syncoff", ["PRAGMA journal_mode=MEMORY", "PRAGMA synchronous=OFF"])),
    ("8. sqlite journal=OFF sync=OFF", lambda: test_sqlite("off_off", ["PRAGMA journal_mode=OFF", "PRAGMA synchronous=OFF"])),
    ("9. sqlite nolock=1 journal=OFF sync=OFF", lambda: test_sqlite("nolock_off", ["PRAGMA journal_mode=OFF", "PRAGMA synchronous=OFF"], "?nolock=1")),
    ("10. sqlite nolock=1 journal=MEMORY sync=OFF", lambda: test_sqlite("nolock_mem", ["PRAGMA journal_mode=MEMORY", "PRAGMA synchronous=OFF"], "?nolock=1")),
    ("11. sqlite journal=PERSIST sync=OFF", lambda: test_sqlite("persist", ["PRAGMA journal_mode=PERSIST", "PRAGMA synchronous=OFF"])),
    ("12. sqlite nolock=1 journal=OFF sync=OFF mmap=0", lambda: test_sqlite("nolock_nommap", ["PRAGMA journal_mode=OFF", "PRAGMA synchronous=OFF", "PRAGMA mmap_size=0"], "?nolock=1")),
    ("13. sqlite nolock=1 journal=MEMORY sync=OFF mmap=0", lambda: test_sqlite("nolock_mem_nommap", ["PRAGMA journal_mode=MEMORY", "PRAGMA synchronous=OFF", "PRAGMA mmap_size=0"], "?nolock=1")),
    ("14. sqlite nolock=1 journal=MEMORY sync=NORMAL mmap=0", lambda: test_sqlite("nolock_mem_nommap_syncnorm", ["PRAGMA journal_mode=MEMORY", "PRAGMA synchronous=NORMAL", "PRAGMA mmap_size=0"], "?nolock=1")),
    ("15. sqlite nolock=1 journal=DELETE sync=NORMAL mmap=0", lambda: test_sqlite("nolock_del_nommap", ["PRAGMA journal_mode=DELETE", "PRAGMA synchronous=NORMAL", "PRAGMA mmap_size=0"], "?nolock=1")),
    ("16. sqlite created in /tmp, copied to mount (read only)", test_sqlite_from_tmp),
    ("17. sqlite created in /tmp, copied to mount, then INSERT on mount", test_sqlite_from_tmp_then_write),
]

RESULTS = []
print("=" * 60, flush=True)
print("SQLITE BUCKET MOUNT DIAGNOSTICS", flush=True)
print("=" * 60, flush=True)
for name, fn in TESTS:
    result = fn()
    line = f"{name}: {result}"
    RESULTS.append(line)
    print(line, flush=True)
print("=" * 60, flush=True)

with gr.Blocks() as demo:
    gr.Markdown("## SQLite Bucket Mount Config Test")
    gr.Textbox(
        value="\\n".join(RESULTS),
        label="Results",
        lines=len(RESULTS) + 2,
    )

if __name__ == "__main__":
    demo.launch()
"""


def main():
    run_id = random.randint(100000, 999999)
    namespace = huggingface_hub.whoami()["name"]
    space_name = f"{SPACE_ID_PREFIX}-{run_id}"
    space_id = f"{namespace}/{space_name}"
    bucket_short = f"{space_name}-bucket"
    bucket_id = f"{namespace}/{bucket_short}"

    space_url = f"https://huggingface.co/spaces/{space_id}"
    runtime_url = f"https://{namespace}-{space_name}.hf.space/"
    print(f"Space URL: {space_url}")
    print(f"Runtime URL: {runtime_url}")
    print()
    print(f"Creating bucket: {bucket_id}")
    create_bucket(namespace, bucket_short)

    print(f"Creating space: {space_id}")
    hf_api = huggingface_hub.HfApi()
    hf_api.create_repo(
        space_id,
        private=True,
        space_sdk="gradio",
        repo_type="space",
        exist_ok=True,
    )

    print(f"Attaching bucket {bucket_id} at /data")
    attach_bucket(space_id, bucket_id, mount_path="/data")
    huggingface_hub.add_space_variable(space_id, "TRACKIO_DIR", "/data/trackio")

    print("Uploading app.py")
    hf_api.upload_file(
        path_or_fileobj=io.BytesIO(APP_CODE.encode("utf-8")),
        path_in_repo="app.py",
        repo_id=space_id,
        repo_type="space",
    )

    print("Uploading requirements.txt")
    hf_api.upload_file(
        path_or_fileobj=io.BytesIO(b"gradio\n"),
        path_in_repo="requirements.txt",
        repo_id=space_id,
        repo_type="space",
    )

    print("Waiting for Space to start...")
    for _ in range(60):
        try:
            info = hf_api.space_info(space_id)
            if info.runtime and info.runtime.stage == "RUNNING":
                break
        except Exception:
            pass
        time.sleep(5)
    else:
        print("Space did not start in time")
        return

    print(f"\nSpace is running!")
    print(f"  URL: https://huggingface.co/spaces/{space_id}")
    print(f"  Logs: check the Space logs for 'FAILED' or 'disk I/O error'")
    print(f"\nFetching runtime logs...")

    import json

    import requests

    token = huggingface_hub.get_token()
    url = f"https://huggingface.co/api/spaces/{space_id}/logs/run"
    try:
        r = requests.get(
            url,
            headers={"Authorization": f"Bearer {token}"},
            stream=True,
            timeout=(5, 15),
        )
        for line in r.iter_lines():
            if not line:
                continue
            decoded = line.decode("utf-8", errors="replace")
            if decoded.startswith("data:"):
                try:
                    data = json.loads(decoded[5:])
                    text = data.get("data", "")
                    if text.strip():
                        print(f"  {text}")
                except json.JSONDecodeError:
                    pass
    except (requests.exceptions.ReadTimeout, requests.exceptions.ConnectionError):
        pass

    print(f"\nDone. Space: https://huggingface.co/spaces/{space_id}")


if __name__ == "__main__":
    main()
