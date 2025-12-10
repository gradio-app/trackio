import os
import uuid
from abc import ABC, abstractmethod
from pathlib import Path

try:  # absolute imports when installed
    from trackio.media.utils import get_project_media_path
    from trackio.utils import MEDIA_DIR
except ImportError:  # relative imports for local execution on Spaces
    from media.utils import get_project_media_path
    from utils import MEDIA_DIR


class TrackioMedia(ABC):
    """
    Abstract base class for Trackio media objects
    Provides shared functionality for file handling and serialization.
    """

    TYPE: str

    def __init_subclass__(cls, **kwargs):
        """Ensure subclasses define the TYPE attribute."""
        super().__init_subclass__(**kwargs)
        if not hasattr(cls, "TYPE") or cls.TYPE is None:
            raise TypeError(f"Class {cls.__name__} must define TYPE attribute")

    def __init__(self, value, caption: str | None = None):
        """
        Saves the value and caption, and if the value is a file path, checks if the file exists.
        """
        self.caption = caption
        self._value = value
        self._file_path: Path | None = None

        if isinstance(self._value, str | Path):
            if not os.path.isfile(self._value):
                raise ValueError(f"File not found: {self._value}")

    def _file_extension(self) -> str:
        if self._file_path:
            return self._file_path.suffix[1:].lower()
        if isinstance(self._value, str | Path):
            path = Path(self._value)
            return path.suffix[1:].lower()
        if hasattr(self, "_format") and self._format:
            return self._format
        return "unknown"

    def _get_relative_file_path(self) -> Path | None:
        return self._file_path

    def _get_absolute_file_path(self) -> Path | None:
        if self._file_path:
            return MEDIA_DIR / self._file_path
        return None

    def _save(self, project: str, run: str, step: int = 0):
        if self._file_path:
            return

        media_dir = get_project_media_path(project=project, run=run, step=step)
        filename = f"{uuid.uuid4()}.{self._file_extension()}"
        file_path = media_dir / filename

        self._save_media(file_path)
        self._file_path = file_path.relative_to(MEDIA_DIR)

    @abstractmethod
    def _save_media(self, file_path: Path):
        """
        Performs the actual media saving logic.
        """
        pass

    def _to_dict(self) -> dict:
        if not self._file_path:
            raise ValueError("Media must be saved to file before serialization")
        return {
            "_type": self.TYPE,
            "file_path": str(self._get_relative_file_path()),
            "caption": self.caption,
        }
