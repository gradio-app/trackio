import shutil
import subprocess
from pathlib import Path
from typing import Literal

import numpy as np

VideoCodec = Literal["h264", "vp9", "gif"]


def _check_ffmpeg_installed() -> None:
    """Raise an error if ffmpeg is not available on the system PATH."""
    if shutil.which("ffmpeg") is None:
        raise RuntimeError(
            "ffmpeg is required to write video but was not found on your system. "
            "Please install ffmpeg and ensure it is available on your PATH."
        )


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


def _check_path(file_path: str | Path) -> None:
    """Raise an error if the parent directory does not exist."""
    file_path = Path(file_path)
    if not file_path.parent.exists():
        try:
            file_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise ValueError(
                f"Failed to create parent directory {file_path.parent}: {e}"
            )


def write_video(
    file_path: str | Path, video: np.ndarray, fps: float, codec: VideoCodec
) -> None:
    """RGB uint8 only, shape (F, H, W, 3)."""
    _check_ffmpeg_installed()
    _check_path(file_path)

    if codec not in {"h264", "vp9", "gif"}:
        raise ValueError("Unsupported codec. Use h264, vp9, or gif.")

    arr = np.asarray(video)
    _check_array_format(arr)

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
            proc.stderr.read().decode("utf-8", errors="ignore") if proc.stderr else ""
        )
        ret = proc.wait()
        if ret != 0:
            raise RuntimeError(f"ffmpeg failed with code {ret}\n{stderr}")
