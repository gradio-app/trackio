from __future__ import annotations

import huggingface_hub
from huggingface_hub import Volume


def attach_bucket_volume(
    space_id: str,
    bucket_id: str,
    *,
    mount_path: str = "/data",
    read_only: bool = False,
) -> bool:
    if not mount_path.startswith("/"):
        raise ValueError("mount_path must be an absolute path (e.g. '/data').")

    hf_api = huggingface_hub.HfApi()
    runtime = hf_api.get_space_runtime(space_id)
    existing = list(runtime.volumes) if runtime.volumes else []

    for v in existing:
        if v.type == "bucket" and v.source == bucket_id:
            if v.mount_path == mount_path and bool(v.read_only) == read_only:
                return False

    new_vol = Volume(
        type="bucket",
        source=bucket_id,
        mount_path=mount_path,
        read_only=read_only or None,
    )

    non_bucket = [
        v for v in existing if not (v.type == "bucket" and v.source == bucket_id)
    ]
    hf_api.set_space_volumes(space_id, non_bucket + [new_vol])
    return True
