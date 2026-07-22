"""System tray icon, grafted onto the desktop server.

Optional by construction. It needs PyGObject and the AppIndicator typelib, which
are system packages rather than pip ones — a virtualenv only sees them when it
was created with --system-site-packages. When they are missing, `build_tray()`
returns None and the server runs exactly as it did before, with `aparte doctor`
explaining how to get the icon back.

The indicator owns the main thread because GTK insists on it; the HTTP server
moves to a background thread. That is the only structural change to the server.
"""

from __future__ import annotations

import os
import threading
import webbrowser
from pathlib import Path

from . import history
from .clipboard import copy_text
from .config import Settings
from .session import get_active_session

ASSETS_DIR = Path(__file__).resolve().parent / "assets"
ICON_IDLE = "aparte-tray"
ICON_RECORDING = "aparte-tray-recording"
POLL_SECONDS = 1

try:
    import gi

    gi.require_version("Gtk", "3.0")
    try:
        gi.require_version("AyatanaAppIndicator3", "0.1")
        from gi.repository import AyatanaAppIndicator3 as AppIndicator
    except (ImportError, ValueError):
        gi.require_version("AppIndicator3", "0.1")
        from gi.repository import AppIndicator3 as AppIndicator
    from gi.repository import GLib, Gtk

    AVAILABLE = True
except (ImportError, ValueError):
    AVAILABLE = False


LABELS = {
    "fr": {
        "open": "Ouvrir Aparté",
        "copy": "Copier la dernière dictée",
        "settings": "Réglages",
        "quit": "Quitter",
        "idle": "Aparté",
        "recording": "Aparté — micro ouvert",
    },
    "en": {
        "open": "Open Aparté",
        "copy": "Copy the last dictation",
        "settings": "Settings",
        "quit": "Quit",
        "idle": "Aparté",
        "recording": "Aparté — microphone open",
    },
}


def _labels() -> dict[str, str]:
    # A tray menu belongs to the desktop, so it follows the desktop's language
    # rather than the browser's or the dictation setting.
    language = os.getenv("LC_ALL") or os.getenv("LC_MESSAGES") or os.getenv("LANG") or ""
    return LABELS["fr"] if language.lower().startswith("fr") else LABELS["en"]


def build_tray(url: str, settings: Settings, on_quit) -> "Tray | None":
    """The tray icon, or None when the system bindings are not installed."""
    if not AVAILABLE:
        return None
    try:
        return Tray(url, settings, on_quit)
    except Exception:
        # A missing status-notifier host, a broken theme path: the icon is a
        # convenience and must never take the app down with it.
        return None


class Tray:
    def __init__(self, url: str, settings: Settings, on_quit) -> None:
        self.url = url
        self.settings = settings
        self.on_quit = on_quit
        self.labels = _labels()
        self.recording = False

        self.indicator = AppIndicator.Indicator.new(
            "aparte",
            ICON_IDLE,
            AppIndicator.IndicatorCategory.APPLICATION_STATUS,
        )
        self.indicator.set_icon_theme_path(str(ASSETS_DIR))
        self.indicator.set_status(AppIndicator.IndicatorStatus.ACTIVE)
        self.indicator.set_title(self.labels["idle"])
        self.indicator.set_menu(self._build_menu())

    def _build_menu(self):
        menu = Gtk.Menu()
        for label, handler in (
            (self.labels["open"], self._open),
            (self.labels["copy"], self._copy_last),
            (self.labels["settings"], self._open_settings),
        ):
            item = Gtk.MenuItem(label=label)
            item.connect("activate", handler)
            menu.append(item)
        menu.append(Gtk.SeparatorMenuItem())
        quit_item = Gtk.MenuItem(label=self.labels["quit"])
        quit_item.connect("activate", self._quit)
        menu.append(quit_item)
        menu.show_all()
        return menu

    def _open(self, *_) -> None:
        webbrowser.open(self.url)

    def _open_settings(self, *_) -> None:
        webbrowser.open(f"{self.url}/#settings")

    def _copy_last(self, *_) -> None:
        text = history.last(self.settings.history_persist)
        if text:
            # Run off the UI thread: copying shells out, and a slow clipboard
            # tool would otherwise freeze the whole menu.
            threading.Thread(target=copy_text, args=(text,), daemon=True).start()

    def _quit(self, *_) -> None:
        self.on_quit()
        Gtk.main_quit()

    def _refresh(self) -> bool:
        """Follow the recording state set by the global hotkey."""
        recording = get_active_session() is not None
        if recording != self.recording:
            self.recording = recording
            self.indicator.set_icon_full(
                ICON_RECORDING if recording else ICON_IDLE,
                self.labels["recording" if recording else "idle"],
            )
            self.indicator.set_title(self.labels["recording" if recording else "idle"])
        return True

    def run(self) -> None:
        import signal

        # PyGObject swallows Ctrl+C once the GTK loop owns the main thread.
        signal.signal(signal.SIGINT, signal.SIG_DFL)
        GLib.timeout_add_seconds(POLL_SECONDS, self._refresh)
        Gtk.main()
