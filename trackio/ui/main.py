"""The main API layer for the Trackio UI."""

import base64
import os
import re
import secrets
import shutil
from functools import lru_cache
from typing import Any
from urllib.parse import urlencode

import gradio as gr
import httpx
import huggingface_hub as hf
import pandas as pd
from starlette.requests import Request
from starlette.responses import RedirectResponse

import trackio.utils as utils
from trackio.frontend_server import mount_frontend
from trackio.media import get_project_media_path
from trackio.sqlite_storage import SQLiteStorage
from trackio.typehints import AlertEntry, LogEntry, SystemLogEntry, UploadEntry

HfApi = hf.HfApi()

write_token = secrets.token_urlsafe(32)

OAUTH_CALLBACK_PATH = "/login/callback"
OAUTH_START_PATH = "/oauth/hf/start"


def _hf_access_token_from_cookies(request: gr.Request) -> str | None:
    tok = request.cookies.get("trackio_hf_access_token")
    return tok or None


def _oauth_redirect_uri(request: Request) -> str:
    return str(request.base_url).rstrip("/") + OAUTH_CALLBACK_PATH


class TrackioServer(gr.Server):
    def close(self, verbose: bool = True) -> None:
        if self.blocks is None:
            return
        if self.blocks.is_running:
            self.blocks.close(verbose=verbose)


def oauth_hf_start(request: Request):
    client_id = os.getenv("OAUTH_CLIENT_ID")
    if not client_id:
        return RedirectResponse(url="/", status_code=302)
    state = secrets.token_urlsafe(32)
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
    resp = RedirectResponse(url=url, status_code=302)
    resp.set_cookie(
        key="trackio_oauth_state",
        value=state,
        httponly=True,
        samesite="lax",
        max_age=600,
        path="/",
        secure=os.getenv("SYSTEM") == "spaces",
    )
    return resp


def oauth_hf_callback(request: Request):
    client_id = os.getenv("OAUTH_CLIENT_ID")
    client_secret = os.getenv("OAUTH_CLIENT_SECRET")
    err = "/?oauth_error=1"
    if not client_id or not client_secret:
        return RedirectResponse(url=err, status_code=302)
    stored = request.cookies.get("trackio_oauth_state")
    got_state = request.query_params.get("state")
    code = request.query_params.get("code")
    if not stored or not got_state or stored != got_state or not code:
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
    resp = RedirectResponse(url="/", status_code=302)
    resp.delete_cookie("trackio_oauth_state", path="/")
    resp.set_cookie(
        key="trackio_hf_access_token",
        value=access_token,
        httponly=True,
        samesite="lax",
        max_age=86400 * 30,
        path="/",
        secure=os.getenv("SYSTEM") == "spaces",
    )
    return resp


@lru_cache(maxsize=32)
def check_hf_token_has_write_access(hf_token: str | None) -> None:
    if os.getenv("SYSTEM") == "spaces":
        if hf_token is None:
            raise PermissionError(
                "Expected a HF_TOKEN to be provided when logging to a Space"
            )
        who = HfApi.whoami(hf_token)
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


@lru_cache(maxsize=32)
def check_oauth_token_has_write_access(oauth_token: str | None) -> None:
    if not os.getenv("SYSTEM") == "spaces":
        return
    if oauth_token is None:
        raise PermissionError(
            "Expected an oauth to be provided when logging to a Space"
        )
    who = HfApi.whoami(oauth_token)
    user_name = who["name"]
    owner_name = os.getenv("SPACE_AUTHOR_NAME")
    if user_name == owner_name:
        return
    for org in who["orgs"]:
        if org["name"] == owner_name and org["roleInOrg"] == "write":
            return
    raise PermissionError(
        "Expected the oauth token to be the user owner of the space, or be a member of the org owner of the space"
    )


def check_write_access(request: gr.Request, token: str) -> bool:
    cookies = request.headers.get("cookie", "")
    if cookies:
        for cookie in cookies.split(";"):
            parts = cookie.strip().split("=")
            if len(parts) == 2 and parts[0] == "trackio_write_token":
                return parts[1] == token
    if hasattr(request, "query_params") and request.query_params:
        qp = request.query_params.get("write_token")
        return qp == token
    return False


def assert_can_mutate_runs(request: gr.Request) -> None:
    if os.getenv("SYSTEM") != "spaces":
        return
    hf_tok = _hf_access_token_from_cookies(request)
    if hf_tok is not None:
        try:
            check_oauth_token_has_write_access(hf_tok)
        except PermissionError as e:
            raise gr.Error(str(e)) from e
        return
    if check_write_access(request, write_token):
        return
    raise gr.Error(
        "Sign in with Hugging Face to delete or rename runs. You need write access to this Space, "
        "or open the dashboard using a link that includes the write_token query parameter."
    )


def get_run_mutation_status(request: gr.Request) -> dict[str, Any]:
    if os.getenv("SYSTEM") != "spaces":
        return {"spaces": False, "allowed": True, "auth": "local"}
    hf_tok = _hf_access_token_from_cookies(request)
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
    project: str, uploaded_db: gr.FileData, hf_token: str | None
) -> None:
    check_hf_token_has_write_access(hf_token)
    db_project_path = SQLiteStorage.get_project_db_path(project)
    os.makedirs(os.path.dirname(db_project_path), exist_ok=True)
    shutil.copy(uploaded_db["path"], db_project_path)


def bulk_upload_media(uploads: list[UploadEntry], hf_token: str | None) -> None:
    check_hf_token_has_write_access(hf_token)
    for upload in uploads:
        media_path = get_project_media_path(
            project=upload["project"],
            run=upload["run"],
            step=upload["step"],
            relative_path=upload["relative_path"],
        )
        shutil.copy(upload["uploaded_file"]["path"], media_path)


def log(
    project: str,
    run: str,
    metrics: dict[str, Any],
    step: int | None,
    hf_token: str | None,
) -> None:
    check_hf_token_has_write_access(hf_token)
    SQLiteStorage.log(project=project, run=run, metrics=metrics, step=step)


def bulk_log(
    logs: list[LogEntry],
    hf_token: str | None,
) -> None:
    check_hf_token_has_write_access(hf_token)

    logs_by_run = {}
    for log_entry in logs:
        key = (log_entry["project"], log_entry["run"])
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

    for (project, run), data in logs_by_run.items():
        has_log_ids = any(lid is not None for lid in data["log_ids"])
        SQLiteStorage.bulk_log(
            project=project,
            run=run,
            metrics_list=data["metrics"],
            steps=data["steps"],
            config=data["config"],
            log_ids=data["log_ids"] if has_log_ids else None,
        )


def bulk_log_system(
    logs: list[SystemLogEntry],
    hf_token: str | None,
) -> None:
    check_hf_token_has_write_access(hf_token)

    logs_by_run = {}
    for log_entry in logs:
        key = (log_entry["project"], log_entry["run"])
        if key not in logs_by_run:
            logs_by_run[key] = {"metrics": [], "timestamps": [], "log_ids": []}
        logs_by_run[key]["metrics"].append(log_entry["metrics"])
        logs_by_run[key]["timestamps"].append(log_entry.get("timestamp"))
        logs_by_run[key]["log_ids"].append(log_entry.get("log_id"))

    for (project, run), data in logs_by_run.items():
        has_log_ids = any(lid is not None for lid in data["log_ids"])
        SQLiteStorage.bulk_log_system(
            project=project,
            run=run,
            metrics_list=data["metrics"],
            timestamps=data["timestamps"],
            log_ids=data["log_ids"] if has_log_ids else None,
        )


def bulk_alert(
    alerts: list[AlertEntry],
    hf_token: str | None,
) -> None:
    check_hf_token_has_write_access(hf_token)

    alerts_by_run: dict[tuple, dict] = {}
    for entry in alerts:
        key = (entry["project"], entry["run"])
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

    for (project, run), data in alerts_by_run.items():
        has_alert_ids = any(aid is not None for aid in data["alert_ids"])
        SQLiteStorage.bulk_alert(
            project=project,
            run=run,
            titles=data["titles"],
            texts=data["texts"],
            levels=data["levels"],
            steps=data["steps"],
            timestamps=data["timestamps"],
            alert_ids=data["alert_ids"] if has_alert_ids else None,
        )


def get_alerts(
    project: str,
    run: str | None = None,
    level: str | None = None,
    since: str | None = None,
) -> list[dict]:
    return SQLiteStorage.get_alerts(project, run_name=run, level=level, since=since)


def get_metric_values(
    project: str,
    run: str,
    metric_name: str,
    step: int | None = None,
    around_step: int | None = None,
    at_time: str | None = None,
    window: int | None = None,
) -> list[dict]:
    return SQLiteStorage.get_metric_values(
        project,
        run,
        metric_name,
        step=step,
        around_step=around_step,
        at_time=at_time,
        window=window,
    )


def get_runs_for_project(project: str) -> list[str]:
    return SQLiteStorage.get_runs(project)


def get_metrics_for_run(project: str, run: str) -> list[str]:
    return SQLiteStorage.get_all_metrics_for_run(project, run)


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


def get_project_summary(project: str) -> dict:
    runs = SQLiteStorage.get_runs(project)
    if not runs:
        return {"project": project, "num_runs": 0, "runs": [], "last_activity": None}

    last_steps = SQLiteStorage.get_max_steps_for_runs(project)

    return {
        "project": project,
        "num_runs": len(runs),
        "runs": runs,
        "last_activity": max(last_steps.values()) if last_steps else None,
    }


def get_run_summary(project: str, run: str) -> dict:
    num_logs = SQLiteStorage.get_log_count(project, run)
    logs = SQLiteStorage.get_logs(project, run)
    metrics = SQLiteStorage.get_all_metrics_for_run(project, run)

    if not logs:
        return {
            "project": project,
            "run": run,
            "num_logs": 0,
            "metrics": [],
            "config": None,
            "last_step": None,
        }

    df = pd.DataFrame(logs)
    config = logs[0].get("config") if logs else None
    last_step = int(df["step"].max()) if "step" in df.columns else len(logs) - 1

    return {
        "project": project,
        "run": run,
        "num_logs": num_logs,
        "metrics": metrics,
        "config": config,
        "last_step": last_step,
    }


def get_system_metrics_for_run(project: str, run: str) -> list[str]:
    return SQLiteStorage.get_all_system_metrics_for_run(project, run)


def get_system_logs(project: str, run: str) -> list[dict]:
    return SQLiteStorage.get_system_logs(project, run)


def get_snapshot(
    project: str,
    run: str,
    step: int | None = None,
    around_step: int | None = None,
    at_time: str | None = None,
    window: int | None = None,
) -> dict:
    return SQLiteStorage.get_snapshot(
        project, run, step=step, around_step=around_step, at_time=at_time, window=window
    )


def get_logs(project: str, run: str) -> list[dict]:
    return SQLiteStorage.get_logs(project, run)


def delete_run(request: gr.Request, project: str, run: str) -> bool:
    assert_can_mutate_runs(request)
    return SQLiteStorage.delete_run(project, run)


def rename_run(
    request: gr.Request,
    project: str,
    old_name: str,
    new_name: str,
) -> bool:
    assert_can_mutate_runs(request)
    SQLiteStorage.rename_run(project, old_name, new_name)
    return True


def force_sync() -> bool:
    SQLiteStorage._dataset_import_attempted = True
    SQLiteStorage.export_to_parquet()
    scheduler = SQLiteStorage.get_scheduler()
    scheduler.trigger().result()
    return True


CSS = ""
HEAD = ""

gr.set_static_paths(paths=[utils.MEDIA_DIR])


def _make_trackio_server() -> TrackioServer:
    server = TrackioServer(title="Trackio Dashboard")
    server.add_api_route(OAUTH_START_PATH, oauth_hf_start, methods=["GET"])
    server.add_api_route(OAUTH_CALLBACK_PATH, oauth_hf_callback, methods=["GET"])
    server.api(fn=get_run_mutation_status, name="get_run_mutation_status")
    server.api(fn=upload_db_to_space, name="upload_db_to_space")
    server.api(fn=bulk_upload_media, name="bulk_upload_media")
    server.api(fn=log, name="log")
    server.api(fn=bulk_log, name="bulk_log")
    server.api(fn=bulk_log_system, name="bulk_log_system")
    server.api(fn=bulk_alert, name="bulk_alert")
    server.api(fn=get_alerts, name="get_alerts")
    server.api(fn=get_metric_values, name="get_metric_values")
    server.api(fn=get_runs_for_project, name="get_runs_for_project")
    server.api(fn=get_metrics_for_run, name="get_metrics_for_run")
    server.api(fn=get_all_projects, name="get_all_projects")
    server.api(fn=get_project_summary, name="get_project_summary")
    server.api(fn=get_run_summary, name="get_run_summary")
    server.api(fn=get_system_metrics_for_run, name="get_system_metrics_for_run")
    server.api(fn=get_system_logs, name="get_system_logs")
    server.api(fn=get_snapshot, name="get_snapshot")
    server.api(fn=get_logs, name="get_logs")
    server.api(fn=delete_run, name="delete_run")
    server.api(fn=rename_run, name="rename_run")
    server.api(fn=force_sync, name="force_sync")
    server.write_token = write_token
    return server


def prepare_demo_for_launch() -> None:
    global demo
    if demo.blocks is not None:
        demo.close()
        demo = _make_trackio_server()


demo = _make_trackio_server()

if __name__ == "__main__":
    prepare_demo_for_launch()
    app, _, _ = demo.launch(
        allowed_paths=[utils.TRACKIO_LOGO_DIR, utils.TRACKIO_DIR],
        show_error=True,
        ssr_mode=False,
    )
    mount_frontend(app)
