import shutil
from pathlib import Path

try:
    from trackio.utils import FILES_DIR
except ImportError:
    from utils import FILES_DIR


def get_project_files_path(project: str, relative_path: str | Path) -> Path:
    """
    Get the full path for a project file.

    Args:
        project: The project name
        relative_path: The relative path within the project's files directory

    Returns:
        The full path to the file
    """
    return FILES_DIR / project / relative_path


def init_project_files_path(project: str, relative_path: str | Path) -> Path:
    """
    Initialize the directory structure for a project file and return the full path.

    Args:
        project: The project name
        relative_path: The relative path within the project's files directory

    Returns:
        The full path to the file (parent directories will be created)
    """
    file_path = get_project_files_path(project, relative_path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    return file_path

