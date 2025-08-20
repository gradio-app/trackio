import uuid
from pathlib import Path

import numpy as np
from PIL import Image as PILImage

try:  # absolute imports when installed
    from trackio.file_storage import FileStorage
    from trackio.utils import TRACKIO_DIR
except ImportError:  # relative imports for local execution on Spaces
    from file_storage import FileStorage
    from utils import TRACKIO_DIR


class TrackioImage:
    """
    Creates an image that can be logged with trackio.

    Demo: fake-training-images
    """

    TYPE = "trackio.image"

    def __init__(
        self, value: str | np.ndarray | PILImage.Image, caption: str | None = None
    ):
        """
        Parameters:
            value: A string path to an image, a numpy array, or a PIL Image.
            caption: A string caption for the image.
        """
        self.caption = caption
        self._pil = TrackioImage._as_pil(value)
        self._file_path: Path | None = None
        self._file_format: str | None = None

    @staticmethod
    def _as_pil(value: str | np.ndarray | PILImage.Image) -> PILImage.Image:
        try:
            if isinstance(value, str):
                return PILImage.open(value).convert("RGBA")
            elif isinstance(value, np.ndarray):
                arr = np.asarray(value).astype("uint8")
                return PILImage.fromarray(arr).convert("RGBA")
            elif isinstance(value, PILImage.Image):
                return value.convert("RGBA")
        except Exception as e:
            raise ValueError(f"Failed to process image data: {value}") from e

    def _save(self, project: str, run: str, step: int = 0, format: str = "PNG") -> str:
        if not self._file_path:
            # Save image as {TRACKIO_DIR}/media/{project}/{run}/{step}/{uuid}.{ext}
            filename = f"{uuid.uuid4()}.{format.lower()}"
            path = FileStorage.save_image(
                self._pil, project, run, step, filename, format=format
            )
            self._file_path = path.relative_to(TRACKIO_DIR)
            self._file_format = format
        return str(self._file_path)

    def _get_relative_file_path(self) -> Path | None:
        return self._file_path

    def _get_absolute_file_path(self) -> Path | None:
        return TRACKIO_DIR / self._file_path

    def _to_dict(self) -> dict:
        if not self._file_path:
            raise ValueError("Image must be saved to file before serialization")
        return {
            "_type": self.TYPE,
            "file_path": str(self._get_relative_file_path()),
            "file_format": self._file_format,
            "caption": self.caption,
        }

    @classmethod
    def _from_dict(cls, obj: dict) -> "TrackioImage":
        if not isinstance(obj, dict):
            raise TypeError(f"Expected dict, got {type(obj).__name__}")
        if obj.get("_type") != cls.TYPE:
            raise ValueError(f"Wrong _type: {obj.get('_type')!r}")

        file_path = obj.get("file_path")
        if not isinstance(file_path, str):
            raise TypeError(
                f"'file_path' must be string, got {type(file_path).__name__}"
            )

        absolute_path = TRACKIO_DIR / file_path
        try:
            if not absolute_path.is_file():
                raise ValueError(f"Image file not found: {file_path}")
            pil = PILImage.open(absolute_path).convert("RGBA")
            instance = cls(pil, caption=obj.get("caption"))
            instance._file_path = Path(file_path)
            instance._file_format = obj.get("file_format")
            return instance
        except Exception as e:
            raise ValueError(f"Failed to load image from file: {absolute_path}") from e
