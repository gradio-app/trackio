from typing import Any, Iterator, Sequence

from trackio.remote_client import RemoteClient
from trackio.sqlite_storage import SQLiteStorage


class Run:
    def __init__(
        self,
        project: str,
        name: str,
        run_id: str | None = None,
        created_at: str | None = None,
        remote_client: RemoteClient | None = None,
    ):
        self.project = project
        self.name = name
        self._id = run_id or name
        self.created_at = created_at
        self._remote_client = remote_client
        self._config = None

    def _remote(self, api_name: str, **kwargs: Any) -> Any:
        if self._remote_client is None:
            raise RuntimeError("run is not backed by a remote Trackio server")
        return self._remote_client.predict(api_name=api_name, **kwargs)

    @property
    def id(self) -> str:
        return self._id

    @property
    def config(self) -> dict | None:
        if self._config is None:
            if self._remote_client is not None:
                summary = self._remote(
                    "/get_run_summary",
                    project=self.project,
                    run=self.name,
                    run_id=self.id,
                )
                self._config = summary.get("config")
            else:
                self._config = SQLiteStorage.get_run_config(
                    self.project, self.name, run_id=self.id
                )
        return self._config

    def alerts(self, level: str | None = None, since: str | None = None) -> list[dict]:
        if self._remote_client is not None:
            return self._remote(
                "/get_alerts",
                project=self.project,
                run=self.name,
                run_id=self.id,
                level=level,
                since=since,
            )
        return SQLiteStorage.get_alerts(
            self.project, run_name=self.name, run_id=self.id, level=level, since=since
        )

    def summary(self) -> dict[str, Any]:
        """Return stable metadata describing the run's stored evidence."""

        if self._remote_client is not None:
            remote_summary = self._remote(
                "/get_run_summary",
                project=self.project,
                run=self.name,
                run_id=self.id,
            )
            return {
                "project": self.project,
                "name": self.name,
                "id": self.id,
                "created_at": self.created_at,
                "config": remote_summary.get("config"),
                "num_logs": remote_summary.get("num_logs", 0),
                "last_step": remote_summary.get("last_step"),
                "metrics": remote_summary.get("metrics", []),
            }

        summary = SQLiteStorage.get_run_config(self.project, self.name, run_id=self.id)
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

        if self._remote_client is not None:
            rows = self._remote(
                "/get_run_history",
                project=self.project,
                run=self.name,
                run_id=self.id,
                scalar_only=scalar_only,
            )
        else:
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
                self.summary()["metrics"]
                if self._remote_client is not None
                else SQLiteStorage.get_all_metrics_for_run(
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

    def system_metric_names(self) -> list[str]:
        """Return the names of host metrics recorded for this run."""

        if self._remote_client is not None:
            return self._remote(
                "/get_system_metrics_for_run",
                project=self.project,
                run=self.name,
                run_id=self.id,
            )
        return SQLiteStorage.get_all_system_metrics_for_run(
            self.project,
            self.name,
            run_id=self.id,
        )

    def system_history(self) -> list[dict[str, Any]]:
        """Return provider-bounded host telemetry in timestamp order."""

        if self._remote_client is not None:
            return self._remote(
                "/get_system_logs",
                project=self.project,
                run=self.name,
                run_id=self.id,
            )
        return SQLiteStorage.get_system_logs(
            self.project,
            self.name,
            run_id=self.id,
            max_points=None,
        )

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

        kwargs = {
            "project": self.project,
            "run": self.name,
            "search": search,
            "sort": sort,
            "limit": limit,
            "offset": offset,
            "run_id": self.id,
            "step": step,
            "trace_type": trace_type,
        }
        if self._remote_client is not None:
            return self._remote("/get_traces", **kwargs)
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

        if self._remote_client is not None:
            links = self._remote(
                "/get_run_artifacts",
                project=self.project,
                run=self.name,
                run_id=self.id,
            )
        else:
            links = SQLiteStorage.get_run_artifacts(
                self.project, run_name=self.name, run_id=self.id
            )
        for records in links.values():
            for record in records:
                if self._remote_client is not None:
                    manifest = self._remote(
                        "/get_artifact_manifest",
                        project=self.project,
                        name=record["name"],
                        spec=f"v{record['version']}",
                    )
                else:
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
        if self._remote_client is not None:
            raise RuntimeError("trackio.Api remote runs are read-only")
        return SQLiteStorage.delete_run(self.project, self.name, run_id=self.id)

    def move(self, new_project: str) -> bool:
        if self._remote_client is not None:
            raise RuntimeError("trackio.Api remote runs are read-only")
        success = SQLiteStorage.move_run(
            self.project, self.name, new_project, run_id=self.id
        )
        if success:
            self.project = new_project
        return success

    def rename(self, new_name: str) -> "Run":
        if self._remote_client is not None:
            raise RuntimeError("trackio.Api remote runs are read-only")
        SQLiteStorage.rename_run(self.project, self.name, new_name, run_id=self.id)
        self.name = new_name
        return self

    def __repr__(self) -> str:
        return f"<Run {self.name} in project {self.project}>"


class Runs:
    def __init__(self, project: str, remote_client: RemoteClient | None = None):
        self.project = project
        self._remote_client = remote_client
        self._runs = None

    def _load_runs(self):
        if self._runs is None:
            records = (
                self._remote_client.predict(
                    project=self.project, api_name="/get_runs_for_project"
                )
                if self._remote_client is not None
                else SQLiteStorage.get_run_records(self.project)
            )
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
                    remote_client=self._remote_client,
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
    def __init__(
        self, server_url: str | None = None, *, hf_token: str | None = None
    ) -> None:
        self._remote_client = (
            RemoteClient(server_url, hf_token=hf_token) if server_url is not None else None
        )

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
            "system_metrics": True,
        }

    def run_configs(self, project: str) -> dict[str, Any]:
        """Every run's configuration in one request.

        The server has always been able to answer this for a whole project;
        without it on the client, callers read configurations one run at a time.
        """
        if self._remote_client is None:
            return SQLiteStorage.get_all_run_configs(project)
        return self._remote_client.predict(project=project, api_name="/get_run_configs")

    def run_lifecycles(self, project: str) -> dict[str, Any]:
        """Every run's latest lifecycle values in one request.

        Reading these per run makes listing a project cost a request per run.
        """
        if self._remote_client is None:
            return SQLiteStorage.get_run_lifecycles(project)
        return self._remote_client.predict(
            project=project, api_name="/get_run_lifecycles"
        )

    def runs(self, project: str) -> Runs:
        if self._remote_client is not None:
            return Runs(project, self._remote_client)
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
        if self._remote_client is not None:
            return self._remote_client.predict(
                project=project,
                run=run,
                level=level,
                since=since,
                api_name="/get_alerts",
            )
        if not SQLiteStorage.get_project_db_path(project).exists():
            raise ValueError(f"Project '{project}' does not exist")
        return SQLiteStorage.get_alerts(project, run_name=run, level=level, since=since)
