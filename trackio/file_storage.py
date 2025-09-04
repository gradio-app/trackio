import os
from pathlib import Path

from PIL import Image as PILImage

try:  # absolute imports when installed
    from trackio.utils import TRACKIO_DIR, get_space
except ImportError:  # relative imports for local execution on Spaces
    from utils import TRACKIO_DIR, get_space


class FileStorage:
    @staticmethod
    def get_base_path() -> Path:
        if get_space() is not None:
            return Path("/home/user/app")
        return TRACKIO_DIR

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

        path = FileStorage.get_base_path() / "media" / project
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
        FileStorage.maybe_create_media_symlink()
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
    
    @staticmethod
    def maybe_create_media_symlink() -> None:
        if get_space() and not (TRACKIO_DIR / "media").exists():
            os.symlink(FileStorage.get_base_path() / "media", TRACKIO_DIR / "media")
