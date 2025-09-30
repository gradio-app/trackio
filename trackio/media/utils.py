import shutil
from pathlib import Path


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
