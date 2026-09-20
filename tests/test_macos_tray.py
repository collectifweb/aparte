"""M6a — what the macOS menu bar shows, decided without AppKit.

No rumps, no NSStatusItem: this file locks the pure half of the tray — the two
languages, the elapsed-time format, and the mapping from a controller snapshot plus
the shortcut's registration state onto icon, title and menu lines. The native
binding is exercised (with a fake rumps) in test_macos_runloop.
"""

import struct
import unittest
import zlib
from unittest import mock

from aparte import macos_tray
from aparte import update as update_module
from aparte.macos_hotkey import HotkeyState
from aparte.macos_recording import ERROR, IDLE, PROCESSING, RECORDING
from aparte.macos_tray import ICON_IDLE, ICON_RECORDING, format_elapsed, labels, tray_view

REGISTERED = HotkeyState(registered=True, configured_key="ctrl+opt+d")


def view(state, elapsed=None, hotkey=REGISTERED, texts=None):
    return tray_view((state, elapsed), hotkey, texts or macos_tray.LABELS["fr"])


class ElapsedFormatTest(unittest.TestCase):
    def test_it_reads_like_a_stopwatch(self):
        self.assertEqual(format_elapsed(0), "0:00")
        self.assertEqual(format_elapsed(7), "0:07")
        self.assertEqual(format_elapsed(59.9), "0:59")   # truncated, never rounded up
        self.assertEqual(format_elapsed(60), "1:00")
        self.assertEqual(format_elapsed(3599), "59:59")

    def test_past_the_hour_it_grows_a_field(self):
        self.assertEqual(format_elapsed(3600), "1:00:00")
        self.assertEqual(format_elapsed(3661), "1:01:01")

    def test_a_negative_clock_reads_zero_rather_than_raising(self):
        # A clock that went backwards must never make the menu bar throw.
        self.assertEqual(format_elapsed(-2), "0:00")


class IconAndTitleTest(unittest.TestCase):
    def test_only_recording_changes_the_icon(self):
        self.assertEqual(view(IDLE).icon, ICON_IDLE)
        self.assertEqual(view(RECORDING, 3).icon, ICON_RECORDING)
        self.assertEqual(view(PROCESSING).icon, ICON_IDLE)
        self.assertEqual(view(ERROR).icon, ICON_IDLE)

    def test_the_timer_shows_only_while_the_microphone_is_open(self):
        self.assertEqual(view(RECORDING, 7).title, "0:07")
        self.assertEqual(view(IDLE).title, "")
        self.assertEqual(view(ERROR).title, "")

    def test_transcribing_says_so_without_claiming_the_mic_is_open(self):
        self.assertEqual(view(PROCESSING).title, "…")

    def test_a_duration_lost_to_a_transition_keeps_the_recording_icon(self):
        # The lock-free read can catch a transition between its two fields. The state
        # is what matters — the icon stays right, the timer joins one tick later.
        transient = view(RECORDING, None)
        self.assertEqual(transient.icon, ICON_RECORDING)
        self.assertEqual(transient.title, "")


class StatusLineTest(unittest.TestCase):
    def test_each_state_has_its_own_sentence(self):
        self.assertEqual(view(IDLE).status, "Prêt à dicter")
        self.assertEqual(view(RECORDING, 1).status, "Micro ouvert")
        self.assertEqual(view(PROCESSING).status, "Transcription en cours…")
        self.assertEqual(view(ERROR).status, "La dernière dictée a échoué")

    def test_an_unknown_state_falls_back_instead_of_crashing_the_menu(self):
        self.assertEqual(view("something-new").status, "Prêt à dicter")

    def test_english_says_the_same_things(self):
        english = macos_tray.LABELS["en"]
        self.assertEqual(view(RECORDING, 1, texts=english).status, "Microphone open")
        self.assertEqual(view(PROCESSING, texts=english).status, "Transcribing…")


class ShortcutLineTest(unittest.TestCase):
    def test_a_live_registration_shows_the_combination(self):
        self.assertEqual(view(IDLE).shortcut, "Raccourci : ⌃⌥D")

    def test_no_shortcut_configured_points_to_the_native_menu(self):
        line = view(IDLE, hotkey=HotkeyState(configured_key=None)).shortcut
        self.assertEqual(line, "Choisis ton raccourci dans ce menu")

    def test_a_refused_combination_is_not_reported_as_working(self):
        # "configured" is a half-truth once Carbon has refused: registered is the
        # only honest source, and this is exactly when the user needs to be told.
        refused = HotkeyState(configured_key="ctrl+opt+d", status=-9878, error="taken")
        self.assertEqual(view(IDLE, hotkey=refused).shortcut, "Raccourci indisponible : ⌃⌥D")

    def test_an_unparseable_combo_from_a_hand_edited_config_still_draws(self):
        broken = HotkeyState(registered=True, configured_key="ctrl+nope")
        self.assertEqual(view(IDLE, hotkey=broken).shortcut, "Raccourci : ctrl+nope")

    def test_no_published_state_reads_as_no_shortcut(self):
        self.assertEqual(view(IDLE, hotkey=None).shortcut, "Choisis ton raccourci dans ce menu")

    def test_english_shortcut_lines(self):
        english = macos_tray.LABELS["en"]
        self.assertEqual(view(IDLE, texts=english).shortcut, "Shortcut: ⌃⌥D")
        self.assertEqual(
            view(IDLE, hotkey=HotkeyState(configured_key=None), texts=english).shortcut,
            "Choose your shortcut in this menu",
        )


class FakeMenuItem:
    def __init__(self, title="", callback=None):
        self.title = title
        self.callback = callback


class FakeTimer:
    def __init__(self, callback, interval):
        self.callback = callback
        self.interval = interval
        self.started = False
        self.stopped = False

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def fire(self):
        self.callback(self)


class FakeApp:
    def __init__(self, name, title=None, icon=None, template=None, quit_button="Quit"):
        self.name = name
        self.title = title
        self.icon = icon
        self.template = template
        self.quit_button = quit_button
        self.menu = []
        self.ran = False
        self.on_run = None

    def run(self):
        self.ran = True
        if self.on_run is not None:
            self.on_run(self)


class FakeRumps:
    """Just enough rumps to prove the binding, with no AppKit anywhere."""

    separator = "---"

    def __init__(self, events=None):
        self.apps: list[FakeApp] = []
        self.timers: list[FakeTimer] = []
        self.quit_calls = 0
        if events is not None:
            self.events = events

    def App(self, *args, **kwargs):
        app = FakeApp(*args, **kwargs)
        self.apps.append(app)
        return app

    def MenuItem(self, title="", callback=None):
        return FakeMenuItem(title, callback)

    def Timer(self, callback, interval):
        timer = FakeTimer(callback, interval)
        self.timers.append(timer)
        return timer

    def quit_application(self, *_):
        self.quit_calls += 1


class FakeController:
    def __init__(self, snapshots=None):
        self.snapshots = list(snapshots or [(IDLE, None)])

    def recording_snapshot(self):
        return self.snapshots[0] if len(self.snapshots) == 1 else self.snapshots.pop(0)


def build(rumps, controller=None, hotkey=REGISTERED, url="http://127.0.0.1:8765"):
    settings = mock.Mock(history_persist=False)
    return macos_tray.MacTray(rumps, url, settings, controller or FakeController(), lambda: hotkey)


class TrayBindingTest(unittest.TestCase):
    """Base for the rumps-binding tests: AppKit does not exist on this machine, so
    the one native call (hiding the Dock icon) is stubbed rather than left to fail
    loudly into the suite's output."""

    def setUp(self):
        mock.patch.object(macos_tray, "_set_accessory_policy").start()
        mock.patch.object(macos_tray, "language", return_value="fr").start()
        self.addCleanup(mock.patch.stopall)


class MenuStructureTest(TrayBindingTest):
    def test_rumps_own_quit_item_is_disabled(self):
        # Not cosmetic: rumps' built-in Quit calls quit_application() directly, which
        # goes through terminate_ and never comes back — a visible way out that would
        # skip the ordered teardown entirely.
        rumps = FakeRumps()
        build(rumps)
        self.assertIsNone(rumps.apps[0].quit_button)

    def test_the_only_quit_in_the_menu_tears_down_before_terminating(self):
        rumps = FakeRumps()
        tray = build(rumps)
        order = []
        tray.run_loop(lambda: None, lambda: order.append("teardown"))
        quits = [i for i in rumps.apps[0].menu if isinstance(i, FakeMenuItem) and i.title == "Quitter"]
        self.assertEqual(len(quits), 1)
        quits[0].callback(None)
        self.assertEqual(order, ["teardown"])
        self.assertEqual(rumps.quit_calls, 1)

    def test_quit_waits_for_preservation_before_termination(self):
        rumps = FakeRumps()
        tray = build(rumps)
        attempts = mock.Mock(side_effect=[False, True])
        tray.run_loop(lambda: None, attempts)
        tray._quit()
        self.assertEqual(rumps.quit_calls, 0)
        self.assertTrue(tray._quit_pending)
        self.assertEqual(tray._quit_item.title, tray._texts["quit_wait"])
        tray._tick()
        self.assertEqual(rumps.quit_calls, 1)

    def test_shortcut_dialog_only_applies_confirmed_valid_choice(self):
        rumps = FakeRumps()
        rumps.Window = mock.Mock()
        rumps.alert = mock.Mock()
        tray = build(rumps)
        configure = mock.Mock()
        tray.set_hotkey_handler(configure)
        response = rumps.Window.return_value.run.return_value
        response.clicked, response.text = False, "cmd+shift+d"
        tray._configure_hotkey()
        configure.assert_not_called()
        response.clicked, response.text = True, "nonsense"
        tray._configure_hotkey()
        configure.assert_not_called()
        self.assertEqual(rumps.alert.call_args.kwargs["title"], tray._texts["shortcut_problem"])
        response.text = "Alt+Ctrl+D"
        tray._configure_hotkey()
        configure.assert_called_once_with("ctrl+opt+d")
        self.assertIn("Appuie pour essayer", rumps.alert.call_args.kwargs["message"])

    def test_model_preparation_is_an_explicit_native_action(self):
        tray = build(FakeRumps())
        threads = []
        class ImmediateThread:
            def __init__(self, target, **kwargs):
                self.target = target
                threads.append(self)
            def start(self):
                self.target()
        with mock.patch.object(macos_tray.threading, "Thread", ImmediateThread):
            with mock.patch("aparte.model_download.ensure_ready") as ensure:
                with mock.patch.object(macos_tray.Settings, "from_env", return_value="settings"):
                    with mock.patch.object(macos_tray.webbrowser, "open"):
                        ensure.assert_not_called()
                        tray._prepare_model()
                ensure.assert_called_once_with("settings")

    def test_copy_last_rereads_history_setting(self):
        tray = build(FakeRumps())
        with mock.patch.object(macos_tray.Settings, "from_env", return_value=mock.Mock(history_persist=True)):
            with mock.patch.object(macos_tray.history, "last", return_value=None) as last:
                tray._copy_last()
        last.assert_called_once_with(True)

    def test_the_two_state_lines_are_not_clickable(self):
        rumps = FakeRumps()
        build(rumps)
        status, shortcut = rumps.apps[0].menu[0], rumps.apps[0].menu[1]
        self.assertIsNone(status.callback)      # no callback → macOS greys it out
        self.assertIsNone(shortcut.callback)

    def test_the_icon_starts_as_a_template_image(self):
        rumps = FakeRumps()
        build(rumps)
        self.assertTrue(rumps.apps[0].template)
        self.assertTrue(rumps.apps[0].icon.endswith(ICON_IDLE))


class ReadyHookTest(TrayBindingTest):
    def test_on_ready_fires_from_the_timer_not_before_the_loop(self):
        # RegisterEventHotKey needs a live NSApplication: registering before run()
        # would attach the shortcut to nothing.
        rumps = FakeRumps()
        tray = build(rumps)
        fired = []
        rumps.apps[0].on_run = lambda app: rumps.timers[0].fire()
        tray.run_loop(lambda: fired.append("ready"))
        self.assertEqual(fired, ["ready"])

    def test_the_ready_timer_is_a_hand_made_one_shot(self):
        # rumps.Timer repeats by construction; a second tick must not re-register.
        rumps = FakeRumps()
        tray = build(rumps)
        fired = []
        tray.run_loop(lambda: fired.append("ready"))
        ready = rumps.timers[0]
        ready.fire()
        ready.fire()
        self.assertEqual(fired, ["ready"])
        self.assertTrue(ready.stopped)

    def test_a_raising_ready_hook_does_not_take_the_menu_bar_down(self):
        rumps = FakeRumps()
        tray = build(rumps)
        tray.run_loop(lambda: (_ for _ in ()).throw(RuntimeError("boom")))
        rumps.timers[0].fire()      # must not propagate out of the timer callback

    def test_close_stops_both_timers(self):
        rumps = FakeRumps()
        tray = build(rumps)
        tray.run_loop(lambda: None, lambda: None)
        tray.close()
        self.assertTrue(all(timer.stopped for timer in rumps.timers))
        tray.close()   # idempotent: the teardown may run twice


class BeforeQuitHookTest(TrayBindingTest):
    def test_the_hook_is_used_when_the_installed_rumps_has_one(self):
        registered = []
        events = mock.Mock(before_quit=mock.Mock(register=registered.append))
        rumps = FakeRumps(events=events)
        tray = build(rumps)
        order = []
        tray.run_loop(lambda: None, lambda: order.append("teardown"))
        self.assertEqual(len(registered), 1)
        registered[0]()                      # macOS terminating by another path
        self.assertEqual(order, ["teardown"])

    def test_a_rumps_without_events_still_runs(self):
        # Duck-typed on purpose: not every release has rumps.events, and an
        # AttributeError at startup would cost the whole tray.
        rumps = FakeRumps()
        tray = build(rumps)
        tray.run_loop(lambda: None, lambda: None)
        self.assertTrue(rumps.apps[0].ran)


class RefreshTest(TrayBindingTest):
    def test_the_menu_bar_follows_the_recorder(self):
        rumps = FakeRumps()
        controller = FakeController([(IDLE, None), (RECORDING, 7.0)])
        tray = build(rumps, controller)
        app = rumps.apps[0]
        self.assertEqual(app.title, "")
        tray.refresh()
        self.assertEqual(app.title, "0:07")
        self.assertTrue(app.icon.endswith(ICON_RECORDING))
        self.assertEqual(app.menu[0].title, "Micro ouvert")

    def test_an_unchanged_state_does_not_rewrite_the_icon(self):
        # The icon is rebuilt from disk on every assignment; at four ticks a second
        # that would be pure churn.
        rumps = FakeRumps()
        tray = build(rumps, FakeController([(IDLE, None)]))
        app = rumps.apps[0]
        app.icon = "sentinel"
        tray.refresh()
        self.assertEqual(app.icon, "sentinel")

    def test_a_refresh_failure_never_kills_the_timer(self):
        # A frozen icon showing a stale state is worse than one bad pixel.
        rumps = FakeRumps()
        tray = build(rumps)
        tray.run_loop(lambda: None, lambda: None)
        with mock.patch.object(tray, "refresh", side_effect=RuntimeError("boom")):
            rumps.timers[1].fire()


class BuildTrayTest(unittest.TestCase):
    def setUp(self):
        self.notify = mock.patch.object(macos_tray, "notify").start()
        # The outcome is module-level and read by `aparte doctor`: a test that left
        # its own value behind would answer for the next one.
        mock.patch.object(macos_tray, "_BUILD_OUTCOME", None).start()
        self.addCleanup(mock.patch.stopall)

    def _build(self):
        return macos_tray.build_tray("http://x", mock.Mock(history_persist=False), FakeController(), lambda: None)

    def test_a_missing_rumps_falls_back_in_silence(self):
        # An install without the [macos] extra is a choice, not a bug: doctor says
        # how to get the icon back, and the server runs exactly as before.
        with mock.patch.object(macos_tray, "_rumps", side_effect=ImportError("no rumps")):
            self.assertIsNone(self._build())
        self.notify.assert_not_called()
        self.assertEqual(macos_tray.tray_build_outcome(), macos_tray.MISSING_DEPENDENCY)

    def test_an_unexpected_failure_is_loud(self):
        # M6 exists to close M8's main usability defect. A silently missing icon
        # would quietly recreate the very bug it fixes.
        with mock.patch.object(macos_tray, "_rumps", return_value=FakeRumps()), \
             mock.patch.object(macos_tray, "MacTray", side_effect=RuntimeError("no status bar")):
            self.assertIsNone(self._build())
        self.notify.assert_called_once()
        self.assertEqual(self.notify.call_args.kwargs.get("urgency"), "critical")
        self.assertEqual(macos_tray.tray_build_outcome(), "no status bar")

    def test_a_built_tray_records_that_it_exists(self):
        # What `aparte doctor` reads: nothing else in the process knows the icon is up.
        with mock.patch.object(macos_tray, "_rumps", return_value=FakeRumps()), \
             mock.patch.object(macos_tray, "MacTray", return_value=mock.Mock()):
            self.assertIsNotNone(self._build())
        self.assertEqual(macos_tray.tray_build_outcome(), "ok")


FR = macos_tray.LABELS["fr"]


class UpdateDecisionTest(unittest.TestCase):
    """Every state of check_update gets a sentence. A menu item that silently does
    nothing is the failure this whole lot is about."""

    def test_a_release_is_offered_then_installed_on_the_second_click(self):
        decision = macos_tray.update_after_check({"state": "available", "release": "v1.2.0"}, FR)
        self.assertEqual(decision.mode, macos_tray.UPDATE_INSTALL)
        self.assertEqual(decision.title, "Installer la version 1.2.0")   # the tag's "v" is git's
        self.assertIn("Reclique", decision.message)

    def test_up_to_date_says_so_and_stays_ready_to_check_again(self):
        decision = macos_tray.update_after_check({"state": "current", "version": "1.1.1"}, FR)
        self.assertEqual(decision.mode, macos_tray.UPDATE_CHECK)
        self.assertEqual(decision.message, "Aparté 1.1.1 est à jour.")

    def test_a_dirty_checkout_is_named_rather_than_offered(self):
        # A release is waiting but the checkout cannot move to it; offering an
        # install that would refuse itself is worse than saying why.
        decision = macos_tray.update_after_check(
            {"state": "available", "release": "v1.2.0", "dirty": True}, FR
        )
        self.assertEqual(decision.mode, macos_tray.UPDATE_CHECK)
        self.assertEqual(decision.message, "Le dossier a des modifications non validées.")

    def test_every_impossible_state_gets_its_own_reason(self):
        for state, expected in (
            ("manual", "Aparté ne tourne pas depuis un dépôt git."),
            ("no_upstream", "La branche ne suit aucune branche distante."),
            ("offline", "Impossible de joindre le dépôt distant."),
            ("error", "Lecture du dépôt impossible."),
        ):
            with self.subTest(state=state):
                self.assertEqual(macos_tray.update_after_check({"state": state}, FR).message, expected)

    def test_an_unknown_state_still_says_something(self):
        self.assertTrue(macos_tray.update_after_check({"state": "martian"}, FR).message)

    def test_a_homebrew_install_is_told_the_command(self):
        # The fallback above would find the sentence but not the command, and the
        # command is the whole answer for someone who installed with brew.
        decision = macos_tray.update_after_check(
            {"state": "brew", "command": "brew upgrade aparte"}, FR
        )
        self.assertEqual(decision.mode, macos_tray.UPDATE_CHECK)
        self.assertIn("brew upgrade aparte", decision.message)
        english = macos_tray.update_after_check(
            {"state": "brew", "command": "brew upgrade aparte"}, macos_tray.LABELS["en"]
        )
        self.assertIn("brew upgrade aparte", english.message)

    def test_an_installed_release_freezes_the_item_on_relaunch(self):
        decision = macos_tray.update_after_check({"state": "restart_required", "release": "v1.2.0"}, FR)
        self.assertEqual(decision.mode, macos_tray.UPDATE_DONE)
        self.assertEqual(decision.title, "Mise à jour installée — relance Aparté")

    def test_success_is_the_marker_never_the_absence_of_an_error(self):
        decision = macos_tray.update_after_apply(["ok", "DONE"], FR, "DONE")
        self.assertEqual(decision.mode, macos_tray.UPDATE_DONE)
        self.assertIn("relance", decision.message)

    def test_a_failed_install_reports_the_last_line_of_the_log(self):
        decision = macos_tray.update_after_apply(["$ pip install", "boom", ""], FR, "DONE")
        self.assertEqual(decision.mode, macos_tray.UPDATE_CHECK)
        self.assertEqual(decision.message, "Mise à jour interrompue : boom")

    def test_english_carries_the_same_flow(self):
        english = macos_tray.LABELS["en"]
        decision = macos_tray.update_after_check({"state": "available", "release": "v1.2.0"}, english)
        self.assertEqual(decision.title, "Install version 1.2.0")


class UpdateClickTest(TrayBindingTest):
    """The two-step flow, on the real menu item, with a fake rumps."""

    def setUp(self):
        super().setUp()
        self.notify = mock.patch.object(macos_tray, "notify").start()
        self.rumps = FakeRumps()

    def _tray(self, state=IDLE):
        return build(self.rumps, FakeController([(state, None)]))

    def _click(self, tray):
        tray._update()
        if tray._update_worker is not None:
            tray._update_worker.join(2.0)
        tray.refresh()          # the main thread draws the result, not the worker

    def test_a_dictation_in_progress_refuses_the_update(self):
        # An update reinstalls packages; a recording is worth more, and an update
        # has no urgency.
        tray = self._tray(state=RECORDING)
        self._click(tray)
        self.assertIsNone(tray._update_worker)
        self.assertEqual(self.notify.call_args.args[1], "Une dictée est en cours — réessaie après.")

    def test_first_click_checks_second_click_installs(self):
        tray = self._tray()
        with mock.patch("aparte.update.check_update", return_value={"state": "available", "release": "v1.2.0"}) as check:
            self._click(tray)
        check.assert_called_once_with(fetch=True)   # network only because it was asked
        self.assertEqual(tray._update_item.title, "Installer la version 1.2.0")

        with mock.patch("aparte.update.apply_update", return_value=["ok", update_module.DONE_MARKER]) as apply_:
            self._click(tray)
        apply_.assert_called_once()
        self.assertEqual(tray._update_mode, macos_tray.UPDATE_DONE)
        self.assertEqual(tray._update_item.title, "Mise à jour installée — relance Aparté")

    def test_once_installed_the_item_stops_doing_anything(self):
        # Nothing left to install, and the running process still holds the old code.
        tray = self._tray()
        tray._update_mode = macos_tray.UPDATE_DONE
        with mock.patch("aparte.update.check_update") as check:
            self._click(tray)
        check.assert_not_called()

    def test_a_second_click_while_it_works_is_ignored(self):
        tray = self._tray()
        tray._update_busy = True
        with mock.patch("aparte.update.check_update") as check:
            tray._update()
        check.assert_not_called()

    def test_a_crash_in_the_worker_leaves_the_item_usable(self):
        tray = self._tray()
        with mock.patch("aparte.update.check_update", side_effect=RuntimeError("git exploded")):
            self._click(tray)
        self.assertEqual(tray._update_mode, macos_tray.UPDATE_CHECK)
        self.assertFalse(tray._update_busy)
        self.assertIn("git exploded", self.notify.call_args.args[1])


def _png_rgba(path):
    """Decode a PNG into (width, height, pixels) with the standard library only.

    Pillow is not a project dependency, and the guarantees below are worth decoding
    for: an icon that renders as nothing is exactly the M8 defect M6 exists to close,
    and a header check alone would not catch a fully transparent file.
    """
    data = path.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"{path.name} is not a PNG")
    idat, header, offset = b"", None, 8
    while offset < len(data):
        (length,) = struct.unpack(">I", data[offset:offset + 4])
        kind = data[offset + 4:offset + 8]
        payload = data[offset + 8:offset + 8 + length]
        if kind == b"IHDR":
            header = payload
        elif kind == b"IDAT":
            idat += payload
        offset += 12 + length
    width, height, depth, colour, _comp, _filt, interlace = struct.unpack(">IIBBBBB", header)
    if (depth, colour, interlace) != (8, 6, 0):
        raise ValueError(f"{path.name}: expected 8-bit RGBA, non-interlaced")
    raw = zlib.decompress(idat)
    stride, pixels, previous = width * 4, [], bytearray(width * 4)
    for row in range(height):
        start = row * (stride + 1)
        method, line = raw[start], bytearray(raw[start + 1:start + 1 + stride])
        for i in range(stride):
            left = line[i - 4] if i >= 4 else 0
            up = previous[i]
            upleft = previous[i - 4] if i >= 4 else 0
            if method == 1:
                line[i] = (line[i] + left) & 0xFF
            elif method == 2:
                line[i] = (line[i] + up) & 0xFF
            elif method == 3:
                line[i] = (line[i] + (left + up) // 2) & 0xFF
            elif method == 4:
                p = left + up - upleft
                pa, pb, pc = abs(p - left), abs(p - up), abs(p - upleft)
                nearest = left if (pa <= pb and pa <= pc) else (up if pb <= pc else upleft)
                line[i] = (line[i] + nearest) & 0xFF
        pixels.extend(tuple(line[i:i + 4]) for i in range(0, stride, 4))
        previous = line
    return width, height, pixels


class IconAssetTest(unittest.TestCase):
    """The two committed PNGs. No build step: a contributor gets them as they are."""

    def setUp(self):
        self.icons = {
            name: _png_rgba(macos_tray.ASSETS_DIR / name)
            for name in (ICON_IDLE, ICON_RECORDING)
        }

    def test_both_are_forty_pixel_squares(self):
        # 40 px lands exactly on 20 points on a Retina screen, and halves cleanly
        # otherwise — rumps displays a menu-bar image at 20 points.
        for name, (width, height, _) in self.icons.items():
            with self.subTest(icon=name):
                self.assertEqual((width, height), (40, 40))

    def test_they_are_template_images_black_plus_alpha(self):
        # macOS tints a template image itself and reads only the alpha channel. A
        # coloured pixel would be silently ignored at runtime — and a sign the file
        # was re-exported from something other than its monochrome source.
        for name, (_, _, pixels) in self.icons.items():
            with self.subTest(icon=name):
                coloured = [p for p in pixels if p[3] > 0 and p[:3] != (0, 0, 0)]
                self.assertEqual(coloured, [])

    def test_neither_icon_is_invisible(self):
        # A fully transparent icon draws nothing at all: precisely the M8 defect.
        for name, (_, _, pixels) in self.icons.items():
            with self.subTest(icon=name):
                self.assertGreater(sum(1 for p in pixels if p[3] > 200), 100)

    def test_recording_is_visibly_heavier_than_idle(self):
        # The design decision, made testable: the state is read from the corner of
        # the eye, so the two silhouettes must differ in ink mass, not just in shape.
        ink = {name: sum(1 for p in pixels if p[3] > 200) for name, (_, _, pixels) in self.icons.items()}
        self.assertGreater(ink[ICON_RECORDING], ink[ICON_IDLE] * 1.5)


class LanguageTest(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch("aparte.macos_locale.sys.platform", "linux")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_the_menu_follows_the_desktop_language(self):
        with mock.patch.dict("os.environ", {"LC_ALL": "", "LC_MESSAGES": "", "LANG": "fr_CA.UTF-8"}):
            self.assertEqual(labels()["quit"], "Quitter")
        with mock.patch.dict("os.environ", {"LC_ALL": "", "LC_MESSAGES": "", "LANG": "en_US.UTF-8"}):
            self.assertEqual(labels()["quit"], "Quit")

    def test_no_language_at_all_falls_back_to_english(self):
        with mock.patch.dict("os.environ", {"LC_ALL": "", "LC_MESSAGES": "", "LANG": ""}):
            self.assertEqual(labels()["quit"], "Quit")

    def test_finder_language_comes_from_foundation_without_shell_locale(self):
        foundation = mock.Mock()
        foundation.NSLocale.preferredLanguages.return_value = ["fr-CA", "en-CA"]
        with mock.patch("aparte.macos_locale.sys.platform", "darwin"):
            with mock.patch.dict("sys.modules", {"Foundation": foundation}):
                with mock.patch.dict("os.environ", {"LC_ALL": "", "LC_MESSAGES": "", "LANG": ""}):
                    self.assertEqual(labels()["quit"], "Quitter")

    def test_both_languages_carry_exactly_the_same_keys(self):
        # A label added on one side only is a menu item that reads in the wrong
        # language, or a KeyError while drawing the menu.
        self.assertEqual(set(macos_tray.LABELS["fr"]), set(macos_tray.LABELS["en"]))


if __name__ == "__main__":
    unittest.main()
