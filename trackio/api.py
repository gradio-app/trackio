from typing import Iterator

from trackio.sqlite_storage import SQLiteStorage


class Run:
    def __init__(self, project: str, name: str, run_id: str | None = None):
        self.project = project
        self.name = name
        self._id = run_id or name
        self._config = None

    @property
    def id(self) -> str:
        return self._id

    @property
    def config(self) -> dict | None:
        if self._config is None:
            self._config = SQLiteStorage.get_run_config(
                self.project, self.name, run_id=self.id
            )
        return self._config

    @property
    def status(self) -> str | None:
        return SQLiteStorage.get_run_status(self.project, self.name, run_id=self.id)

    @property
    def final_metrics(self) -> dict:
        """Last recorded value for each numeric metric, keyed by metric name."""
        metric_names = SQLiteStorage.get_all_metrics_for_run(self.project, self.name)
        result = {}
        for m in metric_names:
            rows = SQLiteStorage.get_final_metric_for_runs(
                self.project, m, mode="last", run_names=[self.name], status_filter=None
            )
            if rows:
                result[m] = rows[0]["value"]
        return result

    def metrics(self) -> list[str]:
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
            return SQLiteStorage.get_metric_values(
                self.project,
                self.name,
                metric,
                step=step,
                around_step=around_step,
                at_time=at_time,
                window=window,
            )
        return SQLiteStorage.get_logs(self.project, self.name)

    def alerts(self, level: str | None = None, since: str | None = None) -> list[dict]:
        return SQLiteStorage.get_alerts(
            self.project, run_name=self.name, run_id=self.id, level=level, since=since
        )

    def delete(self) -> bool:
        return SQLiteStorage.delete_run(self.project, self.name, run_id=self.id)

    def move(self, new_project: str) -> bool:
        success = SQLiteStorage.move_run(
            self.project, self.name, new_project, run_id=self.id
        )
        if success:
            self.project = new_project
        return success

    def rename(self, new_name: str) -> "Run":
        SQLiteStorage.rename_run(self.project, self.name, new_name, run_id=self.id)
        self.name = new_name
        return self

    def __repr__(self) -> str:
        return f"<Run {self.name} in project {self.project}>"


class Runs:
    def __init__(self, project: str):
        self.project = project
        self._runs = None

    def _load_runs(self):
        if self._runs is None:
            records = SQLiteStorage.get_run_records(self.project)
            self._runs = [
                Run(self.project, str(record["name"]), run_id=str(record["id"]))
                for record in records
            ]

    def __iter__(self) -> Iterator[Run]:
        self._load_runs()
        return iter(self._runs)

    def __getitem__(self, index: int) -> Run:
        self._load_runs()
        return self._runs[index]

    def __len__(self) -> int:
        self._load_runs()
        return len(self._runs)

    def __repr__(self) -> str:
        self._load_runs()
        return f"<Runs project={self.project} count={len(self._runs)}>"


class Api:
    def runs(self, project: str) -> Runs:
        if not SQLiteStorage.get_project_db_path(project).exists():
            raise ValueError(f"Project '{project}' does not exist")
        return Runs(project)

    def alerts(
        self,
        project: str,
        run: str | None = None,
        level: str | None = None,
        since: str | None = None,
    ) -> list[dict]:
        if not SQLiteStorage.get_project_db_path(project).exists():
            raise ValueError(f"Project '{project}' does not exist")
        return SQLiteStorage.get_alerts(project, run_name=run, level=level, since=since)
