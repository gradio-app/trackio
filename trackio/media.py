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

TrackioImageSourceType = str | Path | np.ndarray | PILImage.Image
class TrackioImage:
    """
    Creates an image that can be logged with trackio.

    Demo: fake-training-images
    """

    TYPE = "trackio.image"

    def __init__(
        self, value: TrackioImageSourceType, caption: str | None = None
    ):
        """
        Parameters:
            value: A string path to an image, a numpy array, or a PIL Image.
            caption: A string caption for the image.
        """
        self.caption = caption
        self._value = value
        self._file_path: Path | None = None
        self._format: str | None = None

        if isinstance(self._value, np.ndarray | PILImage.Image) and self._format is None:
            self._format = "png"
        if isinstance(self._value, str | Path):
            if not os.path.isfile(self._value):
                raise ValueError(f"File not found: {self._value}")

    def _as_pil(self) -> PILImage.Image | None:
        try:
            if isinstance(self._value, np.ndarray):
                arr = np.asarray(self._value).astype("uint8")
                return PILImage.fromarray(arr).convert("RGBA")
            if isinstance(self._value, PILImage.Image):
                return self._value.convert("RGBA")
        except Exception as e:
            raise ValueError(f"Failed to process image data: {self._value}") from e
        return None

    def _file_extension(self) -> str:
        if self._file_path:
            return self._file_path.suffix[1:].lower()
        if isinstance(self._value, str | Path):
            path = Path(self._value)
            return path.suffix[1:].lower()
        if self._format:
            return self._format

    def _save(self, project: str, run: str, step: int = 0):
        if self._file_path:
            return

        media_dir = FileStorage.init_project_media_path(project, run, step)
        filename = f"{uuid.uuid4()}.{self._file_extension()}"
        file_path = media_dir / filename
        if pil := self._as_pil():
            pil.save(file_path, format=self._format)
        elif isinstance(self._value, str | Path):
            if os.path.isfile(self._value):
                shutil.copy(self._value, file_path)
            else:
                raise ValueError(f"File not found: {self._value}")
        self._file_path = file_path.relative_to(MEDIA_DIR)

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
            "caption": self.caption,
        }

TrackioVideoSourceType = str | Path | np.ndarray
TrackioVideoFormatType = Literal["gif", "mp4", "webm"]

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
        if isinstance(self._value, np.ndarray) and self._format is None:
            self._format = "gif"
        if isinstance(self._value, str | Path):
            if not os.path.isfile(self._value):
                raise ValueError(f"File not found: {self._value}")

    @property
    def _codec(self) -> str | None:
        match self._format:
            case "gif":
                return "gif"
            case "mp4":
                return "h264"
            case "webm":
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
        if self._file_path:
            return self._file_path.suffix[1:].lower()
        if isinstance(self._value, str | Path):
            path = Path(self._value)
            return path.suffix[1:].lower()
        if self._format:
            return self._format
    
    @staticmethod
    def _process_ndarray(value: np.ndarray) -> np.ndarray:
        # Verify value is either 4D (single video) or 5D array (batched videos).
        # Expected format: (frames, channels, height, width) or (batch, frames, channels, height, width)
        if value.ndim < 4:
            raise ValueError("Video requires at least 4 dimensions (frames, channels, height, width)")
        if value.ndim > 5:
            raise ValueError("Videos can have at most 5 dimensions (batch, frames, channels, height, width)")
        if value.ndim == 4:
            # Reshape to 5D with single batch: (1, frames, channels, height, width)
            value = value[np.newaxis, ...]
        
        value = TrackioVideo._tile_batched_videos(value)
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

    def _get_relative_file_path(self) -> Path | None:
        return self._file_path
        
    def _to_dict(self) -> dict:
        return {
            "_type": self.TYPE,
            "file_path": str(self._get_relative_file_path()),
            "caption": self._caption,
        }