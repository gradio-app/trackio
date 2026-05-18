from typing import Iterator

from trackio.remote_client import RemoteClient
from trackio.sqlite_storage import SQLiteStorage

_REMOTE_WRITE_MSG = (
    "Write operations on remote runs are not yet supported via the Python API. "
    "Use the CLI or the dashboard."
)


class Run:
    def __init__(
        self,
        project: str,
        name: str,
        run_id: str | None = None,
        _client: RemoteClient | None = None,
    ):
        self.project = project
        self.name = name
        self._id = run_id or name
        self._client = _client
        self._config: dict | None = None

    @property
    def id(self) -> str:
        return self._id

    @property
    def config(self) -> dict | None:
        if self._config is None:
            if self._client is not None:
                summary = self._client.predict(
                    self.project,
                    self.name,
                    self.id,
                    api_name="/get_run_summary",
                )
                self._config = (
                    summary.get("config") if isinstance(summary, dict) else None
                )
            else:
                self._config = SQLiteStorage.get_run_config(
                    self.project, self.name, run_id=self.id
                )
        return self._config

    @property
    def status(self) -> str | None:
        if self._client is not None:
            return self._client.predict(
                self.project,
                self.name,
                self.id,
                api_name="/get_run_status",
            )
        return SQLiteStorage.get_run_status(self.project, self.name, run_id=self.id)

    def final_metrics(self, mode: str = "last") -> dict:
        """Final value per numeric metric, keyed by metric name."""
        if self._client is not None:
            rich: dict[str, dict] = (
                self._client.predict(
                    self.project,
                    self.name,
                    self.id,
                    mode,
                    api_name="/get_final_metrics_for_run",
                )
                or {}
            )
            return {m: row["value"] for m, row in rich.items() if "value" in row}

        metric_names = SQLiteStorage.get_all_metrics_for_run(self.project, self.name)
        result = {}
        for m in metric_names:
            rows = SQLiteStorage.get_final_metric_for_runs(
                self.project,
                m,
                mode=mode,
                run_names=[self.name],
                run_ids=[self.id],
                status_filter=None,
            )
            if rows:
                result[m] = rows[0]["value"]
        return result

    def metrics(self) -> list[str]:
        if self._client is not None:
            return (
                self._client.predict(
                    self.project,
                    self.name,
                    self.id,
                    api_name="/get_metrics_for_run",
                )
                or []
            )
        return SQLiteStorage.get_all_metrics_for_run(self.project, self.name)

    def history(
        self,
        metric: str | None = None,
        step: int | None = None,
        around_step: int | None = None,
        at_time: str | None = None,
        window: int | None = None,
    ) -> list[dict]:
        if metric is not None:
            if self._client is not None:
                return (
                    self._client.predict(
                        self.project,
                        self.name,
                        metric,
                        step,
                        around_step,
                        at_time,
                        window,
                        self.id,
                        api_name="/get_metric_values",
                    )
                    or []
                )
            return SQLiteStorage.get_metric_values(
                self.project,
                self.name,
                metric,
                step=step,
                around_step=around_step,
                at_time=at_time,
                window=window,
            )
        if self._client is not None:
            return (
                self._client.predict(self.project, self.name, api_name="/get_logs")
                or []
            )
        return SQLiteStorage.get_logs(self.project, self.name)

    def alerts(self, level: str | None = None, since: str | None = None) -> list[dict]:
        if self._client is not None:
            return (
                self._client.predict(
                    self.project,
                    self.name,
                    self.id,
                    level,
                    since,
                    api_name="/get_alerts",
                )
                or []
            )
        return SQLiteStorage.get_alerts(
            self.project, run_name=self.name, run_id=self.id, level=level, since=since
        )

    def delete(self) -> bool:
        if self._client is not None:
            raise NotImplementedError(_REMOTE_WRITE_MSG)
        return SQLiteStorage.delete_run(self.project, self.name, run_id=self.id)

    def move(self, new_project: str) -> bool:
        if self._client is not None:
            raise NotImplementedError(_REMOTE_WRITE_MSG)
        success = SQLiteStorage.move_run(
            self.project, self.name, new_project, run_id=self.id
        )
        if success:
            self.project = new_project
        return success

    def rename(self, new_name: str) -> "Run":
        if self._client is not None:
            raise NotImplementedError(_REMOTE_WRITE_MSG)
        SQLiteStorage.rename_run(self.project, self.name, new_name, run_id=self.id)
        self.name = new_name
        return self

    def __repr__(self) -> str:
        return f"<Run {self.name} in project {self.project}>"


class Runs:
    def __init__(self, project: str, client: RemoteClient | None = None):
        self.project = project
        self._client = client
        self._runs: list[Run] | None = None

    def _load_runs(self):
        if self._runs is not None:
            return
        if self._client is not None:
            records = (
                self._client.predict(self.project, api_name="/get_runs_for_project")
                or []
            )
        else:
            records = SQLiteStorage.get_run_records(self.project)
        self._runs = [
            Run(
                self.project,
                str(record["name"]),
                run_id=str(record["id"]) if record.get("id") is not None else None,
                _client=self._client,
            )
            for record in records
        ]

    def __iter__(self) -> Iterator[Run]:
        self._load_runs()
        return iter(self._runs)  # type: ignore[arg-type]

    def __getitem__(self, index: int) -> Run:
        self._load_runs()
        return self._runs[index]  # type: ignore[index]

    def __len__(self) -> int:
        self._load_runs()
        return len(self._runs)  # type: ignore[arg-type]

    def __repr__(self) -> str:
        self._load_runs()
        return f"<Runs project={self.project} count={len(self._runs)}>"  # type: ignore[arg-type]


class Api:
    def __init__(self, space: str | None = None, hf_token: str | None = None) -> None:
        self._space = space
        self._client: RemoteClient | None = None
        if space is not None:
            self._client = RemoteClient(space, hf_token=hf_token)

    def runs(self, project: str) -> Runs:
        if self._client is None:
            if not SQLiteStorage.get_project_db_path(project).exists():
                raise ValueError(f"Project '{project}' does not exist")
        return Runs(project, client=self._client)

    def alerts(
        self,
        project: str,
        run: str | None = None,
        level: str | None = None,
        since: str | None = None,
    ) -> list[dict]:
        if self._client is not None:
            return (
                self._client.predict(
                    project, run, None, level, since, api_name="/get_alerts"
                )
                or []
            )
        if not SQLiteStorage.get_project_db_path(project).exists():
            raise ValueError(f"Project '{project}' does not exist")
        return SQLiteStorage.get_alerts(project, run_name=run, level=level, since=since)
