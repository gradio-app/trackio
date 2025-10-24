import os
import shutil
import uuid
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Literal

import numpy as np
from PIL import Image as PILImage

try:  # absolute imports when installed
    from trackio.media.audio_writer import AudioFormatType, write_audio
    from trackio.media.file_storage import FileStorage
    from trackio.media.video_writer import write_video
    from trackio.utils import MEDIA_DIR
except ImportError:  # relative imports for local execution on Spaces
    from media.audio_writer import AudioFormatType, write_audio
    from media.file_storage import FileStorage
    from media.video_writer import write_video
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

        media_dir = FileStorage.init_project_media_path(project, run, step)
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


TrackioImageSourceType = str | Path | np.ndarray | PILImage.Image


class TrackioImage(TrackioMedia):
    """
    Initializes an Image object.

    Example:
        ```python
        import trackio
        import numpy as np
        from PIL import Image

        # Create an image from numpy array
        image_data = np.random.randint(0, 255, (64, 64, 3), dtype=np.uint8)
        image = trackio.Image(image_data, caption="Random image")
        trackio.log({"my_image": image})

        # Create an image from PIL Image
        pil_image = Image.new('RGB', (100, 100), color='red')
        image = trackio.Image(pil_image, caption="Red square")
        trackio.log({"red_image": image})

        # Create an image from file path
        image = trackio.Image("path/to/image.jpg", caption="Photo from file")
        trackio.log({"file_image": image})
        ```

    Args:
        value (`str`, `Path`, `numpy.ndarray`, or `PIL.Image`, *optional*):
            A path to an image, a PIL Image, or a numpy array of shape (height, width, channels).
            If numpy array, should be of type `np.uint8` with RGB values in the range `[0, 255]`.
        caption (`str`, *optional*):
            A string caption for the image.
    """

    TYPE = "trackio.image"

    def __init__(self, value: TrackioImageSourceType, caption: str | None = None):
        super().__init__(value, caption)
        self._format: str | None = None

        if not isinstance(self._value, TrackioImageSourceType):
            raise ValueError(
                f"Invalid value type, expected {TrackioImageSourceType}, got {type(self._value)}"
            )
        if isinstance(self._value, np.ndarray) and self._value.dtype != np.uint8:
            raise ValueError(
                f"Invalid value dtype, expected np.uint8, got {self._value.dtype}"
            )
        if (
            isinstance(self._value, np.ndarray | PILImage.Image)
            and self._format is None
        ):
            self._format = "png"

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

    def _save_media(self, file_path: Path):
        if pil := self._as_pil():
            pil.save(file_path, format=self._format)
        elif isinstance(self._value, str | Path):
            if os.path.isfile(self._value):
                shutil.copy(self._value, file_path)
            else:
                raise ValueError(f"File not found: {self._value}")


TrackioVideoSourceType = str | Path | np.ndarray
TrackioVideoFormatType = Literal["gif", "mp4", "webm"]


class TrackioVideo(TrackioMedia):
    """
    Initializes a Video object.

    Example:
        ```python
        import trackio
        import numpy as np

        # Create a simple video from numpy array
        frames = np.random.randint(0, 255, (10, 3, 64, 64), dtype=np.uint8)
        video = trackio.Video(frames, caption="Random video", fps=30)

        # Create a batch of videos
        batch_frames = np.random.randint(0, 255, (3, 10, 3, 64, 64), dtype=np.uint8)
        batch_video = trackio.Video(batch_frames, caption="Batch of videos", fps=15)

        # Create video from file path
        video = trackio.Video("path/to/video.mp4", caption="Video from file")
        ```

    Args:
        value (`str`, `Path`, or `numpy.ndarray`, *optional*):
            A path to a video file, or a numpy array.
            If numpy array, should be of type `np.uint8` with RGB values in the range `[0, 255]`.
            It is expected to have shape of either (frames, channels, height, width) or (batch, frames, channels, height, width).
            For the latter, the videos will be tiled into a grid.
        caption (`str`, *optional*):
            A string caption for the video.
        fps (`int`, *optional*):
            Frames per second for the video. Only used when value is an ndarray. Default is `24`.
        format (`Literal["gif", "mp4", "webm"]`, *optional*):
            Video format ("gif", "mp4", or "webm"). Only used when value is an ndarray. Default is "gif".
    """

    TYPE = "trackio.video"

    def __init__(
        self,
        value: TrackioVideoSourceType,
        caption: str | None = None,
        fps: int | None = None,
        format: TrackioVideoFormatType | None = None,
    ):
        super().__init__(value, caption)

        if not isinstance(self._value, TrackioVideoSourceType):
            raise ValueError(
                f"Invalid value type, expected {TrackioVideoSourceType}, got {type(self._value)}"
            )
        if isinstance(self._value, np.ndarray):
            if self._value.dtype != np.uint8:
                raise ValueError(
                    f"Invalid value dtype, expected np.uint8, got {self._value.dtype}"
                )
            if format is None:
                format = "gif"
            if fps is None:
                fps = 24
        self._fps = fps
        self._format = format

    @property
    def _codec(self) -> str:
        match self._format:
            case "gif":
                return "gif"
            case "mp4":
                return "h264"
            case "webm":
                return "vp9"
            case _:
                raise ValueError(f"Unsupported format: {self._format}")

    def _save_media(self, file_path: Path):
        if isinstance(self._value, np.ndarray):
            video = TrackioVideo._process_ndarray(self._value)
            write_video(file_path, video, fps=self._fps, codec=self._codec)
        elif isinstance(self._value, str | Path):
            if os.path.isfile(self._value):
                shutil.copy(self._value, file_path)
            else:
                raise ValueError(f"File not found: {self._value}")

    @staticmethod
    def _process_ndarray(value: np.ndarray) -> np.ndarray:
        # Verify value is either 4D (single video) or 5D array (batched videos).
        # Expected format: (frames, channels, height, width) or (batch, frames, channels, height, width)
        if value.ndim < 4:
            raise ValueError(
                "Video requires at least 4 dimensions (frames, channels, height, width)"
            )
        if value.ndim > 5:
            raise ValueError(
                "Videos can have at most 5 dimensions (batch, frames, channels, height, width)"
            )
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


TrackioAudioSourceType = str | Path | np.ndarray


class TrackioAudio(TrackioMedia):
    """
    Initializes an Audio object.

    Example:
        ```python
        import trackio
        import numpy as np

        # Generate a 1-second 440 Hz sine wave (mono)
        sr = 16000
        t = np.linspace(0, 1, sr, endpoint=False)
        wave = 0.2 * np.sin(2 * np.pi * 440 * t)
        audio = trackio.Audio(wave, caption="A4 sine", sample_rate=sr, format="wav")
        trackio.log({"tone": audio})

        # Stereo from numpy array (shape: samples, 2)
        stereo = np.stack([wave, wave], axis=1)
        audio = trackio.Audio(stereo, caption="Stereo", sample_rate=sr, format="mp3")
        trackio.log({"stereo": audio})

        # From an existing file
        audio = trackio.Audio("path/to/audio.wav", caption="From file")
        trackio.log({"file_audio": audio})
        ```

    Args:
        value (`str`, `Path`, or `numpy.ndarray`, *optional*):
            A path to an audio file, or a numpy array.
            The array should be shaped `(samples,)` for mono or `(samples, 2)` for stereo.
            Float arrays will be peak-normalized and converted to 16-bit PCM; integer arrays will be converted to 16-bit PCM as needed.
        caption (`str`, *optional*):
            A string caption for the audio.
        sample_rate (`int`, *optional*):
            Sample rate in Hz. Required when `value` is a numpy array.
        format (`Literal["wav", "mp3"]`, *optional*):
            Audio format used when `value` is a numpy array. Default is "wav".
    """

    TYPE = "trackio.audio"

    def __init__(
        self,
        value: TrackioAudioSourceType,
        caption: str | None = None,
        sample_rate: int | None = None,
        format: AudioFormatType | None = None,
    ):
        super().__init__(value, caption)
        if isinstance(value, np.ndarray):
            if sample_rate is None:
                raise ValueError("Sample rate is required when value is an ndarray")
            if format is None:
                format = "wav"
        self._format = format
        self._sample_rate = sample_rate

    def _save_media(self, file_path: Path):
        if isinstance(self._value, np.ndarray):
            write_audio(
                data=self._value,
                sample_rate=self._sample_rate,
                filename=file_path,
                format=self._format,
            )
        elif isinstance(self._value, str | Path):
            if os.path.isfile(self._value):
                shutil.copy(self._value, file_path)
            else:
                raise ValueError(f"File not found: {self._value}")
