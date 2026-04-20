"""The main API layer for the Trackio UI."""

import base64
import logging
import os
import re
import secrets
import shutil
import sqlite3
import threading
import time
import warnings
from collections import deque
from functools import lru_cache
from typing import Any
from urllib.parse import urlencode

import httpx
import huggingface_hub as hf
from starlette.requests import Request
from starlette.responses import RedirectResponse
from starlette.routing import Route

import trackio.utils as utils
from trackio.asgi_app import (
    cleanup_uploaded_temp_file,
    consume_uploaded_temp_file,
    create_trackio_starlette_app,
)
from trackio.exceptions import TrackioAPIError
from trackio.media import get_project_media_path
from trackio.sqlite_storage import SQLiteStorage
from trackio.typehints import AlertEntry, LogEntry, SystemLogEntry, UploadEntry
from trackio.utils import on_spaces

HfApi = hf.HfApi()

logger = logging.getLogger("trackio")

_write_queue: deque[tuple[str, Any]] = deque()
_flush_thread: threading.Thread | None = None
_flush_lock = threading.Lock()
_FLUSH_INTERVAL = 2.0
_MAX_RETRIES = 30

_LOGS_BATCH_MAX_RUNS = 64
_LOGS_BATCH_MAX_POINTS = 10_000


def _normalize_logs_batch_runs(runs: Any) -> list[dict[str, Any]]:
    if not isinstance(runs, list):
        raise TrackioAPIError("runs must be a list")
    if len(runs) > _LOGS_BATCH_MAX_RUNS:
        raise TrackioAPIError(
            f"runs cannot contain more than {_LOGS_BATCH_MAX_RUNS} entries"
        )
    out: list[dict[str, Any]] = []
    for i, r in enumerate(runs):
        if not isinstance(r, dict):
            raise TrackioAPIError(f"runs[{i}] must be an object")
        out.append({"run": r.get("run"), "run_id": r.get("run_id")})
    return out


def _normalize_logs_batch_max_points(max_points: Any) -> int | None:
    if max_points is None:
        return 1500
    if isinstance(max_points, bool):
        raise TrackioAPIError("max_points must be a number or null")
    if isinstance(max_points, float):
        if not max_points.is_integer():
            raise TrackioAPIError("max_points must be a whole number")
        max_points = int(max_points)
    if not isinstance(max_points, int):
        raise TrackioAPIError("max_points must be an integer or null")
    if max_points < 1:
        return 1500
    return min(max_points, _LOGS_BATCH_MAX_POINTS)


def _enqueue_write(kind: str, payload: Any) -> None:
    _write_queue.append((kind, payload))
    _ensure_flush_thread()


def _ensure_flush_thread() -> None:
    global _flush_thread
    with _flush_lock:
        if _flush_thread is not None and _flush_thread.is_alive():
            return
        _flush_thread = threading.Thread(target=_flush_loop, daemon=True)
        _flush_thread.start()


def _flush_loop() -> None:
    retries = 0
    while _write_queue and retries < _MAX_RETRIES:
        kind, payload = _write_queue[0]
        try:
            if kind == "bulk_log":
                SQLiteStorage.bulk_log(**payload)
            elif kind == "bulk_log_system":
                SQLiteStorage.bulk_log_system(**payload)
            elif kind == "bulk_alert":
                SQLiteStorage.bulk_alert(**payload)
            _write_queue.popleft()
            retries = 0
        except sqlite3.OperationalError as e:
            msg = str(e).lower()
            if "disk i/o error" in msg or "readonly" in msg:
                retries += 1
                logger.warning(
                    "write queue: flush failed (%s), retry %d/%d",
                    e,
                    retries,
                    _MAX_RETRIES,
                )
                time.sleep(min(_FLUSH_INTERVAL * retries, 15.0))
            else:
                logger.error("write queue: non-retryable error (%s), dropping entry", e)
                _write_queue.popleft()
                retries = 0
    if _write_queue:
        logger.error(
            "write queue: giving up after %d retries, %d entries dropped",
            _MAX_RETRIES,
            len(_write_queue),
        )
        _write_queue.clear()


write_token = secrets.token_urlsafe(32)

OAUTH_CALLBACK_PATH = "/login/callback"
OAUTH_START_PATH = "/oauth/hf/start"


def _hf_access_token(request: Request) -> str | None:
    session_id = None
    try:
        session_id = request.headers.get("x-trackio-oauth-session")
    except (AttributeError, TypeError):
        pass
    if session_id and session_id in _oauth_sessions:
        token, created = _oauth_sessions[session_id]
        if time.monotonic() - created <= _OAUTH_SESSION_TTL:
            return token
        del _oauth_sessions[session_id]
    cookie_header = ""
    try:
        cookie_header = request.headers.get("cookie", "")
    except (AttributeError, TypeError):
        pass
    if cookie_header:
        for cookie in cookie_header.split(";"):
            parts = cookie.strip().split("=", 1)
            if len(parts) == 2 and parts[0] == "trackio_hf_access_token":
                return parts[1] or None
    return None


def _authorization_bearer_token(request: Request) -> str | None:
    auth = request.headers.get("authorization") or request.headers.get("Authorization")
    if not auth:
        return None
    parts = auth.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    token = parts[1].strip()
    return token or None


def _oauth_redirect_uri(request: Request) -> str:
    space_host = os.getenv("SPACE_HOST")
    if space_host:
        space_host = space_host.split(",")[0]
        return f"https://{space_host}{OAUTH_CALLBACK_PATH}"
    return str(request.base_url).rstrip("/") + OAUTH_CALLBACK_PATH


_OAUTH_STATE_TTL = 86400
_OAUTH_SESSION_TTL = 86400 * 30
_pending_oauth_states: dict[str, float] = {}
_oauth_sessions: dict[str, tuple[str, float]] = {}


def _evict_expired_oauth():
    now = time.monotonic()
    expired_states = [
        k for k, t in _pending_oauth_states.items() if now - t > _OAUTH_STATE_TTL
    ]
    for k in expired_states:
        del _pending_oauth_states[k]
    expired_sessions = [
        k for k, (_, t) in _oauth_sessions.items() if now - t > _OAUTH_SESSION_TTL
    ]
    for k in expired_sessions:
        del _oauth_sessions[k]


def oauth_hf_start(request: Request):
    client_id = os.getenv("OAUTH_CLIENT_ID")
    if not client_id:
        return RedirectResponse(url="/", status_code=302)
    _evict_expired_oauth()
    state = secrets.token_urlsafe(32)
    _pending_oauth_states[state] = time.monotonic()
    redirect_uri = _oauth_redirect_uri(request)
    scope = os.getenv("OAUTH_SCOPES", "openid profile").strip()
    url = "https://huggingface.co/oauth/authorize?" + urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": scope,
            "state": state,
        }
    )
    return RedirectResponse(url=url, status_code=302)


def oauth_hf_callback(request: Request):
    client_id = os.getenv("OAUTH_CLIENT_ID")
    client_secret = os.getenv("OAUTH_CLIENT_SECRET")
    err = "/?oauth_error=1"
    if not client_id or not client_secret:
        return RedirectResponse(url=err, status_code=302)
    got_state = request.query_params.get("state")
    code = request.query_params.get("code")
    if not got_state or got_state not in _pending_oauth_states or not code:
        return RedirectResponse(url=err, status_code=302)
    state_created = _pending_oauth_states.pop(got_state)
    if time.monotonic() - state_created > _OAUTH_STATE_TTL:
        return RedirectResponse(url=err, status_code=302)
    redirect_uri = _oauth_redirect_uri(request)
    auth_b64 = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    try:
        with httpx.Client() as client:
            token_resp = client.post(
                "https://huggingface.co/oauth/token",
                headers={"Authorization": f"Basic {auth_b64}"},
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": redirect_uri,
                    "client_id": client_id,
                },
            )
            token_resp.raise_for_status()
        access_token = token_resp.json()["access_token"]
    except Exception:
        return RedirectResponse(url=err, status_code=302)
    session_id = secrets.token_urlsafe(32)
    _oauth_sessions[session_id] = (access_token, time.monotonic())
    _on_spaces = on_spaces()
    resp = RedirectResponse(url=f"/?oauth_session={session_id}", status_code=302)
    resp.set_cookie(
        key="trackio_hf_access_token",
        value=access_token,
        httponly=True,
        samesite="none" if _on_spaces else "lax",
        max_age=86400 * 30,
        path="/",
        secure=_on_spaces,
    )
    return resp


def oauth_logout(request: Request):
    _on_spaces = on_spaces()
    resp = RedirectResponse(url="/", status_code=302)
    resp.delete_cookie(
        "trackio_hf_access_token",
        path="/",
        samesite="none" if _on_spaces else "lax",
        secure=_on_spaces,
    )
    return resp


@lru_cache(maxsize=32)
def check_hf_token_has_write_access(hf_token: str | None) -> None:
    """
    Checks if the provided hf_token has write access to the space. If it does not
    have write access, a PermissionError is raised. Otherwise, the function returns None.

    The function is cached in two separate caches to avoid unnecessary API calls to /whoami-v2 which is heavily rate-limited:
    - A cache of the whoami response for the hf_token using .whoami(token=hf_token, cache=True).
    - This entire function is cached using @lru_cache(maxsize=32).
    """
    if on_spaces():
        if hf_token is None:
            raise PermissionError(
                "Expected a HF_TOKEN to be provided when logging to a Space"
            )
        space_token = os.getenv("HF_TOKEN")
        if space_token and hf_token == space_token:
            # If the HF_TOKEN is the same as the space token, we can assume that the user has write access.
            # This avoids unnecessary API calls to /whoami-v2 which is heavily rate-limited.
            return
        who = HfApi.whoami(token=hf_token, cache=True)
        owner_name = os.getenv("SPACE_AUTHOR_NAME")
        repo_name = os.getenv("SPACE_REPO_NAME")
        orgs = [o["name"] for o in who["orgs"]]
        if owner_name != who["name"] and owner_name not in orgs:
            raise PermissionError(
                "Expected the provided hf_token to be the user owner of the space, or be a member of the org owner of the space"
            )
        access_token = who["auth"]["accessToken"]
        if access_token["role"] == "fineGrained":
            matched = False
            for item in access_token["fineGrained"]["scoped"]:
                if (
                    item["entity"]["type"] == "space"
                    and item["entity"]["name"] == f"{owner_name}/{repo_name}"
                    and "repo.write" in item["permissions"]
                ):
                    matched = True
                    break
                if (
                    (
                        item["entity"]["type"] == "user"
                        or item["entity"]["type"] == "org"
                    )
                    and item["entity"]["name"] == owner_name
                    and "repo.write" in item["permissions"]
                ):
                    matched = True
                    break
            if not matched:
                raise PermissionError(
                    "Expected the provided hf_token with fine grained permissions to provide write access to the space"
                )
        elif access_token["role"] != "write":
            raise PermissionError(
                "Expected the provided hf_token to provide write permissions"
            )


_oauth_write_cache: dict[str, tuple[bool, float]] = {}
_OAUTH_WRITE_CACHE_TTL = 300


def check_oauth_token_has_write_access(oauth_token: str | None) -> None:
    if not on_spaces():
        return
    if oauth_token is None:
        raise PermissionError(
            "Expected an oauth to be provided when logging to a Space"
        )
    now = time.monotonic()
    cached = _oauth_write_cache.get(oauth_token)
    if cached is not None:
        allowed, ts = cached
        if now - ts < _OAUTH_WRITE_CACHE_TTL:
            if not allowed:
                raise PermissionError(
                    "Expected the oauth token to be the user owner of the space, or be a member of the org owner of the space"
                )
            return
    who = HfApi.whoami(oauth_token, cache=True)
    user_name = who["name"]
    owner_name = os.getenv("SPACE_AUTHOR_NAME")
    if user_name == owner_name:
        _oauth_write_cache[oauth_token] = (True, now)
        return
    for org in who["orgs"]:
        if org["name"] == owner_name and org["roleInOrg"] == "write":
            _oauth_write_cache[oauth_token] = (True, now)
            return
    _oauth_write_cache[oauth_token] = (False, now)
    raise PermissionError(
        "Expected the oauth token to be the user owner of the space, or be a member of the org owner of the space"
    )


def check_write_access(request: Request, token: str) -> bool:
    expected_token = token or ""
    hdr = request.headers.get("x-trackio-write-token")
    if hdr is not None:
        return secrets.compare_digest(hdr, expected_token)
    cookies = request.headers.get("cookie", "")
    if cookies:
        for cookie in cookies.split(";"):
            parts = cookie.strip().split("=", 1)
            if len(parts) == 2 and parts[0] == "trackio_write_token":
                return secrets.compare_digest(parts[1], expected_token)
    if hasattr(request, "query_params") and request.query_params:
        qp = request.query_params.get("write_token")
        return secrets.compare_digest(qp or "", expected_token)
    return False


def assert_can_write_metrics(request: Request, hf_token: str | None) -> None:
    if on_spaces():
        check_hf_token_has_write_access(hf_token)
    else:
        if check_write_access(request, write_token):
            return
        raise TrackioAPIError(
            "A write_token is required to log metrics or upload to this server. "
            "Use the write-access URL from trackio.show(), set TRACKIO_WRITE_TOKEN, "
            "or send header X-Trackio-Write-Token."
        )


def assert_can_stage_upload(request: Request) -> None:
    if not on_spaces():
        if check_write_access(request, write_token):
            return
        raise TrackioAPIError(
            "A write_token is required to upload files to this server. "
            "Use the write-access URL from trackio.show(), set TRACKIO_WRITE_TOKEN, "
            "or send header X-Trackio-Write-Token."
        )

    bearer_token = _authorization_bearer_token(request)
    if bearer_token is not None:
        try:
            check_hf_token_has_write_access(bearer_token)
        except PermissionError as e:
            raise TrackioAPIError(str(e)) from e
        return

    oauth_token = _hf_access_token(request)
    if oauth_token is not None:
        try:
            check_oauth_token_has_write_access(oauth_token)
        except PermissionError as e:
            raise TrackioAPIError(str(e)) from e
        return

    if check_write_access(request, write_token):
        return

    raise TrackioAPIError(
        "Sign in with Hugging Face to upload files, or use a link that includes the write_token query parameter."
    )


def assert_can_mutate_runs(request: Request) -> None:
    if not on_spaces():
        if check_write_access(request, write_token):
            return
        raise TrackioAPIError(
            "A write_token is required to delete or rename runs. "
            "Open the dashboard using the link that includes the write_token query parameter."
        )
    hf_tok = _hf_access_token(request)
    if hf_tok is not None:
        try:
            check_oauth_token_has_write_access(hf_tok)
        except PermissionError as e:
            raise TrackioAPIError(str(e)) from e
        return
    if check_write_access(request, write_token):
        return
    raise TrackioAPIError(
        "Sign in with Hugging Face to delete or rename runs. You need write access to this Space, "
        "or open the dashboard using a link that includes the write_token query parameter."
    )


def get_run_mutation_status(request: Request) -> dict[str, Any]:
    if not on_spaces():
        if check_write_access(request, write_token):
            return {"spaces": False, "allowed": True, "auth": "local"}
        return {"spaces": False, "allowed": False, "auth": "none"}
    hf_tok = _hf_access_token(request)
    if hf_tok is not None:
        try:
            check_oauth_token_has_write_access(hf_tok)
            return {"spaces": True, "allowed": True, "auth": "oauth"}
        except PermissionError:
            return {"spaces": True, "allowed": False, "auth": "oauth_insufficient"}
    if check_write_access(request, write_token):
        return {"spaces": True, "allowed": True, "auth": "write_token"}
    return {"spaces": True, "allowed": False, "auth": "none"}


def upload_db_to_space(
    request: Request,
    project: str,
    uploaded_db: dict,
    hf_token: str | None,
) -> None:
    assert_can_write_metrics(request, hf_token)
    uploaded_path = consume_uploaded_temp_file(request, uploaded_db)
    try:
        db_project_path = SQLiteStorage.get_project_db_path(project)
        os.makedirs(os.path.dirname(db_project_path), exist_ok=True)
        shutil.copy(uploaded_path, db_project_path)
    finally:
        cleanup_uploaded_temp_file(uploaded_path)


def bulk_upload_media(
    request: Request,
    uploads: list[UploadEntry],
    hf_token: str | None,
) -> None:
    assert_can_write_metrics(request, hf_token)
    for upload in uploads:
        uploaded_path = consume_uploaded_temp_file(request, upload["uploaded_file"])
        try:
            media_path = get_project_media_path(
                project=upload["project"],
                run=upload["run"],
                step=upload["step"],
                relative_path=upload["relative_path"],
            )
            shutil.copy(uploaded_path, media_path)
        finally:
            cleanup_uploaded_temp_file(uploaded_path)


def log(
    request: Request,
    project: str,
    run: str,
    metrics: dict[str, Any],
    step: int | None,
    hf_token: str | None,
    run_id: str | None = None,
) -> None:
    assert_can_write_metrics(request, hf_token)
    SQLiteStorage.log(
        project=project, run=run, run_id=run_id, metrics=metrics, step=step
    )


def bulk_log(
    request: Request,
    logs: list[LogEntry],
    hf_token: str | None,
) -> None:
    assert_can_write_metrics(request, hf_token)

    logs_by_run = {}
    for log_entry in logs:
        key = (log_entry["project"], log_entry["run"], log_entry.get("run_id"))
        if key not in logs_by_run:
            logs_by_run[key] = {
                "metrics": [],
                "steps": [],
                "log_ids": [],
                "config": None,
            }
        logs_by_run[key]["metrics"].append(log_entry["metrics"])
        logs_by_run[key]["steps"].append(log_entry.get("step"))
        logs_by_run[key]["log_ids"].append(log_entry.get("log_id"))
        if log_entry.get("config") and logs_by_run[key]["config"] is None:
            logs_by_run[key]["config"] = log_entry["config"]

    for (project, run, run_id), data in logs_by_run.items():
        has_log_ids = any(lid is not None for lid in data["log_ids"])
        payload = dict(
            project=project,
            run=run,
            run_id=run_id,
            metrics_list=data["metrics"],
            steps=data["steps"],
            config=data["config"],
            log_ids=data["log_ids"] if has_log_ids else None,
        )
        try:
            SQLiteStorage.bulk_log(**payload)
        except sqlite3.OperationalError:
            _enqueue_write("bulk_log", payload)


def bulk_log_system(
    request: Request,
    logs: list[SystemLogEntry],
    hf_token: str | None,
) -> None:
    assert_can_write_metrics(request, hf_token)

    logs_by_run = {}
    for log_entry in logs:
        key = (log_entry["project"], log_entry["run"], log_entry.get("run_id"))
        if key not in logs_by_run:
            logs_by_run[key] = {"metrics": [], "timestamps": [], "log_ids": []}
        logs_by_run[key]["metrics"].append(log_entry["metrics"])
        logs_by_run[key]["timestamps"].append(log_entry.get("timestamp"))
        logs_by_run[key]["log_ids"].append(log_entry.get("log_id"))

    for (project, run, run_id), data in logs_by_run.items():
        has_log_ids = any(lid is not None for lid in data["log_ids"])
        payload = dict(
            project=project,
            run=run,
            run_id=run_id,
            metrics_list=data["metrics"],
            timestamps=data["timestamps"],
            log_ids=data["log_ids"] if has_log_ids else None,
        )
        try:
            SQLiteStorage.bulk_log_system(**payload)
        except sqlite3.OperationalError:
            _enqueue_write("bulk_log_system", payload)


def bulk_alert(
    request: Request,
    alerts: list[AlertEntry],
    hf_token: str | None,
) -> None:
    assert_can_write_metrics(request, hf_token)

    alerts_by_run: dict[tuple, dict] = {}
    for entry in alerts:
        key = (entry["project"], entry["run"], entry.get("run_id"))
        if key not in alerts_by_run:
            alerts_by_run[key] = {
                "titles": [],
                "texts": [],
                "levels": [],
                "steps": [],
                "timestamps": [],
                "alert_ids": [],
            }
        alerts_by_run[key]["titles"].append(entry["title"])
        alerts_by_run[key]["texts"].append(entry.get("text"))
        alerts_by_run[key]["levels"].append(entry["level"])
        alerts_by_run[key]["steps"].append(entry.get("step"))
        alerts_by_run[key]["timestamps"].append(entry.get("timestamp"))
        alerts_by_run[key]["alert_ids"].append(entry.get("alert_id"))

    for (project, run, run_id), data in alerts_by_run.items():
        has_alert_ids = any(aid is not None for aid in data["alert_ids"])
        payload = dict(
            project=project,
            run=run,
            run_id=run_id,
            titles=data["titles"],
            texts=data["texts"],
            levels=data["levels"],
            steps=data["steps"],
            timestamps=data["timestamps"],
            alert_ids=data["alert_ids"] if has_alert_ids else None,
        )
        try:
            SQLiteStorage.bulk_alert(**payload)
        except sqlite3.OperationalError:
            _enqueue_write("bulk_alert", payload)


def get_alerts(
    project: str,
    run: str | None = None,
    run_id: str | None = None,
    level: str | None = None,
    since: str | None = None,
) -> list[dict[str, Any]]:
    return SQLiteStorage.get_alerts(
        project, run_name=run, run_id=run_id, level=level, since=since
    )


def get_metric_values(
    project: str,
    run: str | None,
    metric_name: str,
    step: int | None = None,
    around_step: int | None = None,
    at_time: str | None = None,
    window: int | None = None,
    run_id: str | None = None,
) -> list[dict[str, Any]]:
    return SQLiteStorage.get_metric_values(
        project,
        run,
        metric_name,
        step=step,
        around_step=around_step,
        at_time=at_time,
        window=window,
        run_id=run_id,
    )


def get_runs_for_project(project: str) -> list[dict[str, Any]]:
    return SQLiteStorage.get_run_records(project)


def get_metrics_for_run(
    project: str, run: str | None = None, run_id: str | None = None
) -> list[str]:
    return SQLiteStorage.get_all_metrics_for_run(project, run, run_id=run_id)


def filter_metrics_by_regex(metrics: list[str], filter_pattern: str) -> list[str]:
    if not filter_pattern.strip():
        return metrics
    try:
        pattern = re.compile(filter_pattern, re.IGNORECASE)
        return [metric for metric in metrics if pattern.search(metric)]
    except re.error:
        return [
            metric for metric in metrics if filter_pattern.lower() in metric.lower()
        ]


def get_all_projects() -> list[str]:
    return SQLiteStorage.get_projects()


def get_project_summary(project: str) -> dict[str, Any]:
    runs = SQLiteStorage.get_run_records(project)
    if not runs:
        return {"project": project, "num_runs": 0, "runs": [], "last_activity": None}

    last_steps = SQLiteStorage.get_max_steps_for_runs(project)

    return {
        "project": project,
        "num_runs": len(runs),
        "runs": runs,
        "last_activity": max(last_steps.values()) if last_steps else None,
    }


def get_run_summary(
    project: str, run: str | None = None, run_id: str | None = None
) -> dict[str, Any]:
    if run_id is not None:
        record = next(
            (
                record
                for record in SQLiteStorage.get_run_records(project)
                if record["id"] == run_id
            ),
            None,
        )
        if record is not None:
            run = record["name"]

    num_logs = SQLiteStorage.get_log_count(project, run, run_id=run_id)
    status = SQLiteStorage.get_run_status(project, run)
    if num_logs == 0:
        return {
            "project": project,
            "run": run,
            "run_id": run_id,
            "num_logs": 0,
            "metrics": [],
            "config": None,
            "last_step": None,
            "status": status,
        }

    metrics = SQLiteStorage.get_all_metrics_for_run(project, run, run_id=run_id)
    config = SQLiteStorage.get_run_config(project, run, run_id=run_id)
    last_step = SQLiteStorage.get_last_step(project, run, run_id=run_id)

    return {
        "project": project,
        "run": run,
        "run_id": run_id,
        "num_logs": num_logs,
        "metrics": metrics,
        "config": config,
        "last_step": last_step,
        "status": status,
    }


def get_system_metrics_for_run(
    project: str, run: str | None = None, run_id: str | None = None
) -> list[str]:
    return SQLiteStorage.get_all_system_metrics_for_run(project, run, run_id=run_id)


def get_system_logs(
    project: str, run: str | None = None, run_id: str | None = None
) -> list[dict[str, Any]]:
    return SQLiteStorage.get_system_logs(project, run, run_id=run_id, max_points=1500)


def get_system_logs_batch(
    project: str,
    runs: list[dict[str, Any]],
    max_points: int | None = 1500,
) -> list[dict[str, Any]]:
    runs_clean = _normalize_logs_batch_runs(runs)
    mp = _normalize_logs_batch_max_points(max_points)
    return SQLiteStorage.get_system_logs_batch(project, runs_clean, max_points=mp)


def get_snapshot(
    project: str,
    run: str | None = None,
    run_id: str | None = None,
    step: int | None = None,
    around_step: int | None = None,
    at_time: str | None = None,
    window: int | None = None,
) -> dict[str, Any]:
    return SQLiteStorage.get_snapshot(
        project,
        run,
        run_id=run_id,
        step=step,
        around_step=around_step,
        at_time=at_time,
        window=window,
    )


def get_logs(
    project: str, run: str | None = None, run_id: str | None = None
) -> list[dict[str, Any]]:
    return SQLiteStorage.get_logs(project, run, max_points=1500, run_id=run_id)


def get_logs_batch(
    project: str,
    runs: list[dict[str, Any]],
    max_points: int | None = 1500,
) -> list[dict[str, Any]]:
    runs_clean = _normalize_logs_batch_runs(runs)
    mp = _normalize_logs_batch_max_points(max_points)
    return SQLiteStorage.get_logs_batch(project, runs_clean, max_points=mp)


def query_project(project: str, query: str) -> dict[str, Any]:
    return SQLiteStorage.query_project(project, query)


def get_settings() -> dict[str, Any]:
    return {
        "logo_urls": utils.get_logo_urls(),
        "color_palette": utils.get_color_palette(),
        "plot_order": [
            item.strip()
            for item in os.environ.get("TRACKIO_PLOT_ORDER", "").split(",")
            if item.strip()
        ],
        "table_truncate_length": int(
            os.environ.get("TRACKIO_TABLE_TRUNCATE_LENGTH", "250")
        ),
        "media_dir": str(utils.MEDIA_DIR),
        "space_id": os.getenv("SPACE_ID"),
    }


def get_project_files(project: str) -> list[dict[str, Any]]:
    files_dir = utils.MEDIA_DIR / project / "files"
    if not files_dir.exists():
        return []
    results = []
    for file_path in sorted(files_dir.rglob("*")):
        if file_path.is_file():
            relative = file_path.relative_to(files_dir)
            results.append(
                {
                    "name": str(relative),
                    "path": str(file_path),
                    "size": file_path.stat().st_size,
                }
            )
    return results


def delete_run(
    request: Request,
    project: str,
    run: str | None = None,
    run_id: str | None = None,
) -> bool:
    assert_can_mutate_runs(request)
    return SQLiteStorage.delete_run(project, run, run_id=run_id)


def rename_run(
    request: Request,
    project: str,
    old_name: str,
    new_name: str,
    run_id: str | None = None,
) -> bool:
    assert_can_mutate_runs(request)
    SQLiteStorage.rename_run(project, old_name, new_name, run_id=run_id)
    return True


def force_sync() -> bool:
    if os.environ.get("TRACKIO_BUCKET_ID"):
        return True
    SQLiteStorage._dataset_import_attempted = True
    SQLiteStorage.export_to_parquet()
    scheduler = SQLiteStorage.get_scheduler()
    scheduler.trigger().result()
    return True


CSS = ""
HEAD = ""


def _api_registry() -> dict[str, Any]:
    return {
        "get_run_mutation_status": get_run_mutation_status,
        "upload_db_to_space": upload_db_to_space,
        "bulk_upload_media": bulk_upload_media,
        "log": log,
        "bulk_log": bulk_log,
        "bulk_log_system": bulk_log_system,
        "bulk_alert": bulk_alert,
        "get_alerts": get_alerts,
        "get_metric_values": get_metric_values,
        "get_runs_for_project": get_runs_for_project,
        "get_metrics_for_run": get_metrics_for_run,
        "get_all_projects": get_all_projects,
        "get_project_summary": get_project_summary,
        "get_run_summary": get_run_summary,
        "get_system_metrics_for_run": get_system_metrics_for_run,
        "get_system_logs": get_system_logs,
        "get_system_logs_batch": get_system_logs_batch,
        "get_snapshot": get_snapshot,
        "get_logs": get_logs,
        "get_logs_batch": get_logs_batch,
        "query_project": query_project,
        "get_settings": get_settings,
        "get_project_files": get_project_files,
        "delete_run": delete_run,
        "rename_run": rename_run,
        "force_sync": force_sync,
    }


class TrackioDashboardApp:
    def __init__(self, starlette_app, uvicorn_server: Any, write_token: str) -> None:
        self.app = starlette_app
        self._uvicorn_server = uvicorn_server
        self.write_token = write_token

    def close(self, verbose: bool = True) -> None:
        if self._uvicorn_server is not None:
            self._uvicorn_server.should_exit = True


def build_starlette_app_only(mcp_server: bool = False) -> tuple[Any, str]:
    oauth_routes = [
        Route(OAUTH_START_PATH, oauth_hf_start, methods=["GET"]),
        Route(OAUTH_CALLBACK_PATH, oauth_hf_callback, methods=["GET"]),
        Route("/oauth/logout", oauth_logout, methods=["GET"]),
    ]
    mcp_lifespan = None
    mcp_routes: list[Any] = []
    mcp_enabled = False
    if mcp_server:
        try:
            from trackio.mcp_setup import create_mcp_integration  # noqa: PLC0415

            mcp_routes, mcp_lifespan = create_mcp_integration()
            mcp_enabled = True
        except ImportError:
            warnings.warn(
                "MCP support requested, but the optional `mcp` package is not installed. "
                "Install `trackio[mcp]` to expose `/mcp`.",
                UserWarning,
                stacklevel=2,
            )
    starlette_app = create_trackio_starlette_app(
        oauth_routes,
        _api_registry(),
        extra_routes=mcp_routes,
        mcp_lifespan=mcp_lifespan,
        mcp_enabled=mcp_enabled,
        allowed_file_roots=[
            utils.MEDIA_DIR,
            utils.TRACKIO_LOGO_DIR,
        ],
        upload_authorizer=assert_can_stage_upload,
    )
    from trackio.frontend_server import mount_frontend  # noqa: PLC0415

    mount_frontend(starlette_app)
    return starlette_app, write_token


def make_trackio_server(mcp_server: bool = False) -> TrackioDashboardApp:
    app, wt = build_starlette_app_only(mcp_server=mcp_server)
    return TrackioDashboardApp(app, None, wt)
