import random

import numpy as np

import trackio


class AudioSynthesizer:
    def __init__(self, sample_rate: int = 44100):
        self.sample_rate = sample_rate
        self.base_frequency = 440.0  # A4 note

        # Musical scale definitions
        self.scales = {
            "major": [0, 2, 4, 5, 7, 9, 11, 12],  # C major scale intervals
            "minor": [0, 2, 3, 5, 7, 8, 10, 12],  # A minor scale intervals
            "chromatic": list(range(12)),  # All 12 semitones
        }

    def generate_scale_audio(
        self,
        scale_name: str,
        duration: float = 2.5,
        note_duration: float = 0.3,
        amplitude: float = 0.01,
    ) -> np.ndarray:
        scale_intervals = self.scales[scale_name]
        total_samples = int(self.sample_rate * duration)
        audio = np.zeros(total_samples)

        for i, interval in enumerate(scale_intervals):
            frequency = self.base_frequency * (2 ** (interval / 12))

            start_sample = int(i * note_duration * self.sample_rate)
            end_sample = int((i + 1) * note_duration * self.sample_rate)

            if start_sample >= total_samples:
                break
            end_sample = min(end_sample, total_samples)

            note_samples = end_sample - start_sample
            if note_samples > 0:
                actual_note_duration = note_samples / self.sample_rate
                t = np.linspace(0, actual_note_duration, note_samples)
                note_audio = amplitude * np.sin(2 * np.pi * frequency * t)

                envelope = np.exp(-t * 2)
                note_audio *= envelope

                audio[start_sample:end_sample] += note_audio

        return audio.astype(np.float32)

    def add_harmonics(self, audio: np.ndarray, num_harmonics: int = 3) -> np.ndarray:
        enhanced = audio.copy()
        for harmonic in range(2, num_harmonics + 1):
            harmonic_amplitude = 0.3 / harmonic
            enhanced += harmonic_amplitude * np.sin(
                2
                * np.pi
                * harmonic
                * np.linspace(0, len(audio) / self.sample_rate, len(audio))
            )
        return enhanced

    def add_reverb(self, audio: np.ndarray, room_size: float = 0.3) -> np.ndarray:
        delay_samples = max(1, int(self.sample_rate * room_size))
        output = audio.copy()

        for i in range(delay_samples, len(audio)):
            output[i] += 0.3 * output[i - delay_samples]

        return output

    def add_distortion(
        self, audio: np.ndarray, gain: float = 10.0, mix: float = 1.0
    ) -> np.ndarray:
        x = audio.astype(np.float64)
        shaped = np.tanh(gain * x)
        shaped /= np.tanh(gain) + 1e-12
        out = (1.0 - mix) * x + mix * shaped
        return out.astype(np.float32)

    def normalize_peak(self, audio: np.ndarray, peak: float = 0.98) -> np.ndarray:
        max_abs = float(np.max(np.abs(audio)))
        if max_abs <= 0.0:
            return audio
        scale = min(peak / max_abs, 1.0)
        return (audio.astype(np.float64) * scale).astype(np.float32)


class AudioAnalyzer:
    def __init__(self, sample_rate: int = 44100):
        self.sample_rate = sample_rate

    def calculate_snr(self, signal: np.ndarray, noise: np.ndarray = None) -> float:
        if noise is None:
            window_ms = 5.0  # 5ms smoothing window
            window_size = max(1, int(self.sample_rate * (window_ms / 1000.0)))
            if window_size % 2 == 0:
                window_size += 1
            kernel = np.ones(window_size, dtype=np.float64) / float(window_size)
            smoothed = np.convolve(signal.astype(np.float64), kernel, mode="same")
            noise = signal.astype(np.float64) - smoothed

        signal_power = float(np.mean((signal.astype(np.float64)) ** 2))
        noise_power = float(np.mean((noise.astype(np.float64)) ** 2))

        eps = 1e-12
        snr_db = 10.0 * np.log10(signal_power / max(noise_power, eps))
        return float(snr_db)

    def calculate_harmonic_distortion(self, audio: np.ndarray) -> float:
        fft_result = np.abs(np.fft.fft(audio))
        freqs = np.fft.fftfreq(len(audio), 1 / self.sample_rate)

        peak_idx = np.argmax(fft_result[1 : len(fft_result) // 2]) + 1
        fundamental_freq = freqs[peak_idx]

        harmonic_power = 0
        fundamental_power = 0

        for harmonic in range(2, 6):  # Check 2nd through 5th harmonics
            harmonic_freq = fundamental_freq * harmonic
            if harmonic_freq < self.sample_rate / 2:
                harmonic_idx = int(harmonic_freq * len(audio) / self.sample_rate)
                if harmonic_idx < len(fft_result):
                    harmonic_power += fft_result[harmonic_idx] ** 2

        fundamental_power = fft_result[peak_idx] ** 2

        if fundamental_power == 0:
            return 0.0

        thd = np.sqrt(harmonic_power / fundamental_power) * 100
        return thd


def main():
    project_id = random.randint(10000, 99999)
    project_name = f"audio-synthesis-demo-{project_id}"

    trackio.init(project=project_name, name="audio-synthesis-run")

    synthesizer = AudioSynthesizer(sample_rate=44100)
    analyzer = AudioAnalyzer(sample_rate=44100)

    # Experiment parameters
    scales_to_test = ["major", "minor", "chromatic"]
    effects = ["clean", "distortion"]

    for scale_name in scales_to_test:
        audio = synthesizer.generate_scale_audio(scale_name=scale_name)

        audio_with_harmonics = synthesizer.add_harmonics(audio, num_harmonics=3)

        for effect in effects:
            if effect == "distortion":
                pre = synthesizer.normalize_peak(audio_with_harmonics, peak=0.99)
                effected = synthesizer.add_distortion(pre, gain=10.0, mix=1.0)
                effected = synthesizer.normalize_peak(effected, peak=0.99)
            else:
                effected = audio_with_harmonics

            processed_audio = synthesizer.add_reverb(effected, room_size=0.2)

            snr = analyzer.calculate_snr(processed_audio)
            thd = analyzer.calculate_harmonic_distortion(processed_audio)

            def _finite(value: float, fallback: float = 0.0) -> float:
                if value is None or not np.isfinite(value):
                    return fallback
                return float(value)

            snr = _finite(snr, 0.0)
            thd = _finite(thd, 0.0)

            # Convert to peak-normalized 16-bit PCM ndarray
            _safe = np.nan_to_num(processed_audio).astype(np.float32, copy=False)
            _peak = float(np.max(np.abs(_safe))) if _safe.size else 0.0
            if _peak > 0.0:
                _safe = _safe / _peak
            audio = (_safe * 32767.0).clip(-32768, 32767).astype(np.int16)

            trackio_audio = trackio.Audio(
                audio,
                caption=f"{scale_name} scale, effect={effect}",
                sample_rate=44100,
                format="wav",
            )

            trackio.log(
                {
                    "scale": scale_name,
                    "effect": effect,
                    "snr_db": snr,
                    "harmonic_distortion": thd,
                    "audio_quality_score": _finite((snr - thd) / 10.0, 0.0),
                    "synthesized_audio": trackio_audio,
                }
            )

    trackio.finish()


if __name__ == "__main__":
    main()
