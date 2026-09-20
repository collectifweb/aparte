from __future__ import annotations

import os
import re
import stat
import tempfile
import time
import wave
import math
import shutil
import subprocess
from pathlib import Path

from .platform_dispatch import is_macos


class RecordingError(RuntimeError):
    pass


def list_microphones() -> list[dict[str, str]]:
    """The capture devices ALSA knows about, for the microphone setting.

    Only the ``plughw`` entries: they name one input each and resample on the
    fly, which the raw ``hw`` ones do not — a 48 kHz microphone would refuse the
    16 kHz Whisper wants.
    """
    if is_macos():
        return _list_microphones_sounddevice()
    if not shutil.which("arecord"):
        return []
    try:
        listing = subprocess.run(
            ["arecord", "-L"], check=False, text=True, capture_output=True, timeout=5
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    lines = listing.splitlines()
    devices = []
    for index, line in enumerate(lines):
        if not line.startswith("plughw:CARD="):
            continue
        description = lines[index + 1].strip() if index + 1 < len(lines) else ""
        devices.append({"name": line.strip(), "label": description or line.strip()})
    return devices


def _list_microphones_sounddevice() -> list[dict[str, str]]:
    """The input devices PortAudio knows about, for the microphone setting on macOS.

    A device is named, not addressed by an ALSA ``plughw`` string: the name is
    stored in the config as a plain string — the same shape Linux keeps — and
    ``sounddevice`` resolves it back to a device at record time. Best-effort:
    an empty list rather than an error when PortAudio is unavailable.
    """
    try:
        import sounddevice as sd
    except Exception:
        return []
    try:
        devices = sd.query_devices()
    except Exception:
        return []
    seen: set[str] = set()
    microphones: list[dict[str, str]] = []
    for device in devices:
        if device.get("max_input_channels", 0) <= 0:
            continue
        name = str(device.get("name", "")).strip()
        if not name or name in seen:
            continue
        seen.add(name)
        microphones.append({"name": name, "label": name})
    return microphones


# A capture goes to a temp file, gets transcribed, then deleted in a `finally`.
# A process killed between the two leaves the user's voice on disk — seen in M8
# after a Ctrl-C during a transcription. The name is the one tempfile builds:
# eight random characters, which never matches the cached beep tones
# (`aparte-<uid>-beep-start.wav`) — those are meant to stay.
_ORPHAN_RECORDING = re.compile(r"^aparte-[a-z0-9_]{8}\.wav$")

# Old enough that no live capture can be caught: the recording cap is 300 s by
# default, and a second instance's file must never be pulled from under it.
_ORPHAN_AFTER_SECONDS = 3600.0
_FAILED_UPLOAD = re.compile(r"^aparte-failed-upload-[a-z0-9_]{8}\.(wav|webm|mp3)$")


def sweep_orphan_recordings(older_than: float = _ORPHAN_AFTER_SECONDS, *,
                            failed_uploads_only: bool = False) -> int:
    """Delete captures an earlier run abandoned. Returns how many were removed.

    Best-effort by design: this runs at startup, and a file that refuses to go
    must never be the reason the app does not."""
    now = time.time()
    removed = 0
    try:
        entries = list(Path(tempfile.gettempdir()).iterdir())
    except OSError:
        return 0
    for path in entries:
        if not (_FAILED_UPLOAD.fullmatch(path.name) or
                (not failed_uploads_only and _ORPHAN_RECORDING.fullmatch(path.name))):
            continue
        try:
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
                continue
            if now - info.st_mtime < older_than:
                continue
            path.unlink()
            removed += 1
        except OSError:
            continue
    return removed


def ensure_microphone_access() -> None:
    """Make sure macOS granted the microphone **before** a stream is opened.

    Opening a PortAudio input stream does not ask for the permission: on a Mac
    that has never been asked, the stream opens happily and records silence, with
    no error and no dialog (measured on Big Sur, M8 — the first dictation of a
    fresh install looked like a broken app). So we ask through AVFoundation and
    refuse to record rather than deliver silence.

    A no-op off macOS, and a no-op once the permission is granted."""
    if not is_macos():
        return
    from .macos_permissions import request_microphone_access

    status = request_microphone_access()
    if status in ("authorized", "unknown"):
        # "unknown" means AVFoundation could not answer: never block a recording
        # on a probe that failed — the capture itself will tell.
        return
    raise RecordingError(
        "macOS has not granted Aparté the microphone. Allow it in System "
        "Settings → Privacy & Security → Microphone, then record again."
    )


def record_wav(
    seconds: float,
    sample_rate: int = 16000,
    backend: str = "auto",
    device: str | None = None,
) -> Path:
    if seconds <= 0:
        raise RecordingError("Recording duration must be greater than zero.")
    if is_macos():
        # macOS has no arecord; PortAudio via sounddevice is the only recorder,
        # so there is no ALSA fallback to suggest when it is missing.
        return _record_wav_sounddevice(seconds, sample_rate, device)
    last_error: Exception | None = None
    # A chosen microphone is an ALSA name, and arecord is the backend that
    # speaks it — so it takes the lead as soon as one is set, which also keeps
    # this path and the global-hotkey one on the same device.
    if backend == "auto" and device and shutil.which("arecord"):
        backend = "arecord"
    if backend in {"auto", "sounddevice"}:
        try:
            return _record_wav_sounddevice(seconds, sample_rate, device)
        except Exception as exc:
            last_error = exc
            if backend == "sounddevice":
                raise
    if backend in {"auto", "arecord"}:
        if shutil.which("arecord"):
            return _record_wav_arecord(seconds, sample_rate, device)
        if backend == "arecord":
            raise RecordingError("arecord was not found on PATH.")
    message = (
        "No microphone recorder found. Install sounddevice or alsa-utils/arecord, "
        "or set APARTE_RECORDER=sounddevice|arecord."
    )
    if last_error:
        message = f"{message} Last error: {last_error}"
    raise RecordingError(message)


def _record_wav_sounddevice(seconds: float, sample_rate: int, device: str | None = None) -> Path:
    try:
        import sounddevice as sd
    except Exception as exc:
        raise RecordingError(
            "Microphone recording requires the sounddevice package. "
            'Install with: python -m pip install -e ".[recording]"'
        ) from exc

    ensure_microphone_access()
    frames = int(seconds * sample_rate)
    data = sd.rec(frames, samplerate=sample_rate, channels=1, dtype="int16", device=device or None)
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


def _record_wav_arecord(seconds: float, sample_rate: int, device: str | None = None) -> Path:
    handle = tempfile.NamedTemporaryFile(prefix="aparte-", suffix=".wav", delete=False)
    path = Path(handle.name)
    handle.close()
    duration = max(1, math.ceil(seconds))
    command = [
        "arecord",
        "-q",
        *(["-D", device] if device else []),
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


# Rising to open, falling to close: the pair is recognisable without looking at
# the screen, which is the whole point of dictating with a global shortcut.
BEEP_TONES = {"start": 880, "stop": 587}


def play_beep(kind: str) -> None:
    """Short tone for the microphone opening or closing. Never raises.

    Synchronous on purpose: the opening tone has to be over before the
    microphone starts, or it ends up in the recording.
    """
    frequency = BEEP_TONES.get(kind)
    if is_macos():
        player = "afplay" if shutil.which("afplay") else None
    else:
        player = next((name for name in ("paplay", "aplay") if shutil.which(name)), None)
    if not frequency or not player:
        return
    try:
        path = _beep_file(kind, frequency)
        command = [player, "-q", str(path)] if player == "aplay" else [player, str(path)]
        subprocess.run(command, check=False, capture_output=True, timeout=3)
    except (OSError, subprocess.SubprocessError, wave.Error):
        return


def _beep_file(kind: str, frequency: int, sample_rate: int = 44100, ms: int = 90) -> Path:
    path = Path(tempfile.gettempdir()) / f"aparte-{os.getuid()}-beep-{kind}.wav"
    if path.exists():
        return path
    frames = int(sample_rate * ms / 1000)
    fade = int(sample_rate * 0.008)  # without it, the tone starts on a click
    samples = bytearray()
    for index in range(frames):
        gain = min(1.0, index / fade, (frames - index) / fade)
        value = int(7000 * gain * math.sin(2 * math.pi * frequency * index / sample_rate))
        samples += value.to_bytes(2, "little", signed=True)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(bytes(samples))
    return path
