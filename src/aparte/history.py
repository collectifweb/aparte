"""The last few dictations, in private temporary storage by default.

A dictation can carry a password, a private message, a medical detail. So the
history lives in the runtime directory — tmpfs on a systemd session, wiped at
logout. macOS uses disk-backed temporary storage: entries expire after 24 hours
and are removed at the next history read or write. An application that is not
running cannot promise timed disk deletion. Persistent history does not expire.

The file is shared by every Aparté process rather than held in one: the global
hotkey runs a short-lived CLI, the desktop server is another process, and
`aparte last` a third. A file under the runtime directory needs no server to be
running and no port to be guessed.

Recording never raises. A dictation must not fail because its history could not
be written.
"""

from __future__ import annotations

import json
import fcntl
import os
import stat
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .session import get_runtime_dir
from .platform_dispatch import is_macos

LIMIT = 5
TEMPORARY_MAX_AGE_SECONDS = 24 * 60 * 60
_LOCK_TIMEOUT_SECONDS = 0.5
_LOCK_POLL_SECONDS = 0.01


def get_history_path(persist: bool = False) -> Path:
    if not persist:
        return get_runtime_dir() / "history.json"
    state_home = os.getenv("XDG_STATE_HOME")
    base = (Path(state_home).expanduser() if state_home else Path.home() / ".local" / "state") / "aparte"
    base.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Only tighten Aparté's own directory, never the caller's XDG parent. Using
    # the opened descriptor prevents chmod from following a substituted link.
    fd = os.open(base, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        if os.fstat(fd).st_uid != os.getuid():
            raise PermissionError("History directory belongs to another user")
        os.fchmod(fd, 0o700)
    finally:
        os.close(fd)
    return base / "history.json"


def entries(persist: bool = False) -> list[dict]:
    """The most recent dictations, newest first."""
    try:
        path = get_history_path(persist)
        items = _read(path)
        if persist or not is_macos():
            return items
        recent = _unexpired(items)
        if recent != items:
            # Reread after acquiring the same lock as writers: an expiry scan
            # must not erase a fresh dictation published by another instance.
            with _locked(path):
                current = _read(path)
                kept = _unexpired(current)
                if kept != current:
                    if kept:
                        _write(kept, path)
                    else:
                        path.unlink(missing_ok=True)
                return kept
        return recent
    except (OSError, ValueError, RuntimeError):
        return []


def _unexpired(items: list[dict]) -> list[dict]:
    now = time.time()
    # Unknown timestamps in legacy/malformed temporary history do not grant
    # indefinite retention. A backwards clock jump never extends the deadline.
    return [item for item in items
            if isinstance(item.get("at"), (int, float))
            and not isinstance(item["at"], bool)
            and now - TEMPORARY_MAX_AGE_SECONDS < item["at"] <= now]


def _read(path: Path) -> list[dict]:
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    except FileNotFoundError:
        return []
    with os.fdopen(fd, "r", encoding="utf-8") as stream:
        info = os.fstat(stream.fileno())
        # A concurrent replacement can unlink this already-open snapshot.
        # Zero links is safe; multiple links could expose or modify another file.
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink > 1:
            raise PermissionError("History must be a regular file belonging to this user")
        os.fchmod(stream.fileno(), 0o600)
        try:
            data = json.load(stream)
        except ValueError:
            return []
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict) and item.get("text")][:LIMIT]


def last(persist: bool = False) -> str | None:
    recent = entries(persist)
    return str(recent[0]["text"]) if recent else None


def record(text: str, persist: bool = False) -> None:
    text = text.strip()
    if not text:
        return
    try:
        # Dictating the same thing twice moves it back to the top rather than
        # filling the list with copies of itself.
        path = get_history_path(persist)
        with _locked(path):
            items = _read(path)
            if not persist and is_macos():
                items = _unexpired(items)
            kept = [item for item in items if item.get("text") != text]
            kept.insert(0, {"text": text, "at": time.time()})
            _write(kept[:LIMIT], path)
    except (OSError, ValueError, RuntimeError):
        return


def clear(persist: bool = False) -> None:
    try:
        path = get_history_path(persist)
        with _locked(path):
            path.unlink(missing_ok=True)
    except (OSError, RuntimeError):
        return


@contextmanager
def _locked(path: Path) -> Iterator[None]:
    # Keep this inode after clear: unlinking the lock would let a newcomer use
    # a different lock while an older writer still holds the original one.
    fd = os.open(path.with_suffix(".lock"), os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW
                 | os.O_NONBLOCK | os.O_CLOEXEC, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1:
            raise PermissionError("Invalid history lock")
        os.fchmod(fd, 0o600)
        deadline = time.monotonic() + _LOCK_TIMEOUT_SECONDS
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise TimeoutError("History is busy")
                time.sleep(_LOCK_POLL_SECONDS)
        yield
    finally:
        os.close(fd)


def _write(items: list[dict], path: Path) -> None:
    fd, name = tempfile.mkstemp(prefix=f".{path.name}-", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(items, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
