"""macOS menu-bar icon (M6) — what it shows, decided in pure Python.

On Mac nothing else tells the user the microphone is open: no window, and an
``accessory`` application draws nothing. During the M8 native validation the tester
pressed the shortcut, got no feedback, believed nothing had happened, pressed again
— and stopped the recording the first press had just started. The code was correct;
the silence was the defect. This module is the fix.

It is split so that everything decidable is decided **here**, without AppKit: the
labels (French and English), the elapsed-time format, and :func:`tray_view`, which
maps a controller snapshot plus the shortcut's registration state onto what the menu
bar should display. The thin ``rumps`` binding that puts it on screen lives further
down and is the only native part.

The state line, the icon and the timer are three separate signals, on purpose: the
recording state must be readable without colour (DESIGN.md, "la règle du daltonien"),
and the icons are **template** images — macOS tints them itself, black on a light
menu bar, white on a dark one. No fixed colour would do: the menu bar is translucent
over the user's wallpaper, so nothing there can be contrast-checked by calculation,
which is what DESIGN.md requires of every colour.
"""

from __future__ import annotations

import sys
import threading
import webbrowser
from dataclasses import dataclass
from pathlib import Path

from . import history
from .clipboard import copy_text
from .config import Settings
from .macos_locale import language
from .macos_hotkey import DEFAULT_HOTKEY, normalize_hotkey, safe_hotkey_label
from .macos_recording import ERROR, IDLE, PROCESSING, RECORDING
from .notify import notify

ASSETS_DIR = Path(__file__).resolve().parent / "assets"

# Template PNGs: black plus alpha, tinted by macOS. Shapes taken from the brand mark
# — the three bars at rest, a filled disc while recording — so the silhouette alone
# carries the state.
ICON_IDLE = "aparte-menubar.png"
ICON_RECORDING = "aparte-menubar-recording.png"

# The tray polls the controller this often. Fast, and deliberately **not** slowed
# down while idle: the latency that matters is idle → recording, the one that made
# the M8 tester doubt his own press, and it is governed by the tick running while
# idle. The cost is two attribute reads and a string compare, four times a second.
POLL_SECONDS = 0.25

# Shown next to the icon while transcribing. Not a spinner and not a lie about the
# microphone still being open — just a third, non-chromatic state.
PROCESSING_TITLE = "…"


LABELS = {
    "fr": {
        "idle": "Prêt à dicter",
        "recording": "Micro ouvert",
        "processing": "Transcription en cours…",
        "error": "La dernière dictée a échoué",
        "shortcut": "Raccourci : {key}",
        "shortcut_none": "Choisis ton raccourci dans ce menu",
        "shortcut_configure": "Configurer le raccourci…",
        "shortcut_prompt": "Saisis une combinaison, par exemple ctrl+opt+d. Elle démarre et arrête la dictée dans tes applications.",
        "shortcut_save": "Enregistrer",
        "cancel": "Annuler",
        "shortcut_try": "Raccourci enregistré : {key}. Appuie pour essayer. Si rien ne se passe, choisis une autre combinaison.",
        "shortcut_problem": "Raccourci non modifié",
        "shortcut_retry": "Vérifie la combinaison et réessaie.",
        "shortcut_failed": "Raccourci indisponible : {key}",
        "open": "Ouvrir Aparté",
        "copy": "Copier la dernière dictée",
        "settings": "Réglages",
        "model_prepare": "Préparer le modèle…",
        "quit": "Quitter",
        "quit_wait": "Sauvegarde avant de quitter…",
        "quit_retry": "Sauvegarde impossible — réessayer de quitter",
        "overflow": "Audio incomplet — vérifie le texte",
        "cap": "Durée maximale atteinte — vérifie le texte",
        "update_check": "Rechercher une mise à jour…",
        "update_busy": "Vérification…",
        "update_install": "Installer la version {version}",
        "update_installing": "Installation…",
        "update_done": "Mise à jour installée — relance Aparté",
        "update_notice": "Mise à jour",
        "update_current": "Aparté {version} est à jour.",
        "update_available": "Version {version} disponible. Reclique pour l'installer.",
        "update_dirty": "Le dossier a des modifications non validées.",
        "update_manual": "Aparté ne tourne pas depuis un dépôt git.",
        "update_brew": "Installé par Homebrew — mets-le à jour avec {command}",
        "update_no_upstream": "La branche ne suit aucune branche distante.",
        "update_offline": "Impossible de joindre le dépôt distant.",
        "update_error": "Lecture du dépôt impossible.",
        "update_installed": "Mise à jour installée — quitte et relance Aparté.",
        "update_failed": "Mise à jour interrompue : {detail}",
        "update_dictating": "Une dictée est en cours — réessaie après.",
    },
    "en": {
        "idle": "Ready to dictate",
        "recording": "Microphone open",
        "processing": "Transcribing…",
        "error": "The last dictation failed",
        "shortcut": "Shortcut: {key}",
        "shortcut_none": "Choose your shortcut in this menu",
        "shortcut_configure": "Set up the shortcut…",
        "shortcut_prompt": "Enter a combination, for example ctrl+opt+d. It starts and stops dictation in your applications.",
        "shortcut_save": "Save",
        "cancel": "Cancel",
        "shortcut_try": "Shortcut saved: {key}. Press it to try. If nothing happens, choose another combination.",
        "shortcut_problem": "Shortcut unchanged",
        "shortcut_retry": "Check the combination and try again.",
        "shortcut_failed": "Shortcut unavailable: {key}",
        "open": "Open Aparté",
        "copy": "Copy the last dictation",
        "settings": "Settings",
        "model_prepare": "Prepare the model…",
        "quit": "Quit",
        "quit_wait": "Saving before quitting…",
        "quit_retry": "Could not save — retry quitting",
        "overflow": "Incomplete audio — review the text",
        "cap": "Recording limit reached — review the text",
        "update_check": "Check for updates…",
        "update_busy": "Checking…",
        "update_install": "Install version {version}",
        "update_installing": "Installing…",
        "update_done": "Update installed — relaunch Aparté",
        "update_notice": "Update",
        "update_current": "Aparté {version} is up to date.",
        "update_available": "Version {version} available. Click again to install it.",
        "update_dirty": "The checkout has uncommitted changes.",
        "update_manual": "Aparté does not run from a git checkout.",
        "update_brew": "Installed with Homebrew — update it with {command}",
        "update_no_upstream": "The branch tracks no remote branch.",
        "update_offline": "Could not reach the remote.",
        "update_error": "Cannot read the checkout.",
        "update_installed": "Update installed — quit and relaunch Aparté.",
        "update_failed": "Update stopped: {detail}",
        "update_dictating": "A dictation is in progress — try again after.",
    },
}

# What the update menu item is waiting for. Two clicks, never one: an update
# reinstalls packages, and the web panel asks the same way (check, then apply).
UPDATE_CHECK = "check"      # first click: look for a release
UPDATE_INSTALL = "install"  # second click: install the one that was found
UPDATE_DONE = "done"        # installed; nothing left to do but relaunch


def labels() -> dict[str, str]:
    # A menu-bar menu belongs to the desktop, so it follows the desktop's language
    # rather than the browser's or the dictation setting — same rule as the GTK tray.
    return LABELS[language()]


def format_elapsed(seconds: float) -> str:
    """Seconds as ``m:ss``, or ``h:mm:ss`` past the hour."""
    total = max(0, int(seconds))
    minutes, secs = divmod(total, 60)
    if minutes < 60:
        return f"{minutes}:{secs:02d}"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}"


@dataclass(frozen=True)
class TrayView:
    """Everything the menu bar shows, for one poll tick."""

    icon: str
    title: str
    status: str
    shortcut: str


def _shortcut_line(hotkey_state, texts: dict[str, str]) -> str:
    """What the menu says about the global shortcut.

    Reads the **real registration**, not the configured value: saying "configured"
    would be a half-truth the day Carbon refuses the combination, and that day is
    exactly when the user needs to be told. ``None`` — no state published yet —
    reads as "no shortcut", which is what an unconfigured install has.

    The label always goes through ``safe_hotkey_label``: a hand-edited config can
    hold an unparseable combo, and a menu must never fail to draw because of it.
    """
    if hotkey_state is None or not hotkey_state.configured_key:
        return texts["shortcut_none"]
    key = safe_hotkey_label(hotkey_state.configured_key)
    template = "shortcut" if hotkey_state.registered else "shortcut_failed"
    return texts[template].format(key=key)


def tray_view(snapshot: tuple[str, float | None], hotkey_state, texts: dict[str, str]) -> TrayView:
    """Map one controller snapshot onto the icon, the title and the two menu lines.

    ``snapshot`` is taken whole — ``RecordingController.recording_snapshot()`` — and
    never re-read field by field, so the state and the duration always describe the
    same instant.
    """
    state, elapsed = snapshot
    icon = ICON_RECORDING if state == RECORDING else ICON_IDLE
    if state == RECORDING:
        # A transition landing between the two lock-free reads leaves the duration
        # unknown; the icon still says recording, and the timer joins a tick later.
        title = "" if elapsed is None else format_elapsed(elapsed)
    elif state == PROCESSING:
        title = PROCESSING_TITLE
    else:
        title = ""
    status = texts[state if state in (IDLE, RECORDING, PROCESSING, ERROR) else IDLE]
    return TrayView(icon=icon, title=title, status=status, shortcut=_shortcut_line(hotkey_state, texts))


@dataclass(frozen=True)
class UpdateDecision:
    """What the update item becomes, and what the user is told, after a step."""

    mode: str
    title: str
    message: str


def _release_name(release: str) -> str:
    """`v1.2.0` → `1.2.0`. The tag is git's spelling, not the user's."""
    return release[1:] if release.startswith("v") else release


def update_after_check(result: dict, texts: dict[str, str]) -> UpdateDecision:
    """Read `check_update()` and decide what the menu shows next.

    Every state gets a sentence — including the four that mean "no update is
    possible here" (no checkout, no upstream, offline, unreadable). A menu item that
    silently does nothing is the failure this whole lot is about.
    """
    state = str(result.get("state") or "error")
    if state == "restart_required":
        return UpdateDecision(UPDATE_DONE, texts["update_done"], texts["update_installed"])
    if state == "available" and not result.get("dirty"):
        version = _release_name(str(result.get("release") or ""))
        return UpdateDecision(
            UPDATE_INSTALL,
            texts["update_install"].format(version=version),
            texts["update_available"].format(version=version),
        )
    if state == "available":  # a release is waiting, but the checkout cannot move
        return UpdateDecision(UPDATE_CHECK, texts["update_check"], texts["update_dirty"])
    if state == "current":
        message = texts["update_current"].format(version=result.get("version") or "")
        return UpdateDecision(UPDATE_CHECK, texts["update_check"], message)
    if state == "brew":
        # Handled here rather than by the fallback below, which cannot fill in the
        # command — and the command is the whole answer.
        message = texts["update_brew"].format(command=result.get("command") or "")
        return UpdateDecision(UPDATE_CHECK, texts["update_check"], message)
    return UpdateDecision(
        UPDATE_CHECK, texts["update_check"], texts.get(f"update_{state}", texts["update_error"])
    )


def update_after_apply(lines, texts: dict[str, str], done_marker: str) -> UpdateDecision:
    """Read the install log and decide. Success is the marker, never "no error"."""
    lines = list(lines)
    if done_marker in lines:
        return UpdateDecision(UPDATE_DONE, texts["update_done"], texts["update_installed"])
    detail = next((line for line in reversed(lines) if line.strip()), "")
    return UpdateDecision(
        UPDATE_CHECK, texts["update_check"], texts["update_failed"].format(detail=detail)
    )


# -- The rumps binding (native, macOS only) ---------------------------------------

# Delay before the one-shot timer that fires on_ready. Small: the global shortcut is
# registered from there, and nothing can trigger a dictation until it is.
READY_DELAY_SECONDS = 0.05


def _rumps():
    """Import rumps, lazily. Absent off macOS, and absent without the [macos] extra."""
    import rumps

    return rumps


def _set_accessory_policy() -> None:
    """No Dock icon, no application menu — Aparté lives in the menu bar.

    rumps does not set the policy itself (it expects a bundle with LSUIElement, which
    only arrives in M7), so a plain `python -m aparte` run would otherwise grow a Dock
    icon. Native; a failure here is cosmetic and must never cost the tray.
    """
    from AppKit import NSApplication, NSApplicationActivationPolicyAccessory

    NSApplication.sharedApplication().setActivationPolicy_(NSApplicationActivationPolicyAccessory)


# What building the icon did **in this process**: None (nothing tried), "ok", or the
# reason it did not happen. Process-local on purpose, like update's restart flag: the
# CLI `doctor` runs in another process, where it stays None and the check falls back to
# what is installed. Read through :func:`tray_build_outcome`.
_BUILD_OUTCOME: str | None = None

# Reported as the outcome when the dependency is simply absent — an installation
# choice, not a failure. Same string the doctor check turns into its fix line.
MISSING_DEPENDENCY = 'pip install -e ".[macos]"'


def tray_build_outcome() -> str | None:
    """What :func:`build_tray` last did here: ``"ok"``, a reason, or None if untried."""
    return _BUILD_OUTCOME


def build_tray(url, settings, controller, hotkey_state) -> "MacTray | None":
    """The menu-bar icon, or None when it cannot exist.

    Two failure modes, deliberately treated differently. A **missing dependency** is
    an installation choice — silent fallback, and `aparte doctor` says how to get the
    icon. Anything **unexpected** is loud: M6 exists to close M8's main usability
    defect (nothing on screen says the microphone is open), so a swallowed exception
    here would quietly recreate the very bug it fixes.
    """
    global _BUILD_OUTCOME
    try:
        rumps = _rumps()
    except Exception:
        _BUILD_OUTCOME = MISSING_DEPENDENCY
        return None
    try:
        tray = MacTray(rumps, url, settings, controller, hotkey_state)
    except Exception as exc:
        _BUILD_OUTCOME = str(exc)
        print(f"aparte: could not build the menu-bar icon: {exc}", file=sys.stderr)
        try:
            notify(
                "⚠️ Pas d'icône de barre de menus",
                f"{exc} Rien n'indiquera que le micro est ouvert.",
                urgency="critical",
            )
        except Exception:
            pass
        return None
    _BUILD_OUTCOME = "ok"
    return tray


class MacTray:
    """The menu-bar icon: it **observes** the recorder, it never drives it.

    Owning the run loop. ``rumps.App.run()`` calls ``AppHelper.runEventLoop()`` — the
    very thing :func:`aparte.macos_runloop._appkit_run_loop` calls — and there is only
    one main thread. So when a tray exists, rumps runs the loop and this class
    provides :meth:`run_loop` as a drop-in for the M5 runner. ``serve_macos`` keeps
    everything else: the shortcut, the published state, the ordered teardown.

    Two hooks matter and both are handed in by ``serve_macos``:

    - ``on_ready`` — fired from a one-shot timer once the loop is live, because
      ``RegisterEventHotKey`` needs a running ``NSApplication`` to attach to;
    - ``on_quit`` — the ordered, idempotent teardown, called by the "Quit" item
      **before** terminating. ``rumps.quit_application()`` goes through
      ``NSApplication.terminate_``, which never returns from ``run()``: without this,
      the normal way out would skip the teardown entirely.
    """

    def __init__(self, rumps, url, settings, controller, hotkey_state) -> None:
        self._rumps = rumps
        self._url = url
        self._settings = settings
        self._controller = controller
        self._hotkey_state = hotkey_state
        self._texts = labels()

        self._set_hotkey = None
        self._quit_pending = False
        self._quit_item = rumps.MenuItem(self._texts["quit"], callback=self._quit)
        self._on_ready = None
        self._on_quit = None
        self._ready_fired = False
        self._ready_timer = None
        self._poll_timer = None
        self._view: TrayView | None = None

        # quit_button=None is not optional: rumps otherwise adds its own Quit item
        # wired straight to quit_application(), i.e. a visible way out that skips the
        # teardown. The only Quit in this menu is the one built below.
        self._app = rumps.App(
            "Aparté",
            title="",
            icon=str(ASSETS_DIR / ICON_IDLE),
            template=True,
            quit_button=None,
        )
        self._status_item = rumps.MenuItem("")
        self._shortcut_item = rumps.MenuItem("")
        self._update_item = rumps.MenuItem(self._texts["update_check"], callback=self._update)
        self._update_mode = UPDATE_CHECK
        self._update_busy = False
        self._update_worker: threading.Thread | None = None
        self._pending_update: UpdateDecision | None = None
        # No callback → macOS greys the item out. These two lines are read, not clicked.
        self._app.menu = [
            self._status_item,
            self._shortcut_item,
            rumps.separator,
            rumps.MenuItem(self._texts["open"], callback=self._open),
            rumps.MenuItem(self._texts["copy"], callback=self._copy_last),
            rumps.MenuItem(self._texts["settings"], callback=self._open_settings),
            rumps.MenuItem(self._texts["shortcut_configure"], callback=self._configure_hotkey),
            rumps.MenuItem(self._texts["model_prepare"], callback=self._prepare_model),
            rumps.separator,
            self._update_item,
            rumps.separator,
            self._quit_item,
        ]
        self.refresh()

    # -- The run loop -----------------------------------------------------------

    def run_loop(self, on_ready, on_quit=None) -> None:
        """Run the AppKit loop through rumps. Blocks until the app terminates."""
        self._on_ready = on_ready
        self._on_quit = on_quit
        try:
            _set_accessory_policy()
        except Exception as exc:  # a Dock icon is ugly, never fatal
            print(f"aparte: could not hide the Dock icon: {exc}", file=sys.stderr)
        # SIGINT is left alone here, unlike the plain runner: rumps installs its own
        # Mach interrupt inside run(), so anything set before would be overwritten.
        self._ready_timer = self._rumps.Timer(self._fire_ready, READY_DELAY_SECONDS)
        self._ready_timer.start()
        self._poll_timer = self._rumps.Timer(self._tick, POLL_SECONDS)
        self._poll_timer.start()
        self._hook_before_quit()
        self._app.run()

    def _fire_ready(self, _timer=None) -> None:
        # rumps.Timer repeats by construction, so the one-shot is made by hand: stop
        # first, and latch, so a raising on_ready cannot be run twice.
        if self._ready_fired:
            return
        self._ready_fired = True
        self._stop_timer(self._ready_timer)
        try:
            if self._on_ready is not None:
                self._on_ready()
        except Exception as exc:
            # serve_macos already handles a refused shortcut; this catches the rest,
            # so an unexpected failure costs the shortcut, not the whole menu bar.
            print(f"aparte: startup hook failed: {exc}", file=sys.stderr)

    def _hook_before_quit(self) -> None:
        """Second net: tear down on applicationWillTerminate_ too, if rumps has it.

        Duck-typed on purpose — `rumps.events` does not exist in every release, and an
        AttributeError at startup would cost the whole tray. The Quit item stays the
        primary path; this only catches the ways out that bypass it.
        """
        register = getattr(getattr(getattr(self._rumps, "events", None), "before_quit", None), "register", None)
        if register is None:
            return
        try:
            register(lambda *_: self._quit_hook())
        except Exception:
            pass

    def _quit_hook(self) -> bool:
        if self._on_quit is not None:
            return self._on_quit() is not False
        return True

    def close(self) -> None:
        """Stop the timers. First step of the teardown, and safe to repeat."""
        self._stop_timer(self._ready_timer)
        self._stop_timer(self._poll_timer)
        self._ready_timer = None
        self._poll_timer = None

    @staticmethod
    def _stop_timer(timer) -> None:
        if timer is None:
            return
        try:
            timer.stop()
        except Exception:
            pass

    # -- What it shows ----------------------------------------------------------

    def _tick(self, _timer=None) -> None:
        try:
            self.refresh()
            if self._quit_pending:
                self._quit()
        except Exception as exc:
            # A drawing failure must not kill the timer: it would freeze the icon on
            # a stale state, which is worse than the wrong pixel.
            print(f"aparte: could not refresh the menu bar: {exc}", file=sys.stderr)

    def refresh(self) -> None:
        """Read one snapshot and push what changed. Called four times a second."""
        pending, self._pending_update = self._pending_update, None
        if pending is not None:
            # The update worker leaves its result here rather than touching the menu
            # itself: AppKit is a main-thread affair, and this tick is the main thread.
            self._update_mode = pending.mode
            self._update_item.title = pending.title
        view = tray_view(self._controller.recording_snapshot(), self._hotkey_state(), self._texts)
        previous, self._view = self._view, view
        if previous is None or view.icon != previous.icon:
            self._app.icon = str(ASSETS_DIR / view.icon)
        if previous is None or view.title != previous.title:
            self._app.title = view.title
        if previous is None or view.status != previous.status:
            self._status_item.title = view.status
        warning = getattr(self._controller, "warning", None)
        if warning in ("overflow", "cap") and view.status == self._texts["idle"]:
            self._status_item.title = self._texts[warning]
        if previous is None or view.shortcut != previous.shortcut:
            self._shortcut_item.title = view.shortcut

    # -- Menu actions -----------------------------------------------------------

    def _open(self, _=None) -> None:
        webbrowser.open(self._url)

    def _open_settings(self, _=None) -> None:
        webbrowser.open(f"{self._url}/#settings")

    def _prepare_model(self, _=None) -> None:
        # Explicit native gesture; opening the web page never starts a download.
        def prepare():
            from .model_download import ensure_ready
            try:
                ensure_ready(Settings.from_env())
            except Exception as exc:
                try:
                    notify(self._texts["model_prepare"], str(exc), urgency="critical")
                except Exception:
                    pass
        threading.Thread(target=prepare, name="aparte-model-prepare", daemon=True).start()
        self._open()

    def set_hotkey_handler(self, callback) -> None:
        """Native-only action, installed by the owner of the Carbon registration."""
        self._set_hotkey = callback

    def _configure_hotkey(self, _=None) -> None:
        if self._set_hotkey is None:
            return
        state = self._hotkey_state()
        value = getattr(state, "configured_key", None) or DEFAULT_HOTKEY
        window = self._rumps.Window(
            title=self._texts["shortcut_configure"],
            message=self._texts["shortcut_prompt"],
            default_text=value,
            ok=self._texts["shortcut_save"], cancel=self._texts["cancel"],
        )
        response = window.run()
        if not response.clicked:
            return
        try:
            combo = normalize_hotkey(response.text)
            self._set_hotkey(combo)
        except Exception as exc:
            self._rumps.alert(title=self._texts["shortcut_problem"],
                              message=f"{self._texts['shortcut_retry']}\n{exc}")
            return
        self.refresh()
        self._rumps.alert(title=self._texts["shortcut_configure"],
                          message=self._texts["shortcut_try"].format(key=safe_hotkey_label(combo)))

    def _copy_last(self, _=None) -> None:
        text = history.last(Settings.from_env().history_persist)
        if text:
            # Off the UI thread: copying shells out, and a slow clipboard tool would
            # otherwise freeze the whole menu.
            threading.Thread(target=copy_text, args=(text,), daemon=True).start()

    def _quit(self, _=None) -> None:
        # Teardown first, terminate second: terminate_ never comes back.
        if not self._quit_hook():
            self._quit_pending = self._controller.recording_snapshot()[0] != ERROR
            self._quit_item.title = self._texts["quit_wait" if self._quit_pending else "quit_retry"]
            return
        self._quit_pending = False
        self._rumps.quit_application()

    # -- Updating ---------------------------------------------------------------

    def _update(self, _=None) -> None:
        """Menu click, on the main thread. Decide, then hand the work to a thread.

        On macOS this menu is the **only** way to update: `/api/update/apply` is 404
        on Darwin by invariant, since a route that runs git and pip over HTTP would be
        a privilege proxy.
        """
        if self._update_busy or self._update_mode == UPDATE_DONE:
            return
        state, _elapsed = self._controller.recording_snapshot()
        if state != IDLE:
            # A dictation is worth more than an update, and an update has no urgency.
            self._notify_update(self._texts["update_dictating"])
            return
        self._update_busy = True
        installing = self._update_mode == UPDATE_INSTALL
        self._update_item.title = self._texts["update_installing" if installing else "update_busy"]
        self._update_worker = threading.Thread(
            target=self._run_update, args=(installing,), name="aparte-update", daemon=True
        )
        self._update_worker.start()

    def _run_update(self, installing: bool) -> None:
        # Off the main thread: a fetch reaches the network and an install runs git and
        # pip. The result is left for the next tick to draw; only the notification
        # goes out from here, since it shells out and touches no AppKit.
        from .update import DONE_MARKER, apply_update, check_update

        try:
            if installing:
                decision = update_after_apply(apply_update(), self._texts, DONE_MARKER)
            else:
                # Reaches the network only because the user asked: opening the menu
                # never phones home on its own.
                decision = update_after_check(check_update(fetch=True), self._texts)
        except Exception as exc:
            decision = UpdateDecision(UPDATE_CHECK, self._texts["update_check"], str(exc))
        self._pending_update = decision
        self._update_busy = False
        self._notify_update(decision.message)

    def _notify_update(self, message: str) -> None:
        try:
            notify(self._texts["update_notice"], message)
        except Exception:
            pass
