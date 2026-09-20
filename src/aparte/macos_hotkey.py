"""macOS global keyboard shortcut — façade, parser and dispatcher (M5).

On Linux the shortcut lives in the desktop's gsettings and spawns a fresh CLI
recorder (:mod:`aparte.hotkey`, :mod:`aparte.session`). macOS has no such store:
the shortcut must be registered by a **running process** through Carbon's
``RegisterEventHotKey`` — the one global-shortcut API that needs *no* "Input
Monitoring" permission (unlike ``CGEventTap`` / ``pynput``). The resident desktop
server is that process, and it drives the in-memory
:class:`~aparte.macos_recording.RecordingController` directly, in-process — no HTTP
route (Darwin invariant M3).

This module is three things:

1. :func:`register_hotkey` — the façade. A pure spec (``"ctrl+opt+d"``) in, a
   :class:`HotkeyHandle` out, or a :class:`HotkeyError` **carrying the raw
   ``OSStatus``** when macOS refuses the combination (already taken, reserved).
   The real Carbon backend is imported **lazily** and **injected** in tests, so
   this module stays importable and fully testable on the Linux dev machine.
2. :func:`normalize_hotkey` / :func:`hotkey_label` — the canonical macOS combo
   format (``mod+mod+key``), distinct from the gsettings accelerators
   (``<Super>space``) Linux uses.
3. :class:`HotkeyDispatcher` — the correction at the heart of M5. The Carbon
   callback must never block the run loop and must **filter repeats at arrival**,
   not at execution (see the class docstring for the bug it closes).

The Carbon backend itself (PortAudio-adjacent native code) cannot run on Linux;
its behaviour on a real ``NSApplication`` run loop is verified by hand in the M8
smoke suite. Everything above it is proven here by injected fakes.
"""

from __future__ import annotations

import sys
import threading
import time
from dataclasses import dataclass
from typing import Callable

from .notify import notify

# Default combination: ⌃⌥D. Mnemonic for "dictée", avoids the ⌘-heavy space most
# apps use, and dodges the reserved combos (Spotlight ⌘Space, input sources
# ⌃Space, Apple dictation Fn-D, screenshots ⇧⌘3/4/5). Confirmed on a real Mac in
# M8 — a clash surfaces as a register failure, observable via /api/hotkey-state.
DEFAULT_HOTKEY = "ctrl+opt+d"

# Same window as the controller's internal debounce: two presses this close are
# one intent. Here it filters at *arrival* (see HotkeyDispatcher), which is what
# actually fixes the double-press bug; the controller's guard stays as a backstop.
_DEBOUNCE_SECONDS = 0.25

# How long dispatcher.close() waits for an in-flight toggle() before giving up. A
# bounded join: the worker is a daemon, so a wedged toggle can't hold up exit.
_CLOSE_JOIN_SECONDS = 5.0

# -- Carbon constants -------------------------------------------------------------
# Kept as plain data so parsing, resolving and the pressed-only contract are all
# testable without importing Carbon. Values are the documented four-char codes and
# masks from <HIToolbox/Events.h> / <MacTypes.h>.
_NO_ERR = 0
_EVENT_NOT_HANDLED = -9874  # eventNotHandledErr, CarbonEventsCore.h
_K_EVENT_CLASS_KEYBOARD = 0x6B657962   # 'keyb'
_K_EVENT_HOTKEY_PRESSED = 6
_K_EVENT_HOTKEY_RELEASED = 7           # deliberately never subscribed to
_K_EVENT_PARAM_DIRECT_OBJECT = 0x2D2D2D2D  # '----'
_TYPE_EVENT_HOTKEY_ID = 0x686B6964     # 'hkid'
_HOTKEY_SIGNATURE = 0x41505254         # 'APRT'

# Carbon modifier masks (the low word of the classic event modifiers).
_MOD_MASKS = {
    "cmd": 0x0100,
    "shift": 0x0200,
    "opt": 0x0800,
    "ctrl": 0x1000,
}

# Aliases accepted on input, folded to the four canonical modifier names above.
_MOD_ALIASES = {
    "cmd": "cmd", "command": "cmd", "⌘": "cmd", "super": "cmd", "meta": "cmd", "win": "cmd",
    "ctrl": "ctrl", "control": "ctrl", "⌃": "ctrl",
    "opt": "opt", "option": "opt", "alt": "opt", "⌥": "opt",
    "shift": "shift", "⇧": "shift",
}

# Apple's display order for modifiers (⌃⌥⇧⌘) — used for both the canonical string
# and the pretty label so the two never drift.
_MOD_ORDER = ("ctrl", "opt", "shift", "cmd")
_MOD_SYMBOLS = {"ctrl": "⌃", "opt": "⌥", "shift": "⇧", "cmd": "⌘"}

# The keys a global shortcut realistically binds: letters, digits, space, the
# three edit keys, and the function row. ANSI virtual keycodes from Events.h.
_KEYCODES = {
    "a": 0x00, "b": 0x0B, "c": 0x08, "d": 0x02, "e": 0x0E, "f": 0x03, "g": 0x05,
    "h": 0x04, "i": 0x22, "j": 0x26, "k": 0x28, "l": 0x25, "m": 0x2E, "n": 0x2D,
    "o": 0x1F, "p": 0x23, "q": 0x0C, "r": 0x0F, "s": 0x01, "t": 0x11, "u": 0x20,
    "v": 0x09, "w": 0x0D, "x": 0x07, "y": 0x10, "z": 0x06,
    "0": 0x1D, "1": 0x12, "2": 0x13, "3": 0x14, "4": 0x15,
    "5": 0x17, "6": 0x16, "7": 0x1A, "8": 0x1C, "9": 0x19,
    "space": 0x31, "return": 0x24, "tab": 0x30, "escape": 0x35,
    "f1": 0x7A, "f2": 0x78, "f3": 0x63, "f4": 0x76, "f5": 0x60, "f6": 0x61,
    "f7": 0x62, "f8": 0x64, "f9": 0x65, "f10": 0x6D, "f11": 0x67, "f12": 0x6F,
}

# Aliases for the named keys; single characters map to themselves.
_KEY_ALIASES = {
    "spacebar": "space", "⎵": "space",
    "enter": "return", "↩": "return",
    "⇥": "tab",
    "esc": "escape", "⎋": "escape",
}

# How each key prints in a label. Letters upper-case, digits as-is, the rest named.
_KEY_LABELS = {
    "space": "Space", "return": "Return", "tab": "Tab", "escape": "Esc",
}


class HotkeyError(Exception):
    """A shortcut could not be registered.

    ``status`` is the raw Carbon ``OSStatus`` when macOS refused the combination
    (already taken, reserved), or ``None`` when the spec itself was invalid or no
    native backend was available. doctor and the tray surface it as-is.
    """

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class HotkeyState:
    """A snapshot of the global shortcut's registration, read by the read-only
    ``GET /api/hotkey-state`` route and by ``doctor``.

    :func:`~aparte.macos_runloop.serve_macos` owns it and publishes a fresh
    (frozen) instance on the handler class — once before serving, again once
    registration is attempted — so a reader always sees a consistent snapshot
    rather than half-updated fields. ``status`` mirrors :class:`HotkeyError`'s: a
    raw ``OSStatus`` when macOS refused the combination, ``None`` for a bad spec.
    """

    registered: bool = False
    configured_key: str | None = None
    status: int | None = None
    error: str | None = None


# -- Parsing ----------------------------------------------------------------------


def _parse(spec: str) -> tuple[list[str], str]:
    """Split a combo into (canonical modifiers in display order, canonical key).

    Raises :class:`HotkeyError` (``status=None``) on anything unusable: no
    modifier, no key, two keys, or an unknown token. A global shortcut needs at
    least one modifier — a bare key would be grabbed system-wide.
    """
    if not spec or not spec.strip():
        raise HotkeyError("empty shortcut")
    tokens = [t.strip().lower() for t in spec.split("+") if t.strip()]
    if not tokens:
        raise HotkeyError(f"unusable shortcut: {spec!r}")

    mods: list[str] = []
    key: str | None = None
    for token in tokens:
        if token in _MOD_ALIASES:
            canonical = _MOD_ALIASES[token]
            if canonical not in mods:
                mods.append(canonical)
            continue
        resolved = _KEY_ALIASES.get(token, token)
        if resolved not in _KEYCODES:
            raise HotkeyError(f"unknown key in shortcut: {token!r}")
        if key is not None:
            raise HotkeyError(f"a shortcut has one key, got {key!r} and {resolved!r}")
        key = resolved

    if key is None:
        raise HotkeyError(f"shortcut has no key: {spec!r}")
    if not mods:
        raise HotkeyError(f"a global shortcut needs a modifier: {spec!r}")
    ordered = [m for m in _MOD_ORDER if m in mods]
    return ordered, key


def normalize_hotkey(spec: str) -> str:
    """Canonical macOS combo string, e.g. ``"alt+Ctrl+D"`` → ``"ctrl+opt+d"``."""
    mods, key = _parse(spec)
    return "+".join([*mods, key])


def hotkey_label(spec: str) -> str:
    """Pretty label for the UI/doctor, e.g. ``"ctrl+opt+d"`` → ``"⌃⌥D"``."""
    mods, key = _parse(spec)
    symbols = "".join(_MOD_SYMBOLS[m] for m in mods)
    if key in _KEY_LABELS:
        return symbols + _KEY_LABELS[key]
    return symbols + key.upper()


def safe_hotkey_label(spec: str) -> str:
    """:func:`hotkey_label`, but returns the raw spec instead of raising on a bad
    combo. A hand-edited config or a refused registration can carry an unparseable
    spec, and a label is for display only — it must never raise into a diagnostic
    or notification path.
    """
    try:
        return hotkey_label(spec)
    except HotkeyError:
        return spec


def _resolve(spec: str) -> tuple[int, int]:
    """Canonical combo → (virtual keycode, Carbon modifier mask) for the backend."""
    mods, key = _parse(spec)
    mask = 0
    for m in mods:
        mask |= _MOD_MASKS[m]
    return _KEYCODES[key], mask


def subscribed_events() -> tuple[tuple[int, int], ...]:
    """The (eventClass, eventKind) pairs the hotkey handler subscribes to.

    Pressed only. A hotkey that also fired on release would call ``toggle()``
    twice per keypress. Exposed as data so a Linux test can guard "pressed-only"
    without importing Carbon; the real backend builds its EventTypeSpec from this.
    """
    return ((_K_EVENT_CLASS_KEYBOARD, _K_EVENT_HOTKEY_PRESSED),)


# -- Façade -----------------------------------------------------------------------


class HotkeyHandle:
    """A live registration. Keep it, then :meth:`unregister` on teardown."""

    def __init__(self, backend, token, spec: str, keycode: int, modifiers: int) -> None:
        self._backend = backend
        self._token = token
        self.spec = spec
        self.keycode = keycode
        self.modifiers = modifiers
        self._unregistered = False

    def unregister(self) -> None:
        # Idempotent: teardown may run more than once (finally + atexit), and a
        # double UnregisterEventHotKey on the same ref is undefined.
        if self._unregistered:
            return
        self._unregistered = True
        self._backend.unregister(self._token)


def register_hotkey(spec: str, on_trigger: Callable[[], None], *, backend=None) -> HotkeyHandle:
    """Register the global shortcut, calling ``on_trigger()`` on each press.

    ``on_trigger`` is expected to be fast and non-blocking — in the app it is a
    :class:`HotkeyDispatcher`'s ``trigger``, which only timestamps and wakes a
    worker, so the run loop is never held. A bad spec raises :class:`HotkeyError`
    before any backend call; a backend that returns a non-zero ``OSStatus`` raises
    :class:`HotkeyError` carrying that status.
    """
    keycode, modifiers = _resolve(spec)          # HotkeyError on a bad spec
    canonical = normalize_hotkey(spec)
    if backend is None:
        backend = _carbon_backend()              # lazy, macOS-only
    status, token = backend.register(keycode, modifiers, on_trigger)
    if status != _NO_ERR:
        raise HotkeyError(
            f"macOS refused the shortcut {hotkey_label(canonical)} (OSStatus {status})",
            status=status,
        )
    return HotkeyHandle(backend, token, canonical, keycode, modifiers)


# -- Dispatcher -------------------------------------------------------------------


class HotkeyDispatcher:
    """Serialises hotkey presses onto one worker, debounced **at arrival**.

    The bug this closes: a "thread per press" is wrong. ``controller.toggle()``
    samples the clock *after* taking its lock and holds that lock through the
    start I/O (import sounddevice, ``stream.start()``, beeps). Two quick presses
    then stack as blocked threads; when the second finally acquires the lock, more
    than 250 ms have passed, it clears the controller's internal debounce, the
    state is now RECORDING — and it **stops the recording the first just started**.
    The lock serialises, it does not filter intent. A capacity-1 queue does not
    help either: the second event still runs after the start and becomes a STOP.

    The fix is to filter *when the event arrives*, before any work:

    - The Carbon callback calls :meth:`trigger` (fast, non-blocking).
    - ``trigger`` takes the monotonic time **under the internal lock**, decides
      accept/reject there (``arrival − last_accepted < debounce`` → dropped), and
      wakes the worker **only if accepted**. It never accumulates a counter.
    - One resident worker calls ``on_toggle()`` in series, off the run loop. It
      never recomputes the debounce against its own execution time.
    - After :meth:`close`, triggers are ignored and the worker is joined (bounded)
      so no ``toggle()`` is in flight when the controller is shut down.
    """

    def __init__(
        self,
        on_toggle: Callable[[], None],
        *,
        debounce_seconds: float = _DEBOUNCE_SECONDS,
        clock: Callable[[], float] = time.monotonic,
        join_timeout: float = _CLOSE_JOIN_SECONDS,
    ) -> None:
        self._on_toggle = on_toggle
        self._debounce = debounce_seconds
        self._clock = clock
        self._join_timeout = join_timeout

        self._cond = threading.Condition(threading.Lock())
        self._pending = False        # one accepted-but-unhandled trigger, collapsed
        self._closing = False
        self._last_accepted: float | None = None
        self._worker: threading.Thread | None = None

    def trigger(self) -> None:
        """Called by the Carbon callback on each press. Accept/reject at arrival."""
        with self._cond:
            if self._closing:
                return
            now = self._clock()
            if self._last_accepted is not None and now - self._last_accepted < self._debounce:
                return  # a repeat within the window — dropped before any work
            self._last_accepted = now
            self._pending = True
            if self._worker is None:
                self._worker = threading.Thread(
                    target=self._run, name="aparte-hotkey", daemon=True
                )
                self._worker.start()
            self._cond.notify()

    def _run(self) -> None:
        while True:
            with self._cond:
                while not self._pending and not self._closing:
                    self._cond.wait()
                if self._closing and not self._pending:
                    return
                self._pending = False
            # Outside the lock: toggle() is slow (start I/O) and may block; holding
            # the lock here would defeat the arrival-time filter in trigger().
            try:
                self._on_toggle()
            except Exception as exc:  # a toggle() bug must not kill the worker
                _notify_toggle_failure(exc)

    def close(self) -> None:
        """Stop accepting, then join the worker (bounded) so no toggle() is live."""
        with self._cond:
            self._closing = True
            self._cond.notify_all()
            worker = self._worker
        if worker is not None:
            worker.join(self._join_timeout)


def _notify_toggle_failure(exc: Exception) -> None:
    # The shortcut worker must survive a toggle() error and keep listening. stderr
    # is swallowed by launchd for a login-item server, so the notification is the
    # real feedback — same critical tone as the controller's own error notice.
    print(f"aparte: dictation shortcut failed: {exc}", file=sys.stderr)
    try:
        notify("⚠️ Dictée échouée", f"{exc} Rien n'a été inséré ; réessaie.", urgency="critical")
    except Exception:
        pass


# -- Real Carbon backend (macOS only, verified by hand in M8) ---------------------


# A single native handler lives for the whole process. Carbon retains its C
# function pointer, so the Python callback must outlive every individual binding.
# Rebinding must also keep one increasing ID space rather than installing another
# handler whose first ID collides with the still-active shortcut.
_CARBON_BACKEND = None
_CARBON_BACKEND_LOCK = threading.Lock()


def _carbon_backend():
    """Lazily create and retain the application's one Carbon event handler."""
    global _CARBON_BACKEND
    with _CARBON_BACKEND_LOCK:
        if _CARBON_BACKEND is None:
            _CARBON_BACKEND = _CarbonBackend()
        return _CARBON_BACKEND


class _CarbonBackend:
    """ctypes binding over ``RegisterEventHotKey`` / ``InstallEventHandler``.

    One application-wide event handler, subscribed to :func:`subscribed_events`
    (pressed only), routes each hotkey by its integer id to the matching
    ``on_trigger``. Handles and the C callback are kept alive on the instance;
    losing the ``CFUNCTYPE`` object to the GC would crash the run loop.
    """

    def __init__(self) -> None:
        import ctypes

        self._ctypes = ctypes
        self._carbon = ctypes.CDLL(
            "/System/Library/Frameworks/Carbon.framework/Carbon"
        )
        # Built once, then reused everywhere: ctypes matches an argument against an
        # argtype by class identity, so a struct class rebuilt per call would be
        # rejected by the very signature declared for it.
        self._EventTypeSpec, self._EventHotKeyID = self._structs()
        self._HANDLER = ctypes.CFUNCTYPE(
            ctypes.c_int32, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p
        )
        self._declare_signatures()
        self._triggers: dict[int, Callable[[], None]] = {}
        self._refs: dict[int, object] = {}
        self._next_id = 1
        self._handler_ref = None
        self._callback = None  # the CFUNCTYPE, kept alive
        self._install_handler()

    # -- ctypes structs ------------------------------------------------------------

    def _structs(self):
        ctypes = self._ctypes

        class EventTypeSpec(ctypes.Structure):
            _fields_ = [("eventClass", ctypes.c_uint32), ("eventKind", ctypes.c_uint32)]

        class EventHotKeyID(ctypes.Structure):
            _fields_ = [("signature", ctypes.c_uint32), ("id", ctypes.c_uint32)]

        return EventTypeSpec, EventHotKeyID

    def _declare_signatures(self) -> None:
        """Pin every Carbon prototype before any of them is called.

        Undeclared, ctypes assumes an ``int`` return and ``int`` arguments — 32
        bits. ``GetApplicationEventTarget`` then hands back a **pointer truncated
        to its low half**, and passing that on segfaults inside Carbon before the
        first registration ever completes. Observed on Big Sur in M8; nothing off a
        Mac can exercise it, so :func:`test_carbon_backend_declares_pointer_widths`
        pins the declarations themselves.

        The widths are the 64-bit ones: ``ItemCount`` and ``ByteCount`` are
        ``unsigned long``, not ``UInt32``.
        """
        ctypes = self._ctypes
        carbon = self._carbon
        void_p = ctypes.c_void_p

        carbon.GetApplicationEventTarget.restype = void_p
        carbon.GetApplicationEventTarget.argtypes = []

        carbon.InstallEventHandler.restype = ctypes.c_int32
        carbon.InstallEventHandler.argtypes = [
            void_p,                                # EventTargetRef
            self._HANDLER,                         # EventHandlerUPP
            ctypes.c_ulong,                        # ItemCount inNumTypes
            ctypes.POINTER(self._EventTypeSpec),   # const EventTypeSpec *inList
            void_p,                                # void *inUserData
            ctypes.POINTER(void_p),                # EventHandlerRef *outRef
        ]

        carbon.RegisterEventHotKey.restype = ctypes.c_int32
        carbon.RegisterEventHotKey.argtypes = [
            ctypes.c_uint32,          # UInt32 inHotKeyCode
            ctypes.c_uint32,          # UInt32 inHotKeyModifiers
            self._EventHotKeyID,      # EventHotKeyID inHotKeyID, by value
            void_p,                   # EventTargetRef inTarget
            ctypes.c_uint32,          # OptionBits inOptions
            ctypes.POINTER(void_p),   # EventHotKeyRef *outRef
        ]

        carbon.UnregisterEventHotKey.restype = ctypes.c_int32
        carbon.UnregisterEventHotKey.argtypes = [void_p]

        carbon.GetEventParameter.restype = ctypes.c_int32
        carbon.GetEventParameter.argtypes = [
            void_p,                                 # EventRef inEvent
            ctypes.c_uint32,                        # EventParamName inName
            ctypes.c_uint32,                        # EventParamType inDesiredType
            void_p,                                 # EventParamType *outActualType
            ctypes.c_ulong,                         # ByteCount inBufferSize
            void_p,                                 # ByteCount *outActualSize
            ctypes.POINTER(self._EventHotKeyID),    # void *outData
        ]

    def _install_handler(self) -> None:
        ctypes = self._ctypes
        EventHotKeyID = self._EventHotKeyID

        def _on_event(next_handler, event, user_data):
            try:
                hk_id = EventHotKeyID()
                status = self._carbon.GetEventParameter(
                    event,
                    _K_EVENT_PARAM_DIRECT_OBJECT,
                    _TYPE_EVENT_HOTKEY_ID,
                    None,
                    ctypes.sizeof(hk_id),
                    None,
                    ctypes.byref(hk_id),
                )
                if status != _NO_ERR or int(hk_id.signature) != _HOTKEY_SIGNATURE:
                    return _EVENT_NOT_HANDLED
                trigger = self._triggers.get(int(hk_id.id))
                if trigger is None:
                    return _EVENT_NOT_HANDLED
                trigger()
                return _NO_ERR
            except Exception:
                # Never let Python escape into Carbon, or swallow another
                # component's event when ours could not decode/handle it.
                return _EVENT_NOT_HANDLED

        self._callback = self._HANDLER(_on_event)
        spec = (self._EventTypeSpec * 1)()
        (event_class, event_kind), = subscribed_events()
        spec[0].eventClass = event_class
        spec[0].eventKind = event_kind

        handler_ref = ctypes.c_void_p()
        target = self._carbon.GetApplicationEventTarget()
        status = self._carbon.InstallEventHandler(
            target, self._callback, 1, spec, None, ctypes.byref(handler_ref)
        )
        if status != _NO_ERR:
            # Without the handler, RegisterEventHotKey would still succeed and the
            # shortcut would simply never fire — a dead key with a green light.
            raise HotkeyError(
                f"macOS refused the hotkey event handler (OSStatus {status})",
                status=status,
            )
        self._handler_ref = handler_ref

    def register(self, keycode: int, modifiers: int, on_trigger: Callable[[], None]):
        ctypes = self._ctypes
        hotkey_id = self._next_id
        self._next_id += 1

        hk_id = self._EventHotKeyID()
        hk_id.signature = _HOTKEY_SIGNATURE
        hk_id.id = hotkey_id

        ref = ctypes.c_void_p()
        target = self._carbon.GetApplicationEventTarget()
        status = self._carbon.RegisterEventHotKey(
            keycode, modifiers, hk_id, target, 0, ctypes.byref(ref)
        )
        if status == _NO_ERR:
            self._triggers[hotkey_id] = on_trigger
            self._refs[hotkey_id] = ref
        return int(status), hotkey_id

    def unregister(self, token) -> None:
        ref = self._refs.pop(token, None)
        self._triggers.pop(token, None)
        if ref is not None:
            try:
                self._carbon.UnregisterEventHotKey(ref)
            except Exception:
                pass
