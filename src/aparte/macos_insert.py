"""macOS text insertion via Quartz CGEvent.

Two paths, mirroring the Linux paste/type split in :mod:`aparte.clipboard`:

- :func:`insert_via_paste` — a synthetic **Cmd+V**, the primary path. Paired with
  ``pbcopy`` in :func:`aparte.clipboard.paste_text`, a French dictation lands
  intact in Slack, Mail, browsers and Electron apps.
- :func:`type_unicode` — direct Unicode typing (``CGEventKeyboardSetUnicodeString``),
  the fallback for the ``direct`` paste mode and for apps that ignore a paste.
  Correct for the French critical characters (``’ « » U+00A0``).

Native, so it cannot run on the Linux dev machine: the unit tests mock Quartz and
lock the **observable** contract — which events we build and post, and that we
**raise** instead of failing silently. We never claim a *silent success*: a
missing framework or an event that can't be created raises :class:`ClipboardError`.
We do **not** pretend to detect a ``CGEventPost`` failure — macOS returns no
reliable status; the real on-screen effect is verified by hand on a Mac (M8).

The caller (:func:`aparte.clipboard.paste_text`) checks Accessibility trust
**before** reaching here, so these functions assume it and only guard the Quartz
layer.
"""

from __future__ import annotations

from .clipboard import ClipboardError

# kVK_ANSI_V — the virtual key code for "v". Combined with the Command modifier
# it is Cmd+V whatever the physical keyboard layout.
_KEY_V = 9

# CGEventKeyboardSetUnicodeString carries a bounded UTF-16 buffer per event; a
# long dictation is posted in chunks so nothing is dropped. The chunk size is a
# safe margin, not a hard platform limit.
_UNICODE_CHUNK = 20


def _quartz():
    """Import Quartz, or raise a ClipboardError the notification can show as-is."""
    try:
        import Quartz
    except Exception as exc:  # ImportError, or a broken PyObjC install
        raise ClipboardError(
            "macOS insertion needs the Quartz framework — install the macOS "
            "extras with: pip install '.[macos]'"
        ) from exc
    return Quartz


def insert_via_paste() -> str:
    """Synthesise Cmd+V. Returns a backend name for logging; raises
    :class:`ClipboardError` if the events can't be built — never a silent no-op."""
    Quartz = _quartz()
    down = Quartz.CGEventCreateKeyboardEvent(None, _KEY_V, True)
    up = Quartz.CGEventCreateKeyboardEvent(None, _KEY_V, False)
    if down is None or up is None:
        raise ClipboardError("macOS could not create the Cmd+V keyboard event.")
    Quartz.CGEventSetFlags(down, Quartz.kCGEventFlagMaskCommand)
    Quartz.CGEventSetFlags(up, Quartz.kCGEventFlagMaskCommand)
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, down)
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, up)
    return "cgevent-paste"


def type_unicode(text: str) -> str:
    """Type ``text`` out as Unicode, the fallback for apps that ignore a paste.
    Posted in bounded chunks so a long dictation is preserved whole; raises
    :class:`ClipboardError` if an event can't be built."""
    Quartz = _quartz()
    for start in range(0, len(text), _UNICODE_CHUNK):
        chunk = text[start : start + _UNICODE_CHUNK]
        event = Quartz.CGEventCreateKeyboardEvent(None, 0, True)
        if event is None:
            raise ClipboardError("macOS could not create the keyboard event for typing.")
        Quartz.CGEventKeyboardSetUnicodeString(event, len(chunk), chunk)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)
    return "cgevent-type"
