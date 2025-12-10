import os
import shutil
import warnings
from pathlib import Path
from typing import Literal

import numpy as np
from pydub import AudioSegment

try:
    from trackio.media.media import TrackioMedia
    from trackio.media.utils import check_ffmpeg_installed, check_path
except ImportError:
    from media.media import TrackioMedia
    from media.utils import check_ffmpeg_installed, check_path

SUPPORTED_FORMATS = ["wav", "mp3"]
AudioFormatType = Literal["wav", "mp3"]
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
            TrackioAudio.write_audio(
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

    @staticmethod
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

    @staticmethod
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

        pcm = TrackioAudio.ensure_int16_pcm(data)

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
