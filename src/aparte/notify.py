from __future__ import annotations

import shutil
import subprocess

APP_NAME = "Aparté"


def notify(title: str, message: str = "", *, urgency: str = "normal") -> bool:
    """Show a Linux desktop notification via ``notify-send``.

    Best-effort: returns ``False`` and stays silent when ``notify-send`` is not
    installed or the call fails, so dictation never breaks just because the
    notification daemon is missing. ``urgency`` is one of ``low``, ``normal``,
    or ``critical``.
    """
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


def _preview(text: str, limit: int = 90) -> str:
    """Collapse a transcript to a short single-line preview for a notification."""
    snippet = " ".join(text.split())
    if len(snippet) > limit:
        snippet = snippet[: limit - 1].rstrip() + "…"
    return snippet
