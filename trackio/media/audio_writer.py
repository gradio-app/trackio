import warnings
from pathlib import Path
from typing import Literal

import numpy as np

try:  # absolute imports when installed
    from trackio.media.utils import check_ffmpeg_installed, check_path
except ImportError:  # relative imports for local execution on Spaces
    from media.utils import check_ffmpeg_installed, check_path

# Try to import pydub, but make it optional
try:
    from pydub import AudioSegment

    PYDUB_AVAILABLE = True
except ImportError:
    PYDUB_AVAILABLE = False
    AudioSegment = None

SUPPORTED_FORMATS = ["wav", "mp3"]
AudioFormatType = Literal["wav", "mp3"]


def ensure_int16_pcm(data: np.ndarray) -> np.ndarray:
    """
    Convert input audio array to contiguous int16 PCM.
    Peak normalization is applied to floating inputs.
    """
    arr = np.asarray(data)
    if arr.ndim not in (1, 2):
        raise ValueError("Audio data must be 1D (mono) or 2D ([samples, channels])")

    if arr.dtype != np.int16:
        warnings.warn(
            f"Converting {arr.dtype} audio to int16 PCM; pass int16 to avoid conversion.",
            stacklevel=2,
        )

    arr = np.nan_to_num(arr, copy=False)

    # Floating types: normalize to peak 1.0, then scale to int16
    if np.issubdtype(arr.dtype, np.floating):
        max_abs = float(np.max(np.abs(arr))) if arr.size else 0.0
        if max_abs > 0.0:
            arr = arr / max_abs
        out = (arr * 32767.0).clip(-32768, 32767).astype(np.int16, copy=False)
        return np.ascontiguousarray(out)

    converters: dict[np.dtype, callable] = {
        np.dtype(np.int16): lambda a: a,
        np.dtype(np.int32): lambda a: (
            (a.astype(np.int32) // 65536).astype(np.int16, copy=False)
        ),
        np.dtype(np.uint16): lambda a: (
            (a.astype(np.int32) - 32768).astype(np.int16, copy=False)
        ),
        np.dtype(np.uint8): lambda a: (
            (a.astype(np.int32) * 257 - 32768).astype(np.int16, copy=False)
        ),
        np.dtype(np.int8): lambda a: (
            (a.astype(np.int32) * 256).astype(np.int16, copy=False)
        ),
    }

    conv = converters.get(arr.dtype)
    if conv is not None:
        out = conv(arr)
        return np.ascontiguousarray(out)
    raise TypeError(f"Unsupported audio dtype: {arr.dtype}")


def write_audio(
    data: np.ndarray,
    sample_rate: int,
    filename: str | Path,
    format: AudioFormatType = "wav",
) -> None:
    if not isinstance(sample_rate, int) or sample_rate <= 0:
        raise ValueError(f"Invalid sample_rate: {sample_rate}")
    if format not in SUPPORTED_FORMATS:
        raise ValueError(
            f"Unsupported format: {format}. Supported: {SUPPORTED_FORMATS}"
        )

    check_path(filename)

    pcm = ensure_int16_pcm(data)

    # If pydub is missing, allow WAV fallback, otherwise require pydub
    if not PYDUB_AVAILABLE:
        if format == "wav":
            write_wav_simple(filename, pcm, sample_rate)
            return
        raise ImportError(
            "pydub is required for non-WAV formats. Install with: pip install pydub"
        )

    if format != "wav":
        check_ffmpeg_installed()

    channels = 1 if pcm.ndim == 1 else pcm.shape[1]
    audio = AudioSegment(
        pcm.tobytes(),
        frame_rate=sample_rate,
        sample_width=2,  # int16
        channels=channels,
    )

    file = audio.export(str(filename), format=format)
    file.close()


def write_wav_simple(
    file_path: str | Path, data: np.ndarray, sample_rate: int = 44100
) -> None:
    """Fallback for basic WAV export when pydub is not available."""
    import wave

    pcm = ensure_int16_pcm(data)
    if pcm.ndim > 2:
        raise ValueError("Audio data must be 1D (mono) or 2D (stereo)")

    with wave.open(str(file_path), "wb") as wav_file:
        wav_file.setnchannels(1 if pcm.ndim == 1 else pcm.shape[1])
        wav_file.setsampwidth(2)  # 16-bit = 2 bytes
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm.tobytes())
