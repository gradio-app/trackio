from __future__ import annotations

from typing import Any

import huggingface_hub
from huggingface_hub.constants import ENDPOINT
from huggingface_hub.utils import get_session, hf_raise_for_status


class SpaceBucketConflictError(RuntimeError):
    pass


def _token(token: str | None) -> str:
    t = token if token is not None else huggingface_hub.utils.get_token()
    if not t:
        raise ValueError(
            "A Hugging Face token is required. Set HF_TOKEN or run huggingface_hub.login()."
        )
    return t


def _space_repo_api_url(space_id: str) -> str:
    if "/" not in space_id:
        raise ValueError(f"Invalid space_id {space_id!r}; expected 'namespace/repo'.")
    namespace, repo = space_id.split("/", 1)
    base = ENDPOINT.rstrip("/")
    return f"{base}/api/spaces/{namespace}/{repo}"


def get_space_volumes(
    space_id: str, *, token: str | None = None
) -> list[dict[str, Any]]:
    t = _token(token)
    hf_api = huggingface_hub.HfApi(token=t)
    info = hf_api.space_info(space_id)
    if not info.runtime:
        return []
    raw = info.runtime.raw
    vols = raw.get("volumes")
    return list(vols) if vols else []


def set_space_volumes(
    space_id: str,
    volumes: list[dict[str, Any]],
    *,
    token: str | None = None,
) -> None:
    t = _token(token)
    url = f"{_space_repo_api_url(space_id)}/volumes"
    headers = {"Authorization": f"Bearer {t}"}
    r = get_session().put(
        url,
        headers=headers,
        json={"volumes": volumes},
        timeout=120.0,
    )
    hf_raise_for_status(r)


def attach_bucket_volume(
    space_id: str,
    bucket_id: str,
    *,
    mount_path: str = "/data",
    read_only: bool = False,
    token: str | None = None,
) -> bool:
    if not mount_path.startswith("/"):
        raise ValueError("mount_path must be an absolute path (e.g. '/data').")
    existing = get_space_volumes(space_id, token=token)
    bucket_sources = [
        v["source"] for v in existing if v.get("type") == "bucket" and "source" in v
    ]
    if bucket_sources:
        if bucket_id not in bucket_sources:
            raise SpaceBucketConflictError(
                f"Space {space_id!r} already mounts bucket volume(s) {bucket_sources!r}; "
                f"cannot attach {bucket_id!r}. Remove the existing mount in Space settings or use that bucket."
            )
        for v in existing:
            if v.get("type") != "bucket" or v.get("source") != bucket_id:
                continue
            same_mount = v.get("mountPath") == mount_path
            existing_ro = bool(v.get("readOnly"))
            same_ro = existing_ro == read_only
            if same_mount and same_ro:
                return False
        raise SpaceBucketConflictError(
            f"Bucket {bucket_id!r} is already mounted with different mountPath/readOnly; "
            f"update in Space settings instead."
        )
    new_vol: dict[str, Any] = {
        "type": "bucket",
        "source": bucket_id,
        "mountPath": mount_path,
    }
    if read_only:
        new_vol["readOnly"] = True
    set_space_volumes(space_id, existing + [new_vol], token=token)
    return True


def resolve_bucket_id_for_deploy(
    space_id: str,
    *,
    bucket_id: str | None,
    create_bucket_if_missing: bool,
    bucket_short_name: str | None,
) -> str | None:
    if bucket_id is not None:
        return bucket_id
    if not create_bucket_if_missing:
        return None
    namespace, repo = space_id.split("/", 1)
    short = bucket_short_name if bucket_short_name else f"{repo}-storage"
    if "/" in short:
        short = short.split("/")[-1]
    return f"{namespace}/{short}"
