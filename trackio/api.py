from typing import Iterator

from trackio.sqlite_storage import SQLiteStorage


class Run:
    def __init__(self, project: str, name: str):
        self.project = project
        self.name = name
        self._config = None

    @property
    def id(self) -> str:
        return self.name

    @property
    def config(self) -> dict | None:
        if self._config is None:
            self._config = SQLiteStorage.get_run_config(self.project, self.name)
        return self._config

    def delete(self) -> bool:
        return SQLiteStorage.delete_run(self.project, self.name)

    def move(self, new_project: str) -> bool:
        success = SQLiteStorage.move_run(self.project, self.name, new_project)
        if success:
            self.project = new_project
        return success

    def __repr__(self) -> str:
        return f"<Run {self.name} in project {self.project}>"


class Runs:
    def __init__(self, project: str):
        self.project = project
        self._runs = None

    def _load_runs(self):
        if self._runs is None:
            run_names = SQLiteStorage.get_runs(self.project)
            self._runs = [Run(self.project, name) for name in run_names]

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
