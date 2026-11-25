"""Record which code produced a run, and check it later.

`trackio.init` stores three reserved config entries:

- `_Code`: the entry script's file name, SHA-256 and size, the SHA-256 of every
  local module it imported from its own directory (`files`), plus the git commit
  and dirty flag when the script lives in a git checkout.
- `_Environment`: Python version, platform, and versions of common ML packages.
- `_Job`: the Hugging Face Job running the script, when there is one.

`verify_project_code` compares those records against local files and, for runs on
Hugging Face Jobs, against the files the Job actually executed, which Jobs keeps in
the owner's `jobs-artifacts` bucket.
"""

from __future__ import annotations

import hashlib
import os
import platform
import subprocess
import sys
import tempfile
from importlib import metadata
from pathlib import Path
from typing import Any

import huggingface_hub

TRACKED_PACKAGES = (
    "trackio",
    "torch",
    "numpy",
    "transformers",
    "datasets",
    "accelerate",
    "jax",
    "tensorflow",
)

JOBS_ARTIFACTS_MOUNT = "/data"
MAX_LOCAL_MODULES = 50


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def entry_script() -> Path | None:
    main = sys.modules.get("__main__")
    candidates = [getattr(main, "__file__", None), sys.argv[0] if sys.argv else None]
    for candidate in candidates:
        if candidate and candidate not in ("-c", "-m") and Path(candidate).is_file():
            return Path(candidate).resolve()
    return None


def _git(path: Path, *args: str) -> str | None:
    try:
        out = subprocess.run(
            ["git", *args],
            cwd=path.parent,
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip()


def local_modules(script: Path) -> dict[str, str]:
    """SHA-256 of each imported module that lives in the script's directory."""
    root = script.parent
    found: dict[str, str] = {}
    for module in list(sys.modules.values()):
        path = getattr(module, "__file__", None)
        if not isinstance(path, str) or not path.endswith(".py"):
            continue
        if not os.path.isabs(path):
            continue
        resolved = Path(path).resolve()
        if resolved == script or "site-packages" in resolved.parts:
            continue
        try:
            rel = resolved.relative_to(root)
            found[rel.as_posix()] = sha256_file(resolved)
        except (ValueError, OSError):
            continue
        if len(found) >= MAX_LOCAL_MODULES:
            break
    return dict(sorted(found.items()))


def code_provenance(script: Path | None = None) -> dict[str, Any] | None:
    script = script or entry_script()
    if script is None:
        return None
    record: dict[str, Any] = {
        "path": script.name,
        "sha256": sha256_file(script),
        "bytes": script.stat().st_size,
    }
    files = local_modules(script)
    if files:
        record["files"] = files
    commit = _git(script, "rev-parse", "HEAD")
    if commit:
        record["git_commit"] = commit
        status = _git(script, "status", "--porcelain", "--", script.name)
        record["git_dirty"] = bool(status)
    return record


def environment_provenance() -> dict[str, Any]:
    packages = {}
    for name in TRACKED_PACKAGES:
        try:
            packages[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            continue
    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "packages": packages,
    }


def job_provenance() -> dict[str, Any] | None:
    job_id = os.environ.get("HF_JOB_ID")
    if not job_id:
        return None
    owner = os.environ.get("HF_JOB_OWNER")
    record = {
        "id": job_id,
        "owner": owner,
        "flavor": os.environ.get("HF_JOB_FLAVOR"),
        "image": os.environ.get("HF_JOB_IMAGE"),
    }
    if owner:
        record["url"] = f"https://huggingface.co/jobs/{owner}/{job_id}"
    return {k: v for k, v in record.items() if v is not None}


def collect() -> dict[str, Any]:
    if os.environ.get("TRACKIO_RECORD_PROVENANCE", "1") == "0":
        return {}
    out: dict[str, Any] = {}
    try:
        code = code_provenance()
    except OSError:
        code = None
    if code:
        out["_Code"] = code
    out["_Environment"] = environment_provenance()
    job = job_provenance()
    if job:
        out["_Job"] = job
    return out


def recorded_files(code: dict) -> dict[str, str]:
    """Every file a run recorded: the entry script and its local modules."""
    files = dict(code.get("files") or {})
    if code.get("path") and code.get("sha256"):
        files[code["path"]] = code["sha256"]
    return files


def _executed_hashes(job: dict, names: list[str], token: str | None) -> dict:
    info = huggingface_hub.inspect_job(
        job_id=job["id"], namespace=job.get("owner"), token=token
    )
    result: dict[str, Any] = {"job_status": info.status.stage, "executed": {}}
    volume = next(
        (
            v
            for v in info.volumes or []
            if getattr(v, "mount_path", None) == JOBS_ARTIFACTS_MOUNT
        ),
        None,
    )
    if volume is None:
        result["detail"] = "job has no staged files (it ran a remote command or URL)"
        return result
    prefix = f"{volume.path}/" if volume.path else ""
    with tempfile.TemporaryDirectory() as tmp:
        targets = [
            (prefix + name, Path(tmp) / name.replace("/", "__")) for name in names
        ]
        huggingface_hub.download_bucket_files(
            volume.source,
            [(remote, str(local)) for remote, local in targets],
            raise_on_missing_files=False,
            token=token,
        )
        for name, (_, local) in zip(names, targets):
            result["executed"][name] = sha256_file(local) if local.exists() else None
    result["executed_source"] = f"hf://buckets/{volume.source}/{volume.path or ''}"
    return result


def verify_project_code(
    project: str,
    configs: dict[str, dict],
    files: list[str | Path] | None = None,
    check_jobs: bool = True,
    token: str | None = None,
) -> list[dict[str, Any]]:
    """Return one verification record per run in `configs` (run -> config).

    Each local file in `files` is matched by name against what the run recorded,
    and for runs on Hugging Face Jobs every recorded file is matched against the
    copy the Job executed.
    """
    local = {Path(f).name: sha256_file(f) for f in files or []}
    job_cache: dict[str, dict] = {}
    rows = []
    for run, config in configs.items():
        code = config.get("_Code") or {}
        job = config.get("_Job") or {}
        recorded = recorded_files(code)
        row: dict[str, Any] = {
            "run": run,
            "recorded_sha256": code.get("sha256"),
            "script": code.get("path"),
            "recorded_files": recorded,
            "job_id": job.get("id"),
        }
        problems = []
        if not code:
            problems.append("no code provenance recorded")
        if local:
            mismatched = [n for n, h in local.items() if recorded.get(n) != h]
            row["matches_local"] = not mismatched
            for name in mismatched:
                if name not in recorded:
                    problems.append(f"{name} was not recorded by this run")
                else:
                    problems.append(
                        f"{name}: recorded hash differs from the local file"
                    )
        if check_jobs and job.get("id") and recorded:
            key = f"{job['id']}/" + ",".join(sorted(recorded))
            if key not in job_cache:
                try:
                    job_cache[key] = _executed_hashes(job, sorted(recorded), token)
                except Exception as e:
                    job_cache[key] = {"error": f"{type(e).__name__}: {e}"}
            executed = job_cache[key]
            row.update(executed)
            if "error" in executed:
                problems.append("could not fetch the job's executed files")
            elif executed.get("executed"):
                bad = [
                    n for n, h in recorded.items() if executed["executed"].get(n) != h
                ]
                row["matches_executed"] = not bad
                problems += [f"{n}: the job ran different code" for n in bad]
            if executed.get("job_status") not in (None, "COMPLETED"):
                problems.append(f"job status is {executed.get('job_status')}")
        row["ok"] = not problems
        row["problems"] = problems
        rows.append(row)
    return rows
