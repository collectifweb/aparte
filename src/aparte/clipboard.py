from __future__ import annotations

import os
import shutil
import subprocess

from .platform_dispatch import is_macos


class ClipboardError(RuntimeError):
    pass


def copy_text(text: str) -> str:
    if is_macos():
        # pbcopy ships with macOS, so there is no tool to look for.
        subprocess.run(["pbcopy"], input=text, text=True, check=True)
        return "pbcopy"
    if shutil.which("wl-copy") and os.getenv("WAYLAND_DISPLAY"):
        subprocess.run(["wl-copy"], input=text, text=True, check=True)
        return "wl-copy"
    if shutil.which("xclip"):
        subprocess.run(["xclip", "-selection", "clipboard"], input=text, text=True, check=True)
        return "xclip"
    if shutil.which("xsel"):
        subprocess.run(["xsel", "--clipboard", "--input"], input=text, text=True, check=True)
        return "xsel"
    raise ClipboardError("No clipboard tool found. Install wl-clipboard, xclip, or xsel.")


PASTE_MODES = ("clipboard", "terminal", "direct")


def paste_text(text: str, mode: str = "clipboard") -> str:
    """Insert the dictation into whatever window has focus.

    clipboard — a single Ctrl+V. The default, and right nearly everywhere.
    terminal  — Ctrl+Shift+V, the paste shortcut terminals actually listen to;
                Ctrl+V in a terminal does nothing at all.
    direct    — type it out, for the applications that ignore a synthetic paste
                (LibreOffice, some Electron apps).
    """
    # Always stash the dictation in the clipboard first, so it is never lost —
    # even if the paste lands on a non-text area — and can be re-pasted by hand.
    copy_text(text)
    on_wayland = bool(shutil.which("wtype") and os.getenv("WAYLAND_DISPLAY"))
    on_x11 = bool(shutil.which("xdotool") and os.getenv("DISPLAY"))

    if mode == "direct":
        if on_wayland:
            subprocess.run(["wtype", text], check=True)
            return "wtype"
        if on_x11:
            subprocess.run(["xdotool", "type", "--clearmodifiers", "--", text], check=True)
            return "xdotool"
    else:
        # One atomic keystroke rather than one per character: a stray click or a
        # key pressed mid-insertion cannot interleave with it or scatter it.
        shift = mode == "terminal"
        if on_wayland:
            hold = ["-M", "ctrl"] + (["-M", "shift"] if shift else [])
            release = (["-m", "shift"] if shift else []) + ["-m", "ctrl"]
            subprocess.run(["wtype", *hold, "-k", "v", *release], check=True)
            return "wtype"
        if on_x11:
            combo = "ctrl+shift+v" if shift else "ctrl+v"
            subprocess.run(["xdotool", "key", "--clearmodifiers", combo], check=True)
            return "xdotool"

    raise ClipboardError(
        "No paste tool found. The dictation was copied to the clipboard — paste it "
        "with Ctrl+V. Install wtype on Wayland or xdotool on X11 for automatic paste."
    )

