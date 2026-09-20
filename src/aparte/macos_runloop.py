"""macOS run loop + global-shortcut lifecycle for the resident server (M5b).

``RegisterEventHotKey`` only delivers events while a live AppKit run loop pumps
them, and that run loop must own the main thread. So on macOS the HTTP server
moves to a daemon thread (exactly as it does under the GTK tray on Linux) and
this module runs the AppKit loop on the main thread, owning the whole shortcut
lifecycle:

    NSApplication ready → register hotkey → run loop (blocks) → ordered teardown

Since M6 the loop is usually **rumps'**: a menu-bar tray is an ``NSStatusItem`` on
the same single run loop, and ``rumps.App.run()`` is ``AppHelper.runEventLoop()``
under another name. So the tray provides the runner and this module keeps everything
else. The teardown moved out of the ``finally`` and into a named, idempotent function
for one blunt reason: rumps quits through ``NSApplication.terminate_``, which never
returns from ``run()`` — a ``finally`` alone would never fire on the normal way out.

Three seams keep it testable on the Linux dev machine, where no run loop exists:

- ``run_loop(on_ready, on_quit)`` — the real one is the injected default; a test
  passes a fake that fires ``on_ready`` (the moment registration must happen) then
  returns.
- ``register`` — the real Carbon façade by default; a fake in tests.
- ``tray_factory`` — :func:`aparte.macos_tray.build_tray` by default; a fake tray in
  tests, and ``None`` on a Mac without rumps installed.

The native AppKit/Carbon imports live inside :func:`_appkit_run_loop`, reached
only on a real Mac; the module itself stays importable everywhere.
"""

from __future__ import annotations

import sys
import threading
import time

from .macos_hotkey import (
    HotkeyDispatcher,
    HotkeyError,
    HotkeyState,
    register_hotkey,
    safe_hotkey_label,
)
from .macos_tray import build_tray
from .config import update_config
from .notify import notify

# How long one quit attempt waits for the recorder lock. A permission dialog
# may hold it for 30 s: refusal keeps the tray alive and retries on later ticks.
SHUTDOWN_TIMEOUT = 2.0


def serve_macos(
    server,
    controller,
    settings,
    *,
    url: str = "",
    register=register_hotkey,
    run_loop=None,
    tray_factory=build_tray,
) -> None:
    """Serve on a daemon thread; own the shortcut and the AppKit loop on the main one.

    Blocks until the app quits, then tears down in a fixed order. ``register``,
    ``run_loop`` and ``tray_factory`` are injected in tests so no native code runs off
    macOS.

    When the menu-bar tray can be built, **it** runs the loop (``rumps.App.run()`` is
    ``AppHelper.runEventLoop()`` under another name, and there is only one main
    thread). This function keeps the shortcut, the published state and the teardown
    either way; without a tray, the plain runner is used and nothing else changes.
    """
    tray = None
    if run_loop is None:
        tray = tray_factory(url, settings, controller, lambda: server.RequestHandlerClass.hotkey_state)
        run_loop = tray.run_loop if tray is not None else _appkit_run_loop

    spec = getattr(settings, "hotkey", "") or ""
    # The dispatcher filters repeats at arrival and calls toggle() on its own
    # worker, so the Carbon callback never blocks the run loop (see macos_hotkey).
    dispatcher = HotkeyDispatcher(controller.toggle)

    # doctor and the read-only /api/hotkey-state route read the shortcut's state
    # from the handler class. Publish an initial snapshot before serving, so a
    # request landing before on_ready() sees "configured, not yet registered"
    # rather than nothing. The server keeps the handler class here.
    handler_cls = server.RequestHandlerClass
    handler_cls.hotkey_state = HotkeyState(configured_key=spec or None)

    threading.Thread(target=server.serve_forever, daemon=True).start()

    handle: object | None = None
    torn = False
    # Reentrant: "Quit" → teardown → quit_application() → applicationWillTerminate_ →
    # teardown, all on the main thread. A plain Lock would deadlock on itself there.
    gate = threading.RLock()

    def on_ready() -> None:
        # Fired once the run loop is live (NSApplication exists) — the hotkey must
        # be registered here, not before, or Carbon has no target to attach to. Under
        # the tray this is a timer callback, so it can land *after* a very quick quit:
        # the torn check under the same lock is what stops a shortcut from being
        # registered onto an already dismantled app.
        nonlocal handle
        failure = None
        with gate:
            if torn:
                return
            if not spec:
                # No shortcut configured — run `aparte install-hotkey` to set one. The
                # server still serves the web UI and browser dictation; doctor points
                # the user at install-hotkey.
                handler_cls.hotkey_state = HotkeyState(configured_key=None)
                return
            try:
                handle = register(spec, dispatcher.trigger)
            except HotkeyError as exc:
                # The server keeps serving the web UI and browser dictation; only the
                # global shortcut is dead. Make it observable (the state below, doctor,
                # a startup notification) instead of crashing or failing in silence.
                handler_cls.hotkey_state = HotkeyState(
                    configured_key=spec, status=exc.status, error=str(exc)
                )
                failure = exc
            else:
                handler_cls.hotkey_state = HotkeyState(registered=True, configured_key=spec)
        # Outside the lock: the notification shells out to osascript, and teardown
        # has no reason to wait behind it.
        if failure is not None:
            _notify_register_failure(spec, failure)

    def configure_hotkey(candidate: str) -> None:
        # Called by the native menu on the AppKit thread, never by HTTP. Keep the
        # existing registration until both the new one and its config are valid.
        nonlocal handle, spec
        from .macos_hotkey import normalize_hotkey
        candidate = normalize_hotkey(candidate)
        with gate:
            if torn:
                raise HotkeyError("Aparté is closing")
            if candidate == spec and handle is not None:
                return
            replacement = register(candidate, dispatcher.trigger)
            try:
                update_config({"hotkey": candidate})
            except Exception:
                replacement.unregister()
                raise
            previous = handle
            handle, spec = replacement, candidate
            handler_cls.hotkey_state = HotkeyState(registered=True, configured_key=candidate)
            if previous is not None:
                previous.unregister()

    if tray is not None and hasattr(tray, "set_hotkey_handler"):
        tray.set_hotkey_handler(configure_hotkey)

    def teardown() -> bool:
        """Ordered, idempotent, best-effort — the app's single way down.

        Three paths lead here and all three must work: the tray's "Quit" item (which
        calls this *before* terminate_, since terminate_ never returns), rumps'
        before-quit hook when the version has one, and the ``finally`` below for every
        path where the loop hands control back.

        Each step is guarded on its own: a hotkey that refuses to unregister must not
        cost the server its socket.
        """
        nonlocal torn
        with gate:
            if torn:
                return True
            # The recorder first makes live audio recoverable and prevents late
            # delivery. If it cannot, keep the application and its Quit menu alive.
            try:
                if controller.shutdown(timeout=SHUTDOWN_TIMEOUT) is False:
                    return False
            except Exception as exc:
                print(f"aparte: cannot preserve recording before quitting: {exc}", file=sys.stderr)
                return False
            torn = True
            # Announced here, not on the KeyboardInterrupt branch: that branch is the
            # one path macOS almost never takes, and the first native run of M6 had no
            # way to tell "Quit tore everything down" from "the process just died" —
            # both leave no process and a free port. A silent teardown is unprovable.
            print("\nStopping desktop server.")
            steps = []
            if tray is not None:
                steps.append(("tray", tray.close))
            if handle is not None:
                # Drop the hotkey early so no trigger arrives mid-shutdown.
                steps.append(("hotkey", handle.unregister))
            # shutdown has already disabled further controller toggles. Drain any
            # dispatch in flight, then close the server.
            steps.append(("dispatcher", dispatcher.close))
            steps.append(("server", server.shutdown))
            steps.append(("socket", server.server_close))
            for what, step in steps:
                try:
                    step()
                except Exception as exc:
                    print(f"aparte: teardown step {what} failed: {exc}", file=sys.stderr)
            return True

    try:
        run_loop(on_ready, teardown)
    except KeyboardInterrupt:
        pass  # the teardown below says so, whichever door we left by
    finally:
        teardown()


def _notify_register_failure(spec: str, exc: HotkeyError) -> None:
    # The shortcut is the primary macOS trigger, so a refused registration must not
    # fail silently. stderr is swallowed by launchd for a login-item server, so the
    # notification is the real feedback at startup; doctor and /api/hotkey-state
    # carry the durable, scriptable version.
    print(f"aparte: could not register the shortcut {spec!r}: {exc}", file=sys.stderr)
    try:
        notify(
            "⚠️ Raccourci indisponible",
            f"macOS a refusé {safe_hotkey_label(spec)}. Choisis-en un autre : aparte install-hotkey.",
            urgency="critical",
        )
    except Exception:
        pass


def run_hotkey_diagnostic(
    spec: str,
    *,
    register=register_hotkey,
    run_loop=None,
    clock=time.monotonic,
    emit=print,
) -> int:
    """M8 native check: register ``spec`` live and log each RAW Carbon event.

    This is the manual-smoke tool (``aparte install-hotkey --diagnostic``). It
    deliberately bypasses :class:`HotkeyDispatcher` and wires ``on_trigger``
    straight to the backend, so the count reflects **what the OS actually
    delivers** — its whole purpose is to answer the question the Linux tests
    can't: does one physical press yield exactly one ``kEventHotKeyPressed``, or
    does macOS repeat/duplicate it? The inter-press delta printed alongside lets
    you eyeball a double-tap against the 250 ms debounce window. It also prints
    the real ``OSStatus`` — the other M8 unknown (is ⌃⌥D free on this machine).

    ``register``/``run_loop`` are injected in tests; on a Mac the defaults drive
    the real Carbon registration on a live AppKit loop. Returns the press count."""
    if run_loop is None:
        run_loop = _appkit_run_loop

    seen = {"count": 0, "last": None}

    def on_trigger() -> None:
        seen["count"] += 1
        now = clock()
        gap = "" if seen["last"] is None else f"  (+{now - seen['last']:.3f}s since last)"
        seen["last"] = now
        emit(f"press #{seen['count']} received{gap}")

    handle: object | None = None

    def on_ready() -> None:
        nonlocal handle
        try:
            handle = register(spec, on_trigger)
        except HotkeyError as exc:
            where = "" if exc.status is None else f" (OSStatus {exc.status})"
            emit(f"registration refused{where}: {exc}")
            return
        emit(f"registered {safe_hotkey_label(spec)} ({spec}) — press it; Ctrl-C to stop")

    try:
        run_loop(on_ready)
    except KeyboardInterrupt:
        emit("\nstopping")
    finally:
        if handle is not None:
            handle.unregister()
    return seen["count"]


def _appkit_run_loop(on_ready, on_quit=None) -> None:
    """Run the AppKit event loop on the main thread until the app quits.

    The fallback runner, used when no menu-bar tray could be built (rumps missing).
    ``on_quit`` is accepted and ignored: this path has no Quit item, and Ctrl-C kills
    the process outright (see below). The parameter is optional so
    :func:`run_hotkey_diagnostic`, which shares this seam, keeps calling it with one
    argument.

    Native — imported lazily and confined here. Not covered by the Linux unit
    tests (which inject a fake run loop); validated by hand in the M8 smoke suite.
    """
    import signal

    from AppKit import NSApplication, NSApplicationActivationPolicyAccessory
    from PyObjCTools import AppHelper

    app = NSApplication.sharedApplication()
    # Accessory: a resident agent with no Dock icon and no menu bar — Aparté here
    # is a shortcut listener, not a window. (Dock presence is an M6 decision.)
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
    # Register now that the run loop's application object exists.
    on_ready()
    # Restore the default SIGINT handler so Ctrl-C stops a foreground run, like the
    # GTK tray does (tray.py); AppHelper would otherwise swallow it.
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    AppHelper.runEventLoop()
