"""The main API layer for the Trackio UI."""

import os
import re
import secrets
import shutil
from functools import lru_cache
from typing import Any

import gradio as gr
import huggingface_hub as hf
import pandas as pd

import trackio.utils as utils
from trackio.frontend_server import mount_frontend
from trackio.media import get_project_media_path
from trackio.sqlite_storage import SQLiteStorage
from trackio.typehints import AlertEntry, LogEntry, SystemLogEntry, UploadEntry

HfApi = hf.HfApi()


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


def check_write_access(request: gr.Request, write_token: str) -> bool:
    cookies = request.headers.get("cookie", "")
    if cookies:
        for cookie in cookies.split(";"):
            parts = cookie.strip().split("=")
            if len(parts) == 2 and parts[0] == "trackio_write_token":
                return parts[1] == write_token
    if hasattr(request, "query_params") and request.query_params:
        token = request.query_params.get("write_token")
        return token == write_token
    return False


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


def delete_run(project: str, run: str) -> bool:
    return SQLiteStorage.delete_run(project, run)


def rename_run(project: str, old_name: str, new_name: str) -> bool:
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

with gr.Blocks(title="Trackio Dashboard") as demo:
    gr.api(fn=upload_db_to_space, api_name="upload_db_to_space")
    gr.api(fn=bulk_upload_media, api_name="bulk_upload_media")
    gr.api(fn=log, api_name="log")
    gr.api(fn=bulk_log, api_name="bulk_log")
    gr.api(fn=bulk_log_system, api_name="bulk_log_system")
    gr.api(fn=bulk_alert, api_name="bulk_alert")
    gr.api(fn=get_alerts, api_name="get_alerts")
    gr.api(fn=get_metric_values, api_name="get_metric_values")
    gr.api(fn=get_runs_for_project, api_name="get_runs_for_project")
    gr.api(fn=get_metrics_for_run, api_name="get_metrics_for_run")
    gr.api(fn=get_all_projects, api_name="get_all_projects")
    gr.api(fn=get_project_summary, api_name="get_project_summary")
    gr.api(fn=get_run_summary, api_name="get_run_summary")
    gr.api(fn=get_system_metrics_for_run, api_name="get_system_metrics_for_run")
    gr.api(fn=get_system_logs, api_name="get_system_logs")
    gr.api(fn=get_snapshot, api_name="get_snapshot")
    gr.api(fn=get_logs, api_name="get_logs")
    gr.api(fn=delete_run, api_name="delete_run")
    gr.api(fn=rename_run, api_name="rename_run")
    gr.api(fn=force_sync, api_name="force_sync")

write_token = secrets.token_urlsafe(32)
demo.write_token = write_token


async def _mount_frontend_on_startup():
    mount_frontend(demo.app)


demo.extra_startup_events.append(_mount_frontend_on_startup)

if __name__ == "__main__":
    demo.launch(
        allowed_paths=[utils.TRACKIO_LOGO_DIR, utils.TRACKIO_DIR],
        show_error=True,
        ssr_mode=False,
    )
