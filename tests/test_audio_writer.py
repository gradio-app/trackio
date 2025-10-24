import math
import shutil
import wave
from pathlib import Path

import numpy as np
import pytest

from trackio.media.audio_writer import PYDUB_AVAILABLE, ensure_int16_pcm, write_audio

SAMPLE_RATE = 44100


def _tone(
    duration_s: float, freq_hz: float, sr: int = SAMPLE_RATE, amp: float = 0.5
) -> np.ndarray:
    t = np.linspace(0.0, duration_s, int(sr * duration_s), endpoint=False)
    return (amp * np.sin(2 * math.pi * freq_hz * t)).astype(np.float32)


def _read_wav(path: Path) -> tuple[int, int, int, np.ndarray]:
    with wave.open(str(path), "rb") as f:
        channels = f.getnchannels()
        sampwidth = f.getsampwidth()
        framerate = f.getframerate()
        nframes = f.getnframes()
        pcm = np.frombuffer(f.readframes(nframes), dtype=np.int16)
        if channels > 1:
            pcm = pcm.reshape(-1, channels)
    return channels, sampwidth, framerate, pcm


def _has_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None


@pytest.mark.parametrize("channels", [1, 2])
def test_write_wav_mono_and_stereo_with_float_normalization(
    tmp_path: Path, channels: int
) -> None:
    mono = _tone(0.1, 440.0, SAMPLE_RATE, amp=0.5)
    data = mono if channels == 1 else np.stack([mono, mono], axis=1)

    out = tmp_path / ("mono.wav" if channels == 1 else "stereo.wav")
    write_audio(data=data, sample_rate=SAMPLE_RATE, filename=out, format="wav")

    ch, sw, sr, pcm = _read_wav(out)
    assert ch == channels
    assert sw == 2
    assert sr == SAMPLE_RATE

    max_abs = int(np.max(np.abs(pcm)))
    # float normalization should hit near full-scale
    assert 32000 <= max_abs <= 32767


@pytest.mark.skipif(not PYDUB_AVAILABLE, reason="pydub not available")
@pytest.mark.skipif(not _has_ffmpeg(), reason="ffmpeg not available")
@pytest.mark.parametrize("channels", [1, 2])
def test_write_mp3_mono_and_stereo(tmp_path: Path, channels: int) -> None:
    from pydub import AudioSegment

    mono = _tone(0.1, 440.0, SAMPLE_RATE, amp=0.5)
    data = mono if channels == 1 else np.stack([mono, mono], axis=1)

    out = tmp_path / ("mono.mp3" if channels == 1 else "stereo.mp3")
    write_audio(data=data, sample_rate=SAMPLE_RATE, filename=out, format="mp3")

    seg = AudioSegment.from_file(str(out), format="mp3")
    assert seg.frame_rate == SAMPLE_RATE
    assert seg.channels == channels


@pytest.mark.parametrize(
    "dtype, generator",
    [
        (np.int32, lambda n: (np.arange(n, dtype=np.int32) % 10000) - 5000),
        (np.uint16, lambda n: (np.arange(n, dtype=np.uint16) % 65535)),
        (np.uint8, lambda n: (np.arange(n, dtype=np.uint8) % 255)),
        (np.int8, lambda n: (np.arange(n, dtype=np.int8) % 127) - 63),
    ],
)
def test_write_wav_with_non_int16_inputs(tmp_path: Path, dtype, generator) -> None:
    n = SAMPLE_RATE // 10
    mono = generator(n).astype(dtype)
    out = tmp_path / f"non_int16_{dtype.__name__}.wav"
    write_audio(data=mono, sample_rate=SAMPLE_RATE, filename=out, format="wav")

    ch, sw, sr, pcm = _read_wav(out)
    assert ch == 1
    assert sw == 2
    assert sr == SAMPLE_RATE
    assert pcm.size > 0


def test_wav_fallback_without_pydub(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    mono = _tone(0.05, 220.0, SAMPLE_RATE, amp=0.25)
    out = tmp_path / "fallback.wav"

    # Force fallback path
    import trackio.media.audio_writer as aw  # type: ignore

    monkeypatch.setattr(aw, "PYDUB_AVAILABLE", False, raising=False)

    write_audio(data=mono, sample_rate=SAMPLE_RATE, filename=out, format="wav")
    ch, sw, sr, pcm = _read_wav(out)
    assert ch == 1 and sw == 2 and sr == SAMPLE_RATE
    assert np.max(np.abs(pcm)) >= 100  # not silent


def test_mp3_raises_without_pydub(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    mono = _tone(0.05, 220.0)
    out = tmp_path / "no_pydub.mp3"

    import trackio.media.audio_writer as aw  # type: ignore

    monkeypatch.setattr(aw, "PYDUB_AVAILABLE", False, raising=False)
    with pytest.raises(ImportError):
        write_audio(data=mono, sample_rate=SAMPLE_RATE, filename=out, format="mp3")


def test_silence_float_no_division_by_zero(tmp_path: Path) -> None:
    mono = np.zeros(SAMPLE_RATE // 10, dtype=np.float32)
    out = tmp_path / "silence.wav"
    write_audio(data=mono, sample_rate=SAMPLE_RATE, filename=out, format="wav")
    _, _, _, pcm = _read_wav(out)
    assert np.all(pcm == 0)


def test_invalid_shape_raises(tmp_path: Path) -> None:
    bad = np.zeros((10, 2, 2), dtype=np.float32)
    with pytest.raises(ValueError):
        ensure_int16_pcm(bad)


def test_invalid_sample_rate_raises(tmp_path: Path) -> None:
    mono = _tone(0.05, 220.0)
    out = tmp_path / "bad_sr.wav"
    with pytest.raises(ValueError):
        write_audio(data=mono, sample_rate=0, filename=out, format="wav")
