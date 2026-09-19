"""Observable dictation state and a shutdown that does not discard speech.

Processing markers contain no audio, text or PID. A held flock is the proof
that work still runs; a crashed process releases it without PID reuse hazards.
"""
from __future__ import annotations

from contextlib import ExitStack, contextmanager
import fcntl
import os
from pathlib import Path
import stat
import tempfile
import time
from typing import Iterator

from . import recovery, session


class ShutdownError(session.ToggleSessionError):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


@contextmanager
def processing_dictation(wait: float = 0) -> Iterator[None]:
    """Register before releasing the capture transition, finish after delivery.

    HTTP uploads may briefly wait for another capture transition. The default
    remains nonblocking for shortcut decisions; the processing body never owns
    the transition lock, and exceptions from that body are never retried.
    """
    path = None
    fd = None
    try:
        with ExitStack() as transition:
            deadline = time.monotonic() + max(0, wait)
            while True:
                try:
                    transition.enter_context(session.toggle_session_transition())
                except session.ToggleSessionError as exc:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0 or not isinstance(exc.__cause__, BlockingIOError):
                        raise
                    time.sleep(min(0.02, remaining))
                else:
                    break
            fd, name = tempfile.mkstemp(prefix="processing-", suffix=".lock",
                                       dir=session.get_runtime_dir())
            path = Path(name)
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        if fd is not None:
            try:
                if path is not None:
                    path.unlink(missing_ok=True)
            finally:
                os.close(fd)


def is_processing() -> bool:
    """Inspect under the transition lock to avoid the create-before-flock gap."""
    with session.toggle_session_transition():
        active = False
        for path in session.get_runtime_dir().glob("processing-*.lock"):
            try:
                fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK)
            except FileNotFoundError:
                continue
            try:
                info = os.fstat(fd)
                if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1:
                    continue
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    active = True
                else:
                    path.unlink(missing_ok=True)
            finally:
                os.close(fd)
        return active


def get_dictation_state() -> str:
    capture = session.get_active_session()
    if capture is not None and session._recorder_alive(capture):
        return "recording"
    if is_processing():
        return "processing"
    if capture is not None or recovery.entries():
        return "recoverable"
    return "idle"


@contextmanager
def prepare_shutdown() -> Iterator[str | None]:
    """Keep starts excluded until the caller has stopped its server.

    Failures keep the application running, and keep the session even when arecord
    has already stopped: a later hotkey can still transcribe that original WAV.
    """
    with session.toggle_session_transition():
        if is_processing():
            raise ShutdownError("processing")
        capture = session.get_active_session()
        identifier = None
        if capture is not None:
            try:
                session.stop_toggle_recording(expected_session=capture, preserve_session=True)
            except (OSError, session.ToggleSessionError) as exc:
                raise ShutdownError("stop") from exc
            try:
                identifier = recovery.save_failure(capture.audio_path)
            except (OSError, RuntimeError) as exc:
                raise ShutdownError("save") from exc
            # The recovery copy is complete before either original is removed.
            # If audio unlink fails, keep it discoverable through the shortcut.
            try:
                capture.audio_path.unlink(missing_ok=True)
            except OSError as exc:
                raise ShutdownError("save") from exc
            try:
                session.get_session_path().unlink(missing_ok=True)
            except OSError:
                # There is no recorder or original audio left to supervise.
                # A later state read can discard this empty session snapshot;
                # the saved recovery, announced at quit, is the source of truth.
                pass
        yield identifier
