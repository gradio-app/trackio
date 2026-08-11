from typing import Iterator

from trackio.registry import Registry
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
                Run(
                    self.project,
                    str(record["name"]),
                    run_id=str(record["id"]) if record["id"] is not None else None,
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


class Sweep:
    def __init__(self, project: str, sweep_id: str):
        self.project = project
        self.sweep_id = sweep_id

    def _record(self) -> dict:
        record = SQLiteStorage.get_sweep(self.project, self.sweep_id)
        if record is None:
            raise ValueError(
                f"Sweep '{self.sweep_id}' does not exist in project '{self.project}'"
            )
        return record

    @property
    def config(self) -> dict:
        return self._record()["config"]

    @property
    def state(self) -> str:
        return self._record()["state"]

    @property
    def trials(self) -> list[dict]:
        return SQLiteStorage.get_sweep_trials(self.project, self.sweep_id)

    def best_run(self) -> Run | None:
        record = self._record()
        best_run_id = record.get("best_run_id")
        if best_run_id is None:
            return None
        run_record = next(
            (
                r
                for r in SQLiteStorage.get_run_records(self.project)
                if r["id"] == best_run_id
            ),
            None,
        )
        if run_record is None:
            return None
        return Run(self.project, str(run_record["name"]), run_id=best_run_id)

    def pause(self) -> "Sweep":
        SQLiteStorage.set_sweep_state(self.project, self.sweep_id, "paused")
        return self

    def resume(self) -> "Sweep":
        SQLiteStorage.set_sweep_state(self.project, self.sweep_id, "running")
        return self

    def stop(self) -> "Sweep":
        SQLiteStorage.set_sweep_state(self.project, self.sweep_id, "stopped")
        return self

    def cancel(self) -> "Sweep":
        SQLiteStorage.set_sweep_state(self.project, self.sweep_id, "cancelled")
        return self

    def __repr__(self) -> str:
        return f"<Sweep {self.sweep_id} in project {self.project}>"


class Sweeps:
    def __init__(self, project: str):
        self.project = project
        self._sweeps = None

    def _load_sweeps(self):
        if self._sweeps is None:
            records = SQLiteStorage.list_sweeps(self.project)
            self._sweeps = [
                Sweep(self.project, record["sweep_id"]) for record in records
            ]

    def __iter__(self) -> Iterator[Sweep]:
        self._load_sweeps()
        return iter(self._sweeps)

    def __getitem__(self, index: int) -> Sweep:
        self._load_sweeps()
        return self._sweeps[index]

    def __len__(self) -> int:
        self._load_sweeps()
        return len(self._sweeps)

    def __repr__(self) -> str:
        self._load_sweeps()
        return f"<Sweeps project={self.project} count={len(self._sweeps)}>"


class Api:
    def runs(self, project: str) -> Runs:
        if not SQLiteStorage.get_project_db_path(project).exists():
            raise ValueError(f"Project '{project}' does not exist")
        return Runs(project)

    def sweeps(self, project: str) -> Sweeps:
        if not SQLiteStorage.get_project_db_path(project).exists():
            raise ValueError(f"Project '{project}' does not exist")
        return Sweeps(project)

    def sweep(self, project: str, sweep_id: str) -> Sweep:
        if SQLiteStorage.get_sweep(project, sweep_id) is None:
            raise ValueError(
                f"Sweep '{sweep_id}' does not exist in project '{project}'"
            )
        return Sweep(project, sweep_id)

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

    def create_registry(
        self,
        name: str,
        description: str | None = None,
        bucket_id: str | None = None,
    ) -> Registry:
        """Create a new registry and return a handle on it.

        Raises `ValueError` if a registry with this name already exists.
        Registries are never created implicitly: linking into a registry
        that does not exist raises an error.

        Args:
            name (`str`):
                Registry name, e.g. `"models"`. Must match
                `^[A-Za-z0-9_-]+$`.
            description (`str`, *optional*):
                Human-readable description of the registry.
            bucket_id (`str`, *optional*):
                Hugging Face bucket to hold the registry, e.g.
                `"my-org/models-registry"`. The bucket is created (private) if
                it does not exist. A bucket-backed registry is reachable from
                any machine with access to it, including runs that log to a
                Space. Omit for a local registry; defaults to
                `TRACKIO_REGISTRY_BUCKET_ID` when that is set.

        Returns:
            A [`Registry`] handle on the new registry.
        """
        registry = Registry(name, bucket_id=bucket_id)
        registry._storage.create_registry(name, description=description)
        return registry

    def registry(self, name: str, bucket_id: str | None = None) -> Registry:
        """Fetch a handle on an existing registry.

        Pass `bucket_id` (or set `TRACKIO_REGISTRY_BUCKET_ID`) for a
        bucket-backed registry. Raises `ValueError` if no registry with this
        name exists."""
        registry = Registry(name, bucket_id=bucket_id)
        if not registry._storage.registry_exists(name):
            where = (
                ""
                if registry.bucket_id is None
                else f" in bucket '{registry.bucket_id}'"
            )
            raise ValueError(f"Registry '{name}' does not exist{where}")
        return registry
