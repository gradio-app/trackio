import shutil
from pathlib import Path

try:
    from trackio.utils import MEDIA_DIR
except ImportError:
    from utils import MEDIA_DIR


def check_path(file_path: str | Path) -> None:
    """Raise an error if the parent directory does not exist."""
    file_path = Path(file_path)
    if not file_path.parent.exists():
        try:
            file_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise ValueError(
                f"Failed to create parent directory {file_path.parent}: {e}"
            )


def check_ffmpeg_installed() -> None:
    """Raise an error if ffmpeg is not available on the system PATH."""
    if shutil.which("ffmpeg") is None:
        raise RuntimeError(
            "ffmpeg is required to write video but was not found on your system. "
            "Please install ffmpeg and ensure it is available on your PATH."
        )


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


def init_project_media_path(
    project: str, run: str | None = None, step: int | None = None
) -> Path:
    path = get_project_media_path(project, run, step)
    path.mkdir(parents=True, exist_ok=True)
    return path
