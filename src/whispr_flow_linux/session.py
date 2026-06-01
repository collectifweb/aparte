from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from .audio import RecordingError


class ToggleSessionError(RuntimeError):
    pass


@dataclass(frozen=True)
class RecordingSession:
    pid: int
    audio_path: Path
    sample_rate: int
    started_at: float


def get_runtime_dir() -> Path:
    override = os.getenv("WHISPR_RUNTIME_DIR")
    if override:
        candidates = [Path(override).expanduser()]
    else:
        candidates = []
        if os.getenv("XDG_RUNTIME_DIR"):
            candidates.append(Path(os.environ["XDG_RUNTIME_DIR"]) / "whispr-flow")
        candidates.append(Path(tempfile.gettempdir()) / f"whispr-flow-{os.getuid()}")
    last_error: OSError | None = None
    for path in candidates:
        try:
            path.mkdir(parents=True, exist_ok=True)
            probe = path / ".write-test"
            probe.write_text("", encoding="utf-8")
            probe.unlink(missing_ok=True)
            return path
        except OSError as exc:
            last_error = exc
    raise ToggleSessionError(f"No writable runtime directory found: {last_error}")


def get_session_path() -> Path:
    return get_runtime_dir() / "toggle-session.json"


def get_active_session() -> RecordingSession | None:
    path = get_session_path()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        session = RecordingSession(
            pid=int(data["pid"]),
            audio_path=Path(str(data["audio_path"])),
            sample_rate=int(data["sample_rate"]),
            started_at=float(data["started_at"]),
        )
    except Exception:
        path.unlink(missing_ok=True)
        return None
    if not _process_exists(session.pid):
        path.unlink(missing_ok=True)
        return None
    return session


def start_toggle_recording(sample_rate: int = 16000) -> RecordingSession:
    if get_active_session():
        raise ToggleSessionError("Recording is already active.")
    executable = shutil.which("arecord")
    if not executable:
        raise RecordingError("Toggle recording requires arecord from alsa-utils.")

    audio_path = get_runtime_dir() / f"toggle-{int(time.time() * 1000)}.wav"
    command = [
        executable,
        "-q",
        "-f",
        "S16_LE",
        "-r",
        str(sample_rate),
        "-c",
        "1",
        str(audio_path),
    ]
    process = subprocess.Popen(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    session = RecordingSession(
        pid=process.pid,
        audio_path=audio_path,
        sample_rate=sample_rate,
        started_at=time.time(),
    )
    get_session_path().write_text(
        json.dumps(
            {
                "pid": session.pid,
                "audio_path": str(session.audio_path),
                "sample_rate": session.sample_rate,
                "started_at": session.started_at,
            }
        ),
        encoding="utf-8",
    )
    return session


def stop_toggle_recording(timeout: float = 3.0) -> RecordingSession:
    session = get_active_session()
    if not session:
        raise ToggleSessionError("No active toggle recording.")

    try:
        os.killpg(session.pid, signal.SIGINT)
    except ProcessLookupError:
        pass
    except PermissionError as exc:
        raise ToggleSessionError(f"Cannot stop recording process {session.pid}: {exc}") from exc

    deadline = time.time() + timeout
    while time.time() < deadline and _process_exists(session.pid):
        time.sleep(0.05)
    if _process_exists(session.pid):
        try:
            os.killpg(session.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass

    get_session_path().unlink(missing_ok=True)
    if not session.audio_path.exists():
        raise ToggleSessionError(f"Recording file was not created: {session.audio_path}")
    return session


def _process_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
