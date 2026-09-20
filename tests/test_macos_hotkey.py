"""M5a — the macOS hotkey façade, parser and dispatcher, proven under Linux.

The real Carbon backend cannot run here (no NSApplication run loop, no
RegisterEventHotKey); it is validated by hand in M8. Everything above it — the
combo grammar, the OSStatus contract, and the arrival-time debounce that fixes
the double-press bug — is locked here with an injected fake backend and a
controlled clock.
"""

import threading
import unittest
from unittest import mock

from aparte import macos_hotkey
from aparte.macos_hotkey import (
    DEFAULT_HOTKEY,
    HotkeyDispatcher,
    HotkeyError,
    hotkey_label,
    normalize_hotkey,
    register_hotkey,
    subscribed_events,
    _resolve,
)


class FakeBackend:
    """Records what register_hotkey asked for; returns a fixed OSStatus."""

    def __init__(self, status=0):
        self.status = status
        self.registered = []      # (keycode, modifiers, on_trigger)
        self.unregistered = []

    def register(self, keycode, modifiers, on_trigger):
        self.registered.append((keycode, modifiers, on_trigger))
        return self.status, len(self.registered)  # token = 1-based index

    def unregister(self, token):
        self.unregistered.append(token)


class NormalizeTest(unittest.TestCase):
    def test_the_default_is_canonical_control_option_d(self):
        self.assertEqual(normalize_hotkey(DEFAULT_HOTKEY), "ctrl+opt+d")

    def test_aliases_and_order_fold_to_one_canonical_form(self):
        for spec in ("alt+Ctrl+D", "control+option+d", "⌥+⌃+d", "D+opt+ctrl"):
            self.assertEqual(normalize_hotkey(spec), "ctrl+opt+d")

    def test_a_named_key_survives_normalization(self):
        self.assertEqual(normalize_hotkey("cmd+shift+space"), "shift+cmd+space")

    def test_the_label_uses_apple_symbols(self):
        self.assertEqual(hotkey_label("ctrl+opt+d"), "⌃⌥D")
        self.assertEqual(hotkey_label("cmd+shift+space"), "⇧⌘Space")

    def test_a_missing_modifier_is_refused(self):
        with self.assertRaises(HotkeyError):
            normalize_hotkey("d")

    def test_a_missing_key_is_refused(self):
        with self.assertRaises(HotkeyError):
            normalize_hotkey("ctrl+opt")

    def test_an_unknown_key_is_refused(self):
        with self.assertRaises(HotkeyError):
            normalize_hotkey("ctrl+opt+zz")

    def test_two_keys_are_refused(self):
        with self.assertRaises(HotkeyError):
            normalize_hotkey("ctrl+a+b")

    def test_empty_is_refused(self):
        with self.assertRaises(HotkeyError):
            normalize_hotkey("")


class ResolveTest(unittest.TestCase):
    def test_resolve_maps_to_keycode_and_carbon_mask(self):
        keycode, mask = _resolve("ctrl+opt+d")
        self.assertEqual(keycode, 0x02)                 # kVK_ANSI_D
        self.assertEqual(mask, 0x1000 | 0x0800)         # controlKey | optionKey


class SubscribedEventsTest(unittest.TestCase):
    def test_the_handler_subscribes_to_pressed_only(self):
        events = subscribed_events()
        self.assertEqual(events, ((0x6B657962, 6),))    # (kEventClassKeyboard, pressed)
        kinds = {kind for _, kind in events}
        self.assertNotIn(7, kinds)                       # never kEventHotKeyReleased


class RegisterHotkeyTest(unittest.TestCase):
    def test_success_returns_a_handle_with_the_resolved_combo(self):
        backend = FakeBackend()
        trigger = lambda: None
        handle = register_hotkey("alt+ctrl+d", trigger, backend=backend)
        self.assertEqual(handle.spec, "ctrl+opt+d")
        self.assertEqual(backend.registered, [(0x02, 0x1800, trigger)])

    def test_a_nonzero_osstatus_raises_with_the_status(self):
        backend = FakeBackend(status=-9878)              # eventHotKeyExistsErr
        with self.assertRaises(HotkeyError) as caught:
            register_hotkey("ctrl+opt+d", lambda: None, backend=backend)
        self.assertEqual(caught.exception.status, -9878)

    def test_a_bad_spec_is_refused_before_touching_the_backend(self):
        backend = FakeBackend()
        with self.assertRaises(HotkeyError):
            register_hotkey("nope", lambda: None, backend=backend)
        self.assertEqual(backend.registered, [])

    def test_unregister_is_idempotent(self):
        backend = FakeBackend()
        handle = register_hotkey("ctrl+opt+d", lambda: None, backend=backend)
        handle.unregister()
        handle.unregister()
        self.assertEqual(backend.unregistered, [1])      # token released exactly once


class DispatcherTest(unittest.TestCase):
    def setUp(self):
        self.now = 1000.0
        self.calls = []
        # No dispatcher test may reach the real notify (osascript/gi); stub it.
        self.notify = mock.patch.object(macos_hotkey, "notify").start()
        self.addCleanup(mock.patch.stopall)

    def _clock(self):
        return self.now

    def _dispatcher(self, on_toggle):
        d = HotkeyDispatcher(on_toggle, clock=self._clock)
        self.addCleanup(d.close)
        return d

    def test_a_burst_of_presses_within_the_window_is_one_toggle(self):
        d = self._dispatcher(lambda: self.calls.append(1))
        for _ in range(100):
            d.trigger()          # clock never advances → all inside the window
        d.close()
        self.assertEqual(self.calls, [1])

    def test_a_repeat_never_becomes_a_delayed_stop_even_if_toggle_blocks(self):
        entered = threading.Event()
        release = threading.Event()

        def slow_toggle():
            self.calls.append(1)
            entered.set()
            release.wait(2.0)    # simulate the slow start I/O that holds the lock

        d = self._dispatcher(slow_toggle)
        d.trigger()              # press 1: accepted, worker enters slow_toggle
        self.assertTrue(entered.wait(2.0))
        self.now += 0.005        # press 2 arrives 5 ms later, still in the window
        d.trigger()              # rejected at arrival — must NOT queue a stop
        release.set()
        d.close()
        self.assertEqual(self.calls, [1])

    def test_a_press_past_the_window_is_accepted_again(self):
        seen = threading.Event()

        def toggle():
            self.calls.append(1)
            seen.set()

        d = self._dispatcher(toggle)
        d.trigger()
        self.assertTrue(seen.wait(2.0))   # press 1 consumed by the worker
        seen.clear()
        self.now += 0.5                   # well past the 0.25 s debounce
        d.trigger()
        self.assertTrue(seen.wait(2.0))   # press 2 accepted and consumed
        d.close()
        self.assertEqual(self.calls, [1, 1])

    def test_a_trigger_after_close_is_ignored(self):
        d = self._dispatcher(lambda: self.calls.append(1))
        d.close()
        d.trigger()
        self.assertEqual(self.calls, [])

    def test_a_toggle_exception_is_caught_notified_and_the_worker_survives(self):
        done = threading.Event()
        outcomes = []

        def flaky_toggle():
            outcomes.append(len(outcomes))
            try:
                if len(outcomes) == 1:
                    raise RuntimeError("boom")
            finally:
                done.set()

        d = self._dispatcher(flaky_toggle)
        d.trigger()                          # raises inside the worker
        self.assertTrue(done.wait(2.0))      # first toggle ran and raised
        done.clear()
        self.now += 0.5
        d.trigger()                          # worker still alive → runs again
        self.assertTrue(done.wait(2.0))      # second toggle ran
        d.close()
        self.assertEqual(len(outcomes), 2)
        self.assertEqual(self.notify.call_args.kwargs.get("urgency"), "critical")

    def test_close_waits_for_an_in_flight_toggle_before_returning(self):
        entered = threading.Event()
        release = threading.Event()

        def slow_toggle():
            entered.set()
            release.wait(2.0)

        d = HotkeyDispatcher(slow_toggle, clock=self._clock)
        d.trigger()
        self.assertTrue(entered.wait(2.0))   # toggle is in flight, blocked
        closed = threading.Event()
        threading.Thread(target=lambda: (d.close(), closed.set())).start()
        # close() is joining the worker, which is stuck on release → it must block.
        self.assertFalse(closed.wait(0.2))
        release.set()
        self.assertTrue(closed.wait(2.0))    # once toggle returns, close returns


class _FakeCarbonFunction:
    """A C function that records what was declared for it and returns ``result``."""

    def __init__(self):
        self.restype = None
        self.argtypes = None
        self.result = 0
        self.calls = []
        self.side_effect = None

    def __call__(self, *args):
        self.calls.append(args)
        if self.side_effect is not None:
            return self.side_effect(*args)
        return self.result


class _FakeCarbon:
    """Stands in for the Carbon shared library, one fake function per name."""

    def __init__(self):
        self._functions = {}

    def __getattr__(self, name):
        return self._functions.setdefault(name, _FakeCarbonFunction())


class CarbonRebindingTest(unittest.TestCase):
    def setUp(self):
        import ctypes
        self.carbon = _FakeCarbon()
        patches = [mock.patch.object(ctypes, "CDLL", return_value=self.carbon),
                   mock.patch.object(macos_hotkey, "_CARBON_BACKEND", None)]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    def _emit(self, token, *, signature=macos_hotkey._HOTKEY_SIGNATURE, status=0):
        def parameter(*args):
            identity = args[-1]._obj
            identity.signature, identity.id = signature, token
            return status
        self.carbon.GetEventParameter.side_effect = parameter
        return macos_hotkey._carbon_backend()._callback(None, None, None)

    def test_failed_replacement_keeps_old_shortcut_routable_and_one_handler(self):
        old_trigger, replacement_trigger = mock.Mock(), mock.Mock()
        old = register_hotkey("ctrl+opt+d", old_trigger)
        replacement = register_hotkey("ctrl+opt+f", replacement_trigger)
        self.assertEqual(len(self.carbon.InstallEventHandler.calls), 1)
        self.assertNotEqual(old._token, replacement._token)
        # Same rollback used when persisting a new shortcut fails.
        replacement.unregister()
        self.assertEqual(self._emit(old._token), macos_hotkey._NO_ERR)
        old_trigger.assert_called_once()
        replacement_trigger.assert_not_called()
        self.assertEqual(self._emit(replacement._token), macos_hotkey._EVENT_NOT_HANDLED)
        old.unregister()
        # Handler survives the last individual binding, with no ID reuse.
        third = register_hotkey("ctrl+opt+g", mock.Mock())
        self.assertGreater(third._token, replacement._token)
        self.assertEqual(len(self.carbon.InstallEventHandler.calls), 1)
        third.unregister()

    def test_foreign_unknown_or_unreadable_event_is_left_for_other_handlers(self):
        trigger = mock.Mock()
        handle = register_hotkey("ctrl+opt+d", trigger)
        self.assertEqual(self._emit(handle._token, signature=123), macos_hotkey._EVENT_NOT_HANDLED)
        self.assertEqual(self._emit(9000), macos_hotkey._EVENT_NOT_HANDLED)
        self.assertEqual(self._emit(handle._token, status=-50), macos_hotkey._EVENT_NOT_HANDLED)
        trigger.assert_not_called()
        handle.unregister()

    def test_backend_and_callback_remain_owned_after_handle_is_discarded(self):
        import gc
        import weakref
        handle = register_hotkey("ctrl+opt+d", mock.Mock())
        backend_ref = weakref.ref(handle._backend)
        callback_ref = weakref.ref(handle._backend._callback)
        handle.unregister()
        del handle
        gc.collect()
        self.assertIsNotNone(backend_ref())
        self.assertIsNotNone(callback_ref())
        self.assertIs(macos_hotkey._carbon_backend(), backend_ref())


class CarbonBackendSignatureTest(unittest.TestCase):
    """The declarations whose absence segfaulted Big Sur (M8).

    The backend needs a Mac to *run*, but what it declares to ctypes is plain
    data a fake library can record. Undeclared, ctypes assumes 32-bit ints:
    ``GetApplicationEventTarget`` returned a pointer cut in half and Carbon
    crashed on it before the first registration. These tests are the only guard
    that exists off a Mac.
    """

    def _build(self, carbon=None):
        import ctypes

        carbon = carbon or _FakeCarbon()
        with mock.patch.object(ctypes, "CDLL", return_value=carbon):
            backend = macos_hotkey._CarbonBackend()
        return backend, carbon

    def test_the_pointer_returning_call_declares_a_pointer_restype(self):
        import ctypes

        _, carbon = self._build()
        self.assertIs(carbon.GetApplicationEventTarget.restype, ctypes.c_void_p)

    def test_the_count_arguments_are_declared_sixty_four_bit(self):
        import ctypes

        _, carbon = self._build()
        # ItemCount and ByteCount are unsigned long on 64-bit macOS, not UInt32.
        self.assertIs(carbon.InstallEventHandler.argtypes[2], ctypes.c_ulong)
        self.assertIs(carbon.GetEventParameter.argtypes[4], ctypes.c_ulong)

    def test_every_carbon_call_declares_its_signature(self):
        _, carbon = self._build()
        for name in (
            "GetApplicationEventTarget",
            "InstallEventHandler",
            "RegisterEventHotKey",
            "UnregisterEventHotKey",
            "GetEventParameter",
        ):
            function = getattr(carbon, name)
            self.assertIsNotNone(function.restype, name)
            self.assertIsNotNone(function.argtypes, name)

    def test_the_struct_classes_are_shared_with_the_declared_signatures(self):
        # Rebuilding a Structure subclass per call would make ctypes reject the
        # very argument the signature was declared for.
        backend, carbon = self._build()
        self.assertIs(
            carbon.RegisterEventHotKey.argtypes[2], backend._EventHotKeyID
        )
        self.assertIs(
            carbon.InstallEventHandler.argtypes[3]._type_, backend._EventTypeSpec
        )

    def test_a_refused_event_handler_raises_instead_of_going_silent(self):
        # A hotkey registered without its handler is a dead key with a green
        # light: RegisterEventHotKey succeeds and nothing ever fires.
        carbon = _FakeCarbon()
        carbon.InstallEventHandler.result = -50
        with self.assertRaises(HotkeyError) as caught:
            self._build(carbon)
        self.assertEqual(caught.exception.status, -50)


if __name__ == "__main__":
    unittest.main()
