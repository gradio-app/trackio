"""Sweep agent runner: pulls trials from sweep storage (local SQLite or a
remote trackio server) and executes them via a user-provided function."""

import json
import os
import subprocess
import time
import uuid

import huggingface_hub

from trackio import context_vars, utils
from trackio.remote_client import RemoteClient
from trackio.sqlite_storage import SQLiteStorage
from trackio.sweeps import (
    SWEEP_ID_ENV,
    SWEEP_METRIC_ENV,
    SWEEP_PARAMS_ENV,
    SWEEP_PROJECT_ENV,
    SWEEP_TRIAL_ID_ENV,
    expand_command,
    is_command_sweep,
)
from trackio.utils import _emit_nonfatal_warning

AGENT_POLL_INTERVAL = 5.0
MAX_INITIAL_FAILURES = 3


class SweepClient:
    """Dispatches sweep operations either directly against local SQLite
    storage or against a remote trackio server's sweep endpoints."""

    def __init__(
        self,
        project: str,
        space_id: str | None = None,
        server_url: str | None = None,
    ):
        self.project = project
        space_id, server_url = utils.resolve_space_id_and_server_url(
            space_id, server_url
        )
        self.space_id = space_id
        self.server_url = server_url
        self._remote: RemoteClient | None = None
        if space_id is not None:
            self._remote = RemoteClient(
                space_id, hf_token=huggingface_hub.utils.get_token(), verbose=False
            )
        elif server_url is not None:
            server_base_url, token = utils.resolve_server_write_token(
                server_url, "Sweeps on a self-hosted server require"
            )
            self._remote = RemoteClient(
                server_base_url, hf_token=None, write_token=token, verbose=False
            )

    @property
    def is_local(self) -> bool:
        return self._remote is None

    def _dispatch(self, api_name: str, local_fn, **kwargs):
        """Run one sweep operation against the remote server when one is
        configured, else directly against local storage. The kwargs match
        both the API endpoint and the storage function signatures."""
        if self._remote is not None:
            return self._remote.predict(
                api_name=f"/{api_name}", project=self.project, **kwargs
            )
        return local_fn(self.project, **kwargs)

    def create_sweep(self, config: dict, name: str | None = None) -> str:
        return self._dispatch(
            "sweep_create", SQLiteStorage.create_sweep, config=config, name=name
        )

    def get_sweep(self, sweep_id: str) -> dict | None:
        return self._dispatch("sweep_get", SQLiteStorage.get_sweep, sweep_id=sweep_id)

    def list_sweeps(self) -> list[dict]:
        return self._dispatch("sweep_list", SQLiteStorage.list_sweeps)

    def get_trials(self, sweep_id: str) -> list[dict]:
        return self._dispatch(
            "sweep_get_trials", SQLiteStorage.get_sweep_trials, sweep_id=sweep_id
        )

    def set_sweep_state(self, sweep_id: str, state: str) -> dict | None:
        return self._dispatch(
            "sweep_set_state",
            SQLiteStorage.set_sweep_state,
            sweep_id=sweep_id,
            state=state,
        )

    def suggest_trial(self, sweep_id: str, agent_id: str | None = None) -> dict:
        return self._dispatch(
            "sweep_suggest_trial",
            SQLiteStorage.suggest_trial,
            sweep_id=sweep_id,
            agent_id=agent_id,
        )

    def report_trial(
        self,
        sweep_id: str,
        trial_id: int,
        state: str,
        metric_value: float | None = None,
    ) -> bool:
        return self._dispatch(
            "sweep_report_trial",
            SQLiteStorage.report_trial,
            sweep_id=sweep_id,
            trial_id=trial_id,
            state=state,
            metric_value=metric_value,
        )


def split_sweep_path(sweep_id: str, project: str | None) -> tuple[str | None, str]:
    if "/" in sweep_id:
        path_project, path_sweep_id = sweep_id.rsplit("/", 1)
        if project is not None and project != path_project:
            _emit_nonfatal_warning(
                f"Ignoring project={project!r}: the qualified sweep id "
                f"{sweep_id!r} already names project {path_project!r}."
            )
        return path_project, path_sweep_id
    return project, sweep_id


def trial_context_from_env() -> dict | None:
    sweep_id = os.environ.get(SWEEP_ID_ENV)
    trial_id = os.environ.get(SWEEP_TRIAL_ID_ENV)
    if not sweep_id or not trial_id:
        return None
    params_json = os.environ.get(SWEEP_PARAMS_ENV)
    try:
        params = json.loads(params_json) if params_json else {}
    except json.JSONDecodeError:
        _emit_nonfatal_warning(
            f"Could not parse {SWEEP_PARAMS_ENV} as JSON; ignoring sweep "
            "parameters from the environment."
        )
        params = {}
    return {
        "sweep_id": sweep_id,
        "trial_id": int(trial_id),
        "params": params,
        "project": os.environ.get(SWEEP_PROJECT_ENV),
        "metric_name": os.environ.get(SWEEP_METRIC_ENV) or None,
    }


def resolve_trial_context() -> dict | None:
    return context_vars.current_sweep_trial.get() or trial_context_from_env()


def _resolve_sweep_trial(project: str, config):
    """The sweep trial context a trackio.init() call in `project` should
    attach to (or None), plus the run config with the trial's parameters
    merged in."""
    sweep_trial = None
    try:
        sweep_trial = resolve_trial_context()
    except Exception as e:
        _emit_nonfatal_warning(
            f"trackio.init() could not resolve the sweep trial context: {e}. Continuing without sweep attachment."
        )
    if sweep_trial is not None:
        if sweep_trial.get("project") not in (None, project):
            _emit_nonfatal_warning(
                f"trackio.init() was called with project '{project}' but the active sweep "
                f"trial belongs to project '{sweep_trial.get('project')}'. The run will "
                "NOT be attached to the sweep."
            )
            sweep_trial = None
        else:
            try:
                base_config = utils.to_json_safe(config or {})
            except Exception:
                base_config = {}
            if not isinstance(base_config, dict):
                base_config = {}
            config = {**base_config, **(sweep_trial.get("params") or {})}
            if sweep_trial.get("metric_name") is None:
                try:
                    sweep_record = SQLiteStorage.get_sweep(
                        project, sweep_trial["sweep_id"]
                    )
                    if sweep_record is not None:
                        sweep_trial = {
                            **sweep_trial,
                            "metric_name": sweep_record.get("metric_name"),
                        }
                except Exception:
                    pass
    return sweep_trial, config


def _mark_trial_running_for_run(
    project: str,
    sweep_trial: dict,
    run_id: str,
    remote_source,
    remote_client,
) -> None:
    """Mark the run's sweep trial as running, locally or through the remote
    client, warning instead of raising on failure."""
    try:
        if remote_source is None:
            SQLiteStorage.mark_trial_running(
                project, sweep_trial["sweep_id"], sweep_trial["trial_id"], run_id
            )
        elif remote_client is not None:
            remote_client.predict(
                api_name="/sweep_mark_trial_running",
                project=project,
                sweep_id=sweep_trial["sweep_id"],
                trial_id=sweep_trial["trial_id"],
                run_id=run_id,
            )
        else:
            _emit_nonfatal_warning(
                "trackio.init() could not attach the run to its sweep trial: no "
                "remote client is available yet. The trial will remain in the "
                "'assigned' state."
            )
    except Exception as e:
        _emit_nonfatal_warning(
            f"trackio.init() could not mark sweep trial {sweep_trial['trial_id']} as running: {e}. Logging will continue."
        )


def _trial_child_env(
    sweep_config: dict,
    client: SweepClient,
    sweep_id: str,
    trial_id: int,
    params: dict,
) -> dict:
    child_env = os.environ.copy()
    child_env[SWEEP_ID_ENV] = sweep_id
    child_env[SWEEP_TRIAL_ID_ENV] = str(trial_id)
    child_env[SWEEP_PARAMS_ENV] = json.dumps(params)
    child_env[SWEEP_PROJECT_ENV] = client.project
    metric_name = (sweep_config.get("metric") or {}).get("name")
    if metric_name:
        child_env[SWEEP_METRIC_ENV] = metric_name
    if client.space_id is not None:
        child_env["TRACKIO_SPACE_ID"] = client.space_id
    elif client.server_url is not None:
        child_env["TRACKIO_SERVER_URL"] = client.server_url
    return child_env


def _run_command_trial(
    sweep_config: dict,
    client: SweepClient,
    sweep_id: str,
    trial_id: int,
    params: dict,
) -> None:
    argv = expand_command(sweep_config, params)
    child_env = _trial_child_env(sweep_config, client, sweep_id, trial_id, params)
    print(f"* Running: {' '.join(argv)}")
    returncode = subprocess.Popen(argv, env=child_env).wait()
    if returncode != 0:
        raise RuntimeError(f"Trial command exited with non-zero status {returncode}.")


def _finish_current_run() -> float | None:
    """Finishes the contextvar run (if any) and returns the last logged value
    of the sweep metric, so the agent's fallback trial report can carry it
    when the run's own report could not reach the server."""
    run = context_vars.current_run.get()
    if run is None:
        return None
    try:
        run.finish()
        return run._sweep_metric_last
    finally:
        context_vars.current_run.set(None)


def agent(
    sweep_id: str,
    function=None,
    entity: str | None = None,
    project: str | None = None,
    count: int | None = None,
    space_id: str | None = None,
    server_url: str | None = None,
) -> None:
    if entity is not None:
        _emit_nonfatal_warning(
            "* Warning: entity is not used. Provided for compatibility with wandb.agent()."
        )
    project, sweep_id = split_sweep_path(sweep_id, project)
    project = project or context_vars.current_project.get()
    if project is None:
        raise ValueError(
            "trackio.agent() requires a project: pass `project=`, use a "
            "qualified sweep id like 'my-project/abcd1234', or call "
            "trackio.init() first."
        )

    client = SweepClient(project, space_id=space_id, server_url=server_url)
    sweep = client.get_sweep(sweep_id)
    if sweep is None:
        raise ValueError(f"Sweep '{sweep_id}' not found in project '{project}'.")
    sweep_config = sweep.get("config") or {}
    metric = sweep_config.get("metric") or {}
    metric_name = metric.get("name")

    command_mode = is_command_sweep(sweep_config)
    if command_mode and function is not None:
        raise ValueError(
            f"Sweep '{sweep_id}' is command-based ('program'/'command' in its "
            "config); do not pass `function` to trackio.agent()."
        )
    if not command_mode and function is None:
        raise ValueError(
            f"Sweep '{sweep_id}' is function-based: its config has no "
            "'program' or 'command', so agents must supply the training "
            "function via trackio.agent(sweep_id, function=...). The "
            "`trackio agent` CLI only supports command-mode sweeps."
        )

    agent_id = uuid.uuid4().hex[:8]
    print(f"* Starting sweep agent {agent_id} for sweep {sweep_id} ({project})")

    trials_run = 0
    consecutive_failures = 0
    while count is None or trials_run < count:
        command = client.suggest_trial(sweep_id, agent_id=agent_id)
        if command["command"] == "wait":
            time.sleep(AGENT_POLL_INTERVAL)
            continue
        if command["command"] == "exit":
            print(f"* Sweep {sweep_id} finished ({command.get('reason', 'done')}).")
            break

        trial_id = command["trial_id"]
        params = command["params"]
        trials_run += 1
        print(f"* Agent {agent_id} starting trial {trial_id} with params: {params}")
        try:
            metric_value = None
            if command_mode:
                _run_command_trial(sweep_config, client, sweep_id, trial_id, params)
            else:
                trial_context = {
                    "sweep_id": sweep_id,
                    "trial_id": trial_id,
                    "params": params,
                    "project": project,
                    "metric_name": metric_name,
                }
                token = context_vars.current_sweep_trial.set(trial_context)
                try:
                    function()
                    metric_value = _finish_current_run()
                    if metric_value is None:
                        metric_value = trial_context.get("metric_value")
                finally:
                    context_vars.current_sweep_trial.reset(token)
            try:
                client.report_trial(
                    sweep_id, trial_id, "finished", metric_value=metric_value
                )
            except Exception as report_error:
                _emit_nonfatal_warning(
                    f"Could not report finished trial {trial_id}: {report_error}"
                )
            consecutive_failures = 0
        except Exception as e:
            consecutive_failures += 1
            _emit_nonfatal_warning(
                f"Sweep trial {trial_id} failed with an exception: {e}"
            )
            try:
                client.report_trial(sweep_id, trial_id, "failed")
            except Exception as report_error:
                _emit_nonfatal_warning(
                    f"Could not report failed trial {trial_id}: {report_error}"
                )
            if not command_mode:
                try:
                    _finish_current_run()
                except Exception:
                    pass
            if consecutive_failures >= MAX_INITIAL_FAILURES:
                raise RuntimeError(
                    f"Sweep agent aborting after {consecutive_failures} "
                    "consecutive failed trials."
                ) from e
