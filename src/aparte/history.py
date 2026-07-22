"""The last few dictations, kept in memory by default.

A dictation can carry a password, a private message, a medical detail. So the
history lives in the runtime directory — tmpfs on any systemd session, wiped at
logout — and only reaches the disk when the setting says so.

The file is shared by every Aparté process rather than held in one: the global
hotkey runs a short-lived CLI, the desktop server is another process, and
`aparte last` a third. A file under the runtime directory needs no server to be
running and no port to be guessed.

Recording never raises. A dictation must not fail because its history could not
be written.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from .session import get_runtime_dir

LIMIT = 5


def get_history_path(persist: bool = False) -> Path:
    if not persist:
        return get_runtime_dir() / "history.json"
    state_home = os.getenv("XDG_STATE_HOME")
    base = (Path(state_home).expanduser() if state_home else Path.home() / ".local" / "state") / "aparte"
    base.mkdir(parents=True, exist_ok=True)
    return base / "history.json"


def entries(persist: bool = False) -> list[dict]:
    """The most recent dictations, newest first."""
    try:
        data = json.loads(get_history_path(persist).read_text(encoding="utf-8"))
    except (OSError, ValueError, RuntimeError):
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
        kept = [item for item in entries(persist) if item.get("text") != text]
        kept.insert(0, {"text": text, "at": time.time()})
        _write(kept[:LIMIT], get_history_path(persist))
    except (OSError, ValueError, RuntimeError):
        return


def clear(persist: bool = False) -> None:
    try:
        get_history_path(persist).unlink(missing_ok=True)
    except (OSError, RuntimeError):
        return


def _write(items: list[dict], path: Path) -> None:
    temporary = path.with_name(f"{path.name}.tmp")
    temporary.write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
    # The runtime directory is already private; the state directory is not, and
    # nobody else on the machine has any business reading what was dictated.
    os.chmod(temporary, 0o600)
    temporary.replace(path)
