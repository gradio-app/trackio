import importlib
import os
import platform
import subprocess
import sys
import urllib.request

_DEFAULT_MOUNT = "/data/trackio"
_BIN_DIR = "/tmp/trackio-hf-mount-bin"


def _platform_release_asset():
    if sys.platform != "linux":
        raise OSError(f"hf-mount on Spaces requires Linux, got {sys.platform}")
    m = platform.machine().lower()
    if m in ("x86_64", "amd64"):
        return "x86_64", "linux"
    if m in ("aarch64", "arm64"):
        return "aarch64", "linux"
    raise OSError(f"Unsupported machine for hf-mount: {m}")


def _download_hf_mount_binaries():
    arch, plat = _platform_release_asset()
    base = "https://github.com/huggingface/hf-mount/releases/latest/download"
    os.makedirs(_BIN_DIR, exist_ok=True)
    for name in ("hf-mount", "hf-mount-nfs", "hf-mount-fuse"):
        binary = f"{name}-{arch}-{plat}"
        url = f"{base}/{binary}"
        dest = os.path.join(_BIN_DIR, name)
        with urllib.request.urlopen(url) as response:
            with open(dest, "wb") as out:
                out.write(response.read())
        os.chmod(dest, 0o755)


def start_hf_mount_for_trackio_bucket():
    if os.environ.get("SYSTEM") != "spaces":
        return
    bucket_id = os.environ.get("TRACKIO_BUCKET_ID")
    if not bucket_id:
        return
    mount_path = os.environ.get("TRACKIO_DIR", _DEFAULT_MOUNT)
    parent = os.path.dirname(mount_path.rstrip("/")) or "/"
    os.makedirs(parent, exist_ok=True)
    os.makedirs(mount_path, exist_ok=True)
    hf_mount = os.path.join(_BIN_DIR, "hf-mount")
    if not os.path.isfile(hf_mount):
        _download_hf_mount_binaries()
    env = {**os.environ, "PATH": _BIN_DIR + os.pathsep + os.environ.get("PATH", "")}
    subprocess.run(
        [hf_mount, "start", "bucket", bucket_id, mount_path],
        check=True,
        env=env,
        timeout=600,
    )


start_hf_mount_for_trackio_bucket()

trackio = importlib.import_module("trackio")
trackio.show()
