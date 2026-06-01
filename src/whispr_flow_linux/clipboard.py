from __future__ import annotations

import os
import shutil
import subprocess


class ClipboardError(RuntimeError):
    pass


def copy_text(text: str) -> str:
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


def paste_text(text: str) -> str:
    if shutil.which("wtype") and os.getenv("WAYLAND_DISPLAY"):
        subprocess.run(["wtype", text], check=True)
        return "wtype"
    if shutil.which("xdotool") and os.getenv("DISPLAY"):
        subprocess.run(["xdotool", "type", "--clearmodifiers", "--", text], check=True)
        return "xdotool"
    copy_text(text)
    raise ClipboardError(
        "Direct paste tool not found. Text was copied instead. "
        "Install wtype on Wayland or xdotool on X11."
    )

