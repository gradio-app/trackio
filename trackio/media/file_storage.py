from pathlib import Path

try:  # absolute imports when installed
    from trackio.utils import MEDIA_DIR
except ImportError:  # relative imports for local execution on Spaces
    from utils import MEDIA_DIR


class FileStorage:
    @staticmethod
    def get_project_media_path(
        project: str,
        run: str | None = None,
        step: int | None = None,
        filename: str | None = None,
    ) -> Path:
        if filename is not None and step is None:
            raise ValueError("filename requires step")
        if step is not None and run is None:
            raise ValueError("step requires run")

        path = MEDIA_DIR / project
        if run:
            path /= run
        if step is not None:
            path /= str(step)
        if filename:
            path /= filename
        return path

    @staticmethod
    def init_project_media_path(
        project: str, run: str | None = None, step: int | None = None
    ) -> Path:
        path = FileStorage.get_project_media_path(project, run, step)
        path.mkdir(parents=True, exist_ok=True)
        return path
