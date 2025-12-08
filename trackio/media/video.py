import os
import shutil
import subprocess
from pathlib import Path
from typing import Literal

import numpy as np

try:
    from trackio.media.media import TrackioMedia
    from trackio.media.utils import check_ffmpeg_installed, check_path
except ImportError:
    from media.media import TrackioMedia
    from media.utils import check_ffmpeg_installed, check_path


TrackioVideoSourceType = str | Path | np.ndarray
TrackioVideoFormatType = Literal["gif", "mp4", "webm"]
VideoCodec = Literal["h264", "vp9", "gif"]


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

    @staticmethod
    def _check_array_format(video: np.ndarray) -> None:
        """Raise an error if the array is not in the expected format."""
        if not (video.ndim == 4 and video.shape[-1] == 3):
            raise ValueError(
                f"Expected RGB input shaped (F, H, W, 3), got {video.shape}. "
                f"Input has {video.ndim} dimensions, expected 4."
            )
        if video.dtype != np.uint8:
            raise TypeError(
                f"Expected dtype=uint8, got {video.dtype}. "
                "Please convert your video data to uint8 format."
            )

    @staticmethod
    def write_video(
        file_path: str | Path, video: np.ndarray, fps: float, codec: VideoCodec
    ) -> None:
        """RGB uint8 only, shape (F, H, W, 3)."""
        check_ffmpeg_installed()
        check_path(file_path)

        if codec not in {"h264", "vp9", "gif"}:
            raise ValueError("Unsupported codec. Use h264, vp9, or gif.")

        arr = np.asarray(video)
        TrackioVideo._check_array_format(arr)

        frames = np.ascontiguousarray(arr)
        _, height, width, _ = frames.shape
        out_path = str(file_path)

        cmd = [
            "ffmpeg",
            "-y",
            "-f",
            "rawvideo",
            "-s",
            f"{width}x{height}",
            "-pix_fmt",
            "rgb24",
            "-r",
            str(fps),
            "-i",
            "-",
            "-an",
        ]

        if codec == "gif":
            video_filter = "split[s0][s1];[s0]palettegen[p];[s1][p]paletteuse"
            cmd += [
                "-vf",
                video_filter,
                "-loop",
                "0",
            ]
        elif codec == "h264":
            cmd += [
                "-vcodec",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
            ]
        elif codec == "vp9":
            bpp = 0.08
            bps = int(width * height * fps * bpp)
            if bps >= 1_000_000:
                bitrate = f"{round(bps / 1_000_000)}M"
            elif bps >= 1_000:
                bitrate = f"{round(bps / 1_000)}k"
            else:
                bitrate = str(max(bps, 1))
            cmd += [
                "-vcodec",
                "libvpx-vp9",
                "-b:v",
                bitrate,
                "-pix_fmt",
                "yuv420p",
            ]
        cmd += [out_path]
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            for frame in frames:
                proc.stdin.write(frame.tobytes())
        finally:
            if proc.stdin:
                proc.stdin.close()
            stderr = (
                proc.stderr.read().decode("utf-8", errors="ignore")
                if proc.stderr
                else ""
            )
            ret = proc.wait()
            if ret != 0:
                raise RuntimeError(f"ffmpeg failed with code {ret}\n{stderr}")

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
            TrackioVideo.write_video(file_path, video, fps=self._fps, codec=self._codec)
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
