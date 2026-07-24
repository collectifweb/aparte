from __future__ import annotations

import shutil
import subprocess

from .platform_dispatch import is_macos

APP_NAME = "Aparté"


def notify(title: str, message: str = "", *, urgency: str = "normal") -> bool:
    """Show a desktop notification: ``notify-send`` on Linux, ``osascript`` on macOS.

    Best-effort: returns ``False`` and stays silent when the tool is not
    installed or the call fails, so dictation never breaks just because the
    notification daemon is missing. ``urgency`` is one of ``low``, ``normal``,
    or ``critical`` on Linux; macOS notifications have no such level, so it is
    ignored there.
    """
    if is_macos():
        return _notify_macos(title, message)
    executable = shutil.which("notify-send")
    if not executable:
        return False
    command = [
        executable,
        "--app-name",
        APP_NAME,
        "--urgency",
        urgency,
        "--expire-time",
        "2500",
        title,
    ]
    if message:
        command.append(message)
    try:
        subprocess.run(command, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception:
        return False


def _applescript_escape(text: str) -> str:
    """Quote a string for a double-quoted AppleScript literal.

    A dictation preview can hold a ``"``, a ``\\`` or a newline; unescaped, any
    of them closes the literal early and breaks the whole ``osascript`` command.
    Backslash goes first, so the escapes added afterwards are not doubled.
    """
    return (
        text.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
    )


def _notify_macos(title: str, message: str) -> bool:
    executable = shutil.which("osascript")
    if not executable:
        return False
    try:
        # Build the script inside the try too: an unexpected non-string argument
        # would make _applescript_escape raise, and notify() must never do that.
        script = (
            f'display notification "{_applescript_escape(message)}" '
            f'with title "{_applescript_escape(title)}"'
        )
        subprocess.run(
            [executable, "-e", script],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except Exception:
        return False


def _preview(text: str, limit: int = 90) -> str:
    """Collapse a transcript to a short single-line preview for a notification."""
    snippet = " ".join(text.split())
    if len(snippet) > limit:
        snippet = snippet[: limit - 1].rstrip() + "…"
    return snippet
