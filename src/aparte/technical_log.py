"""Small, private diagnostics for the keyboard shortcut; never a stdout sink."""
from __future__ import annotations

from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import stat
import sys

MAX_BYTES = 128 * 1024  # one active file and one previous file
_EVENTS = {"invoked", "completed", "failed", "audio_start_failed"}


def _directory() -> int:
    base = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state")
    if not base.is_absolute():
        raise OSError("state directory must be absolute")
    # Walk with directory descriptors, refusing symlinks at every level. Only
    # directories belonging to this logger have their permissions tightened.
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        parts = (*base.parts[1:], "aparte", "logs")
        for index, part in enumerate(parts):
            if part in {".", ".."}:
                raise OSError("invalid state directory")
            try:
                os.mkdir(part, 0o700, dir_fd=fd)
            except FileExistsError:
                pass
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
            if index >= len(parts) - 2:
                if os.fstat(fd).st_uid != os.getuid():
                    raise OSError("diagnostic directory has another owner")
                os.fchmod(fd, 0o700)
        return fd
    except BaseException:
        os.close(fd)
        raise


def _file(directory: int, name: str) -> int:
    fd = os.open(name, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK,
                 0o600, dir_fd=directory)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1:
            raise OSError("unsafe diagnostic file")
        os.fchmod(fd, 0o600)
        return fd
    except BaseException:
        os.close(fd)
        raise


def write_event(event: str, *, error_type: str | None = None,
                audio_diagnostic: str | None = None) -> None:
    """Best effort. Only a recorder-start failure may carry an ALSA diagnostic.

    Never pass arbitrary exception messages here: they may contain dictated
    text, HTTP response bodies, or subprocess arguments used for insertion.
    """
    if event not in _EVENTS:
        return
    try:
        data = {"utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "event": event}
        if error_type is not None:
            data["error_type"] = error_type[:80]
        if event == "audio_start_failed" and audio_diagnostic is not None:
            data["audio_diagnostic"] = audio_diagnostic[:6000]
        line = (json.dumps(data, ensure_ascii=False) + "\n").encode("utf-8")
        directory = _directory()
        try:
            # The directory inode is stable across rotations and shared by all
            # shortcut invocations. Do not remove it while the app is running.
            fcntl.flock(directory, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fd = _file(directory, "hotkey.jsonl")
            try:
                if os.fstat(fd).st_size > MAX_BYTES:
                    # Do not retain an unbounded pre-existing or corrupt file.
                    os.ftruncate(fd, 0)
                if os.fstat(fd).st_size + len(line) > MAX_BYTES:
                    os.close(fd)
                    fd = -1
                    backup = _file(directory, "hotkey.jsonl.1")
                    os.close(backup)
                    os.replace("hotkey.jsonl", "hotkey.jsonl.1", src_dir_fd=directory, dst_dir_fd=directory)
                    fd = _file(directory, "hotkey.jsonl")
                with os.fdopen(fd, "ab") as output:
                    fd = -1
                    output.write(line)
            finally:
                if fd != -1:
                    os.close(fd)
        finally:
            os.close(directory)
    except (OSError, ValueError):
        # An unavailable disk or a simultaneous diagnostic never blocks dictation.
        pass


def silence_process() -> None:
    """Permanently discard Python, native and child stdout/stderr.

    Only for the standalone --hotkey process, never the threaded server. Keeping
    the sink through interpreter shutdown also covers backend atexit handlers
    and native buffers flushed after main returns. Tests must use a subprocess.
    """
    sink = open(os.devnull, "w")
    try:
        for stream in (sys.stdout, sys.stderr):
            stream.flush()
        for number in (1, 2):
            os.dup2(sink.fileno(), number)
    except BaseException:
        sink.close()
        raise
    # These references intentionally keep the sink open until interpreter exit.
    sys.stdout = sys.stderr = sink
