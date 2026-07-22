from typing import Any, Iterator, Sequence

from trackio.sqlite_storage import SQLiteStorage


class Run:
    def __init__(
        self,
        project: str,
        name: str,
        run_id: str | None = None,
        created_at: str | None = None,
    ):
        self.project = project
        self.name = name
        self._id = run_id or name
        self.created_at = created_at
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

    def alerts(self, level: str | None = None, since: str | None = None) -> list[dict]:
        return SQLiteStorage.get_alerts(
            self.project, run_name=self.name, run_id=self.id, level=level, since=since
        )

    def summary(self) -> dict[str, Any]:
        """Return stable metadata describing the run's stored evidence."""

        summary = SQLiteStorage.get_run_config(
            self.project, self.name, run_id=self.id
        )
        return {
            "project": self.project,
            "name": self.name,
            "id": self.id,
            "created_at": self.created_at,
            "config": summary,
            "num_logs": SQLiteStorage.get_log_count(
                self.project, self.name, run_id=self.id
            ),
            "last_step": SQLiteStorage.get_last_step(
                self.project, self.name, run_id=self.id
            ),
            "metrics": SQLiteStorage.get_all_metrics_for_run(
                self.project, self.name, run_id=self.id
            ),
        }

    def history(
        self,
        keys: Sequence[str] | None = None,
        *,
        scalar_only: bool = False,
    ) -> list[dict[str, Any]]:
        """Return unsampled run history in occurrence order.

        ``keys`` projects the result while always retaining ``step`` and
        ``timestamp``. The returned dictionaries contain only public logical
        fields and do not expose Trackio's physical storage schema.
        """

        rows = SQLiteStorage.get_logs(
            self.project,
            self.name,
            max_points=None,
            run_id=self.id,
            scalar_only=scalar_only,
        )
        if keys is None:
            return rows
        selected = set(keys)
        return [
            {
                key: value
                for key, value in row.items()
                if key in selected or key in {"step", "timestamp"}
            }
            for row in rows
        ]

    def metric_series(
        self, names: Sequence[str] | None = None
    ) -> dict[str, list[dict[str, Any]]]:
        """Return metric values grouped by name with explicit steps."""

        metric_names = (
            tuple(names)
            if names is not None
            else tuple(
                SQLiteStorage.get_all_metrics_for_run(
                    self.project, self.name, run_id=self.id
                )
            )
        )
        series = {name: [] for name in metric_names}
        for row in self.history(metric_names):
            for name in metric_names:
                if name in row:
                    series[name].append(
                        {
                            "step": row.get("step"),
                            "timestamp": row.get("timestamp"),
                            "value": row[name],
                        }
                    )
        return series

    def traces(
        self,
        *,
        search: str | None = None,
        sort: str | None = None,
        limit: int | None = None,
        offset: int = 0,
        step: int | None = None,
        trace_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return standard or Verifiers traces for this run."""

        return SQLiteStorage.get_traces(
            self.project,
            self.name,
            search=search,
            sort=sort,
            limit=limit,
            offset=offset,
            run_id=self.id,
            step=step,
            trace_type=trace_type,
        )

    def artifacts(self) -> dict[str, list[dict[str, Any]]]:
        """Return this run's input and output artifact edges."""

        links = SQLiteStorage.get_run_artifacts(
            self.project, run_name=self.name, run_id=self.id
        )
        for records in links.values():
            for record in records:
                manifest = SQLiteStorage.get_artifact_manifest(
                    self.project, record["name"], f"v{record['version']}"
                )
                if manifest is None:
                    continue
                record["description"] = manifest.get("description")
                record["metadata"] = manifest.get("metadata") or {}
                record["digest"] = manifest.get("manifest_digest")
        return links

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
                Run(
                    self.project,
                    str(record["name"]),
                    run_id=str(record["id"]) if record["id"] is not None else None,
                    created_at=(
                        str(record["created_at"])
                        if record.get("created_at") is not None
                        else None
                    ),
                )
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
    def capabilities(self) -> dict[str, bool]:
        """Return stable read capabilities implemented by this API."""

        return {
            "run_summaries": True,
            "full_history": True,
            "explicit_metric_steps": True,
            "standard_traces": True,
            "verifiers_traces": True,
            "live_traces": True,
            "artifact_lineage": True,
            "alerts": True,
        }

    def runs(self, project: str) -> Runs:
        if not SQLiteStorage.get_project_db_path(project).exists():
            raise ValueError(f"Project '{project}' does not exist")
        return Runs(project)

    def run(self, project: str, run_id: str) -> Run:
        """Return one run by immutable ID."""

        for run in self.runs(project):
            if run.id == run_id:
                return run
        raise ValueError(f"Run '{run_id}' does not exist in project '{project}'")

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
