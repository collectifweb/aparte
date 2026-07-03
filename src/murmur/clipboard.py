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
    # Always stash the dictation in the clipboard first, so it is never lost —
    # even if the paste lands on a non-text area — and can be re-pasted by hand
    # with Ctrl+V.
    copy_text(text)
    # Then paste it with a single Ctrl+V instead of typing it out character by
    # character: the whole text lands in one atomic keystroke, so a stray click
    # or a key pressed mid-insertion cannot interleave with it or scatter it.
    if shutil.which("wtype") and os.getenv("WAYLAND_DISPLAY"):
        subprocess.run(["wtype", "-M", "ctrl", "-k", "v", "-m", "ctrl"], check=True)
        return "wtype"
    if shutil.which("xdotool") and os.getenv("DISPLAY"):
        subprocess.run(["xdotool", "key", "--clearmodifiers", "ctrl+v"], check=True)
        return "xdotool"
    raise ClipboardError(
        "No paste tool found. The dictation was copied to the clipboard — paste it "
        "with Ctrl+V. Install wtype on Wayland or xdotool on X11 for automatic paste."
    )

