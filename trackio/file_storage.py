from pathlib import Path

from PIL import Image as PILImage

try:  # absolute imports when installed
    from trackio.utils import TRACKIO_DIR
except ImportError:  # relative imports for local execution on Spaces
    from utils import TRACKIO_DIR


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

        path = TRACKIO_DIR / "media" / project
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

    @staticmethod
    def save_image(
        image: PILImage.Image,
        project: str,
        run: str,
        step: int,
        filename: str,
        format: str = "PNG",
    ) -> Path:
        path = FileStorage.init_project_media_path(project, run, step) / filename
        image.save(path, format=format)
        return path

    @staticmethod
    def get_image(project: str, run: str, step: int, filename: str) -> PILImage.Image:
        path = FileStorage.get_project_media_path(project, run, step, filename)
        if not path.exists():
            raise FileNotFoundError(f"Image file not found: {path}")
        return PILImage.open(path).convert("RGBA")
