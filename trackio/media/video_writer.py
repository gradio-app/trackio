import subprocess
from pathlib import Path
from typing import Literal

import numpy as np

try:  # absolute imports when installed
    from trackio.media.utils import check_ffmpeg_installed, check_path
except ImportError:  # relative imports for local execution on Spaces
    from media.utils import check_ffmpeg_installed, check_path

VideoCodec = Literal["h264", "vp9", "gif"]


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


def write_video(
    file_path: str | Path, video: np.ndarray, fps: float, codec: VideoCodec
) -> None:
    """RGB uint8 only, shape (F, H, W, 3)."""
    check_ffmpeg_installed()
    check_path(file_path)

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
