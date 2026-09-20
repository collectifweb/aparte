"""Private, short-lived storage for failed dictations.

A claim excludes retries, deletion and expiry across processes. Its original
expiry is never extended. No transcript or source filename appears in listings.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import fcntl
import json
import math
import os
from pathlib import Path
import re
import shutil
import stat
import time
from typing import Iterator
import uuid

from .session import get_runtime_dir

RETENTION_SECONDS = 3600
_ID = re.compile(r"[0-9a-f]{32}\Z")
_SUFFIX = re.compile(r"\.[a-zA-Z0-9]{1,8}\Z")


class RecoveryError(RuntimeError):
    pass


class RecoveryBusy(RecoveryError):
    pass


class RecoveryNotFound(RecoveryError):
    pass


@dataclass
class RecoveryItem:
    id: str
    audio_path: Path
    raw_text: str | None
    created_at: float
    expires_at: float
    _directory: Path


def _root() -> Path:
    parent = get_runtime_dir()
    root = parent / "recovery"
    if root.is_symlink():
        raise RecoveryError("Dossier de récupération non sûr.")
    root.mkdir(mode=0o700, exist_ok=True)
    if root.stat().st_uid != os.getuid():
        raise RecoveryError("Dossier de récupération appartenant à un autre compte.")
    root.chmod(0o700)
    return root


def _directory(identifier: str) -> Path:
    if not isinstance(identifier, str) or not _ID.fullmatch(identifier):
        raise RecoveryNotFound("Dictée à récupérer introuvable.")
    directory = _root() / identifier
    if directory.is_symlink() or not directory.is_dir():
        raise RecoveryNotFound("Dictée à récupérer introuvable.")
    return directory


def _open(path: Path, flags: int) -> int:
    fd = os.open(path, flags | os.O_NOFOLLOW, 0o600)
    if not stat.S_ISREG(os.fstat(fd).st_mode):
        os.close(fd)
        raise RecoveryError("Fichier de récupération non sûr.")
    return fd


def _read(path: Path) -> str:
    with os.fdopen(_open(path, os.O_RDONLY), "r", encoding="utf-8") as stream:
        return stream.read()


def _write(path: Path, text: str) -> None:
    with os.fdopen(_open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL), "w", encoding="utf-8") as stream:
        stream.write(text)


@contextmanager
def _locked(directory: Path, *, require_metadata: bool = True) -> Iterator[None]:
    # The directory exists before any metadata or timestamp file. Lock its
    # inode directly, so cleanup can also claim an interrupted mkdir -> write
    # without creating/replacing a lock inode while another writer uses it.
    try:
        fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except FileNotFoundError as exc:
        raise RecoveryNotFound("Dictée à récupérer introuvable.") from exc
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RecoveryBusy("Cette dictée est déjà en cours de récupération.") from exc
        # A previous claimant may have deleted the directory before this lock.
        if require_metadata and not (directory / "metadata.json").exists():
            raise RecoveryNotFound("Dictée à récupérer introuvable.")
        yield
    finally:
        os.close(fd)


def _metadata(directory: Path) -> dict:
    try:
        data = json.loads(_read(directory / "metadata.json"))
        if not isinstance(data, dict):
            raise ValueError("metadata must be an object")
        suffix = data.get("suffix", "")
        if not isinstance(suffix, str) or not _SUFFIX.fullmatch(suffix):
            raise ValueError("invalid audio suffix")
        for key in ("created_at", "expires_at"):
            value = data.get(key)
            # bool is an int subclass; JSON NaN/Infinity are accepted by the
            # decoder, but must never produce an immortal capture.
            if type(value) not in (int, float) or not math.isfinite(value):
                raise ValueError("invalid timestamp")
        if data["created_at"] < 0 or not 0 < data["expires_at"] - data["created_at"] <= RETENTION_SECONDS:
            raise ValueError("invalid retention period")
    except (ValueError, OverflowError) as exc:
        raise RecoveryError("Métadonnées de récupération invalides.") from exc
    return data


def _fallback_expiry(directory: Path) -> float:
    # The empty timestamp file is created once, before copying audio. Reading,
    # retrying and saving raw text never touch its mtime. If interrupted before
    # its creation, the directory's own mtime is the only available timestamp.
    try:
        info = (directory / "lock").lstat()
        if not stat.S_ISREG(info.st_mode):
            info = directory.lstat()
    except FileNotFoundError:
        info = directory.lstat()
    return info.st_mtime + RETENTION_SECONDS


def _remove(directory: Path) -> None:
    # rmtree does not follow symlinks inside this private directory.
    shutil.rmtree(directory)


@contextmanager
def save_and_claim(path: Path, raw_text: str | None = None) -> Iterator[RecoveryItem]:
    """Create a private copy and hold its claim continuously through processing.

    Creation failures remove only the incomplete copy. Once yielded, a caller's
    failure preserves the capture, exactly like ``claim``. This closes the gap
    where a listed new entry could be deleted before its creator claimed it.
    """
    sweep()
    identifier = uuid.uuid4().hex
    directory = _root() / identifier
    directory.mkdir(mode=0o700)
    now = time.time()
    suffix = path.suffix if _SUFFIX.fullmatch(path.suffix) else ".wav"
    with _locked(directory, require_metadata=False):
        try:
            # A stable creation timestamp, not a second synchronization lock.
            _write(directory / "lock", "")
            _write(directory / "metadata.json", json.dumps({
                "created_at": now, "expires_at": now + RETENTION_SECONDS,
                "suffix": suffix,
            }))
            with os.fdopen(_open(path, os.O_RDONLY), "rb") as source:
                with os.fdopen(_open(directory / ("audio" + suffix), os.O_WRONLY | os.O_CREAT | os.O_EXCL), "wb") as target:
                    shutil.copyfileobj(source, target)
            if raw_text is not None:
                _write(directory / "raw.txt", raw_text)
        except Exception:
            _remove(directory)
            raise
        # Deliberately outside the creation-cleanup try: a transcriber or caller
        # failing after yield must leave this complete backup recoverable.
        yield RecoveryItem(identifier, directory / ("audio" + suffix), raw_text,
                           now, now + RETENTION_SECONDS, directory)


def save_failure(path: Path, raw_text: str | None = None) -> str:
    """Copy a failed capture; the caller removes its original only on success."""
    with save_and_claim(path, raw_text) as item:
        return item.id


@contextmanager
def claim(identifier: str) -> Iterator[RecoveryItem]:
    """Hold this context through processing and delivery; no competing retry."""
    directory = _directory(identifier)
    with _locked(directory):
        data = _metadata(directory)
        if data["expires_at"] <= time.time():
            _remove(directory)
            raise RecoveryNotFound("Cette dictée a expiré après une heure.")
        audio = directory / ("audio" + data["suffix"])
        # Reject substituted symlinks before handing a path to the transcriber.
        fd = _open(audio, os.O_RDONLY)
        os.close(fd)
        raw = _read(directory / "raw.txt") if (directory / "raw.txt").exists() else None
        yield RecoveryItem(identifier, audio, raw, data["created_at"], data["expires_at"], directory)


def update_raw(item: RecoveryItem, text: str) -> None:
    """Save the successful transcript while holding its claim, without renewal."""
    temporary = item._directory / ("raw-" + uuid.uuid4().hex + ".tmp")
    try:
        _write(temporary, text)
        temporary.replace(item._directory / "raw.txt")
    finally:
        temporary.unlink(missing_ok=True)
    item.raw_text = text


def complete(item: RecoveryItem) -> None:
    """Remove a delivered capture, while still holding its claim."""
    _remove(item._directory)


def discard(identifier: str) -> None:
    with claim(identifier) as item:
        complete(item)


def sweep(now: float | None = None) -> int:
    """Expire idle captures; a claimed retry finishes before its removal."""
    now = time.time() if now is None else now
    removed = 0
    for directory in _root().iterdir():
        if not _ID.fullmatch(directory.name) or directory.is_symlink() or not directory.is_dir():
            continue
        try:
            with _locked(directory, require_metadata=False):
                try:
                    expires_at = _metadata(directory)["expires_at"]
                except (RecoveryError, OSError):
                    expires_at = _fallback_expiry(directory)
                if expires_at <= now:
                    _remove(directory)
                    removed += 1
        except (RecoveryError, OSError, ValueError):
            continue
    return removed


def entries() -> list[dict]:
    sweep()
    result = []
    for directory in _root().iterdir():
        if not _ID.fullmatch(directory.name) or directory.is_symlink() or not directory.is_dir():
            continue
        try:
            data = _metadata(directory)
            if data["expires_at"] <= time.time():
                continue
            busy = False
            try:
                with _locked(directory):
                    pass
            except RecoveryBusy:
                busy = True
            result.append({
                "id": directory.name, "created_at": data["created_at"],
                "expires_at": data["expires_at"],
                "has_text": (directory / "raw.txt").is_file(), "busy": busy,
            })
        except (RecoveryError, OSError, ValueError):
            continue
    return sorted(result, key=lambda entry: entry["created_at"], reverse=True)
