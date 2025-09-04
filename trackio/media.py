import os
import shutil
import uuid
from pathlib import Path
from typing import Literal

import numpy as np
from PIL import Image as PILImage
import mediapy as mp


try:  # absolute imports when installed
    from trackio.file_storage import FileStorage
    from trackio.utils import MEDIA_DIR
except ImportError:  # relative imports for local execution on Spaces
    from file_storage import FileStorage
    from utils import MEDIA_DIR

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
            # Save image as {MEDIA_DIR}/media/{project}/{run}/{step}/{uuid}.{ext}
            filename = f"{uuid.uuid4()}.{format.lower()}"
            path = FileStorage.save_image(
                self._pil, project, run, step, filename, format=format
            )
            self._file_path = path.relative_to(MEDIA_DIR)
            self._file_format = format
        return str(self._file_path)

    def _get_relative_file_path(self) -> Path | None:
        return self._file_path

    def _get_absolute_file_path(self) -> Path | None:
        return MEDIA_DIR / self._file_path

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

        absolute_path = MEDIA_DIR / file_path
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

TrackioVideoSourceType = str | Path | np.ndarray
TrackioVideoFormatType = Literal["gif", "mp4", "webm", "ogg"]

class TrackioVideo:
    """
    Creates a video that can be logged with trackio.

    Demo: video-demo
    """

    TYPE = "trackio.video"

    def __init__(self,
        value: TrackioVideoSourceType,
        caption: str | None = None,
        fps: int | None = None,
        format: TrackioVideoFormatType | None = None,
    ):
        self._value = value
        self._caption = caption
        self._fps = fps
        self._format = format
        self._file_path: Path | None = None

    @property
    def _codec(self) -> str | None:
        match self._format:
            case "gif":
                return "gif"
            case "mp4":
                return "h264"
            case "webm" | "ogg":
                return "vp9"
            case _:
                return None

    def _save(self, project: str, run: str, step: int = 0):
        if self._file_path:
            return

        media_dir = FileStorage.init_project_media_path(project, run, step)
        filename = f"{uuid.uuid4()}.{self._file_extension()}"
        media_path = media_dir / filename
        if isinstance(self._value, np.ndarray):
            video = TrackioVideo._process_ndarray(self._value)
            mp.write_video(media_path, video, fps=self._fps, codec=self._codec)
        elif isinstance(self._value, str | Path):
            if os.path.isfile(self._value):
                shutil.copy(self._value, media_path)
            else:
                raise ValueError(f"File not found: {self._value}")
        self._file_path = media_path.relative_to(MEDIA_DIR)
    
    def _get_absolute_file_path(self) -> Path | None:
        return MEDIA_DIR / self._file_path

    def _file_extension(self) -> str:
        if self._format is None:
            if self._file_path is None:
                raise ValueError("File format not specified and no file path provided")
            return self._file_path.suffix[1:].lower()
        return self._format
    
    @staticmethod
    def _process_ndarray(value: np.ndarray) -> np.ndarray:
        # Verify value is either 4D (single video) or 5D array (batched videos).
        # Expected format: (frames, channels, height, width) for 4D or (batch, frames, channels, height, width) for 5D
        if value.ndim < 4:
            raise ValueError("Video requires at least 4 dimensions (frames, channels, height, width)")
        if value.ndim > 5:
            raise ValueError("Videos can have at most 5 dimensions (batch, frames, channels, height, width)")
        if value.ndim == 4:
            # Reshape to 5D with single batch: (1, frames, channels, height, width)
            value = value[np.newaxis, ...]
        
        value = TrackioVideo._tile_batched_videos(value)
        
        # Convert final result from (F, H, W, C) to (F, C, H, W) for mediapy
        value = np.transpose(value, (0, 3, 1, 2))
        
        return value
    
    @staticmethod
    def _tile_batched_videos(video: np.ndarray) -> np.ndarray:
        """ 
        Tiles a batch of videos into a grid of videos.
        
        Input format: (batch, frames, channels, height, width) - original FCHW format
        Output format: (frames, total_height, total_width, channels)
        """
        batch_size, frames, channels, height, width = video.shape

        next_pow2 = 1 << (batch_size - 1).bit_length()
        if batch_size != next_pow2:
            pad_len = next_pow2 - batch_size
            pad_shape = (pad_len, frames, channels, height, width)
            padding = np.zeros(pad_shape, dtype=video.dtype)
            video = np.concatenate((video, padding), axis=0)
            batch_size = next_pow2

        n_rows = 1 << ((batch_size.bit_length() - 1) // 2)
        n_cols = batch_size // n_rows

        # Reshape to grid layout: (n_rows, n_cols, frames, channels, height, width)
        video = video.reshape(n_rows, n_cols, frames, channels, height, width)

        # Rearrange dimensions to (frames, total_height, total_width, channels)
        video = video.transpose(2, 0, 4, 1, 5, 3)
        video = video.reshape(frames, n_rows * height, n_cols * width, channels)
        return video
        
    def _to_dict(self) -> dict:
        return {
            "_type": self.TYPE,
            "file_path": str(self._file_path),
            "caption": self._caption,
        }