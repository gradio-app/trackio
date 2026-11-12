import shutil
from pathlib import Path

from trackio.utils import resolve_media_path


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
            "ffmpeg is required to write this media format but was not found on your system. "
            "Please install ffmpeg and ensure it is available on your PATH."
        )


def get_project_media_path(
    project: str,
    run: str | None = None,
    step: int | None = None,
    relative_path: str | Path | None = None,
) -> Path:
    """
    Get the full path where uploaded files are stored for a Trackio project (and create the directory if it doesn't exist).
    If a run is not provided, the files are stored in a project-level directory with the given relative path.

    Args:
        project: The project name
        run: The run name
        step: The step number
        relative_path: The relative path within the directory (only used if run is not provided)

    Returns:
        The full path to the media file
    """
    if step is not None and run is None:
        raise ValueError("Uploading files at a specific step requires a run")

    parts = [run] if run else ["files"]
    if run and step is not None:
        parts.append(str(step))
    elif not run and relative_path:
        parts.append(relative_path)
    path = resolve_media_path(project, *parts)
    path.mkdir(parents=True, exist_ok=True)
    return path
