from __future__ import annotations

import tempfile
import wave
import math
import shutil
import subprocess
from pathlib import Path


class RecordingError(RuntimeError):
    pass


def record_wav(seconds: float, sample_rate: int = 16000, backend: str = "auto") -> Path:
    if seconds <= 0:
        raise RecordingError("Recording duration must be greater than zero.")
    last_error: Exception | None = None
    if backend in {"auto", "sounddevice"}:
        try:
            return _record_wav_sounddevice(seconds, sample_rate)
        except Exception as exc:
            last_error = exc
            if backend == "sounddevice":
                raise
    if backend in {"auto", "arecord"}:
        if shutil.which("arecord"):
            return _record_wav_arecord(seconds, sample_rate)
        if backend == "arecord":
            raise RecordingError("arecord was not found on PATH.")
    message = (
        "No microphone recorder found. Install sounddevice or alsa-utils/arecord, "
        "or set APARTE_RECORDER=sounddevice|arecord."
    )
    if last_error:
        message = f"{message} Last error: {last_error}"
    raise RecordingError(message)


def _record_wav_sounddevice(seconds: float, sample_rate: int) -> Path:
    try:
        import sounddevice as sd
    except Exception as exc:
        raise RecordingError(
            "Microphone recording requires the sounddevice package. "
            'Install with: python -m pip install -e ".[recording]"'
        ) from exc

    frames = int(seconds * sample_rate)
    data = sd.rec(frames, samplerate=sample_rate, channels=1, dtype="int16")
    sd.wait()

    handle = tempfile.NamedTemporaryFile(prefix="aparte-", suffix=".wav", delete=False)
    path = Path(handle.name)
    handle.close()

    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(data.tobytes())
    return path


def _record_wav_arecord(seconds: float, sample_rate: int) -> Path:
    handle = tempfile.NamedTemporaryFile(prefix="aparte-", suffix=".wav", delete=False)
    path = Path(handle.name)
    handle.close()
    duration = max(1, math.ceil(seconds))
    command = [
        "arecord",
        "-q",
        "-f",
        "S16_LE",
        "-r",
        str(sample_rate),
        "-c",
        "1",
        "-d",
        str(duration),
        str(path),
    ]
    completed = subprocess.run(command, check=False, text=True, capture_output=True)
    if completed.returncode != 0:
        path.unlink(missing_ok=True)
        raise RecordingError(completed.stderr.strip() or "arecord failed.")
    return path
