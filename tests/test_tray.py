import os
import unittest
from contextlib import contextmanager
from unittest import mock

from aparte import tray


class TrayAvailabilityTest(unittest.TestCase):
    def test_returns_nothing_without_the_system_bindings(self):
        """No PyGObject, no icon — and the server must start exactly as before."""
        with mock.patch.object(tray, "AVAILABLE", False):
            self.assertIsNone(tray.build_tray("http://127.0.0.1:8765", None, lambda: None))

    def test_a_broken_indicator_does_not_take_the_app_down(self):
        with mock.patch.object(tray, "AVAILABLE", True):
            with mock.patch.object(tray, "Tray", side_effect=RuntimeError("pas de hôte de notification")):
                self.assertIsNone(tray.build_tray("http://127.0.0.1:8765", None, lambda: None))

    def test_both_icon_states_are_shipped(self):
        for name in (tray.ICON_IDLE, tray.ICON_RECORDING):
            self.assertTrue((tray.ASSETS_DIR / f"{name}.svg").exists(), name)

    def test_every_svg_declares_its_format_within_the_sniff_window(self):
        """gdk-pixbuf recognises a file from its first 256 bytes.

        A comment placed above the root tag pushes `<svg` past that window: the
        loader answers "unrecognised image format" and the panel draws an empty
        gap where the icon should be. That is exactly what happened to the idle
        tray icon, whose header comment put the root tag at byte 403 — so the
        icon only ever appeared while recording, which uses the other file.
        Comments belong inside the root element.
        """
        for path in sorted(tray.ASSETS_DIR.glob("*.svg")):
            with self.subTest(icon=path.name):
                start = path.read_bytes().find(b"<svg")
                self.assertNotEqual(start, -1, "no root tag at all")
                self.assertLess(start, 256)


class TrayLabelsTest(unittest.TestCase):
    def _labels_for(self, **env):
        base = {"LC_ALL": "", "LC_MESSAGES": "", "LANG": ""}
        with mock.patch.dict(os.environ, {**base, **env}):
            return tray._labels()

    def test_a_french_desktop_gets_a_french_menu(self):
        self.assertEqual(self._labels_for(LANG="fr_CA.UTF-8")["open"], "Ouvrir Aparté")

    def test_anything_else_gets_english(self):
        self.assertEqual(self._labels_for(LANG="de_DE.UTF-8")["open"], "Open Aparté")

    def test_lc_all_wins_over_lang(self):
        self.assertEqual(self._labels_for(LC_ALL="fr_FR.UTF-8", LANG="en_US.UTF-8")["open"], "Ouvrir Aparté")

    def test_both_languages_carry_the_same_entries(self):
        self.assertEqual(set(tray.LABELS["fr"]), set(tray.LABELS["en"]))


class TrayLifecycleTest(unittest.TestCase):
    def setUp(self):
        self.tray = object.__new__(tray.Tray)
        self.tray.labels = tray.LABELS["fr"]
        self.tray.state = "idle"
        self.tray.recording = False
        self.tray.quitting = False
        self.tray.quit_item = mock.Mock()
        self.tray.indicator = mock.Mock()
        self.tray.on_quit = mock.Mock()

    def test_only_live_capture_uses_the_recording_icon(self):
        for state in ("recording", "recoverable", "processing", "idle"):
            with self.subTest(state=state), mock.patch.object(tray, "get_dictation_state", return_value=state):
                self.assertTrue(self.tray._refresh())
                self.tray.indicator.set_icon_full.assert_called_with(
                    tray.ICON_RECORDING if state == "recording" else tray.ICON_IDLE,
                    self.tray.labels[state])

    def test_unreadable_state_is_not_announced_idle(self):
        with mock.patch.object(tray, "get_dictation_state", side_effect=RuntimeError("unavailable")):
            self.assertTrue(self.tray._refresh())
        self.assertEqual(self.tray.state, "unknown")
        self.tray.indicator.set_title.assert_called_with(self.tray.labels["unknown"])

    def test_double_quit_starts_one_worker_and_disables_menu_item(self):
        with mock.patch.object(tray.threading, "Thread") as thread:
            self.tray._quit()
            self.tray._quit()
        thread.assert_called_once_with(target=self.tray._quit_worker, daemon=True)
        thread.return_value.start.assert_called_once()
        self.tray.quit_item.set_sensitive.assert_called_once_with(False)

    def test_callback_is_inside_shutdown_guard_and_gtk_quit_uses_idle_queue(self):
        active = []

        @contextmanager
        def guarded():
            active.append(True)
            yield "saved-id"
            active.pop()

        self.tray.on_quit.side_effect = lambda: self.assertEqual(active, [True])
        with mock.patch.object(tray, "prepare_shutdown", guarded), mock.patch.object(tray, "notify") as notify:
            with mock.patch.object(tray, "GLib", create=True) as glib, mock.patch.object(tray, "Gtk", create=True) as gtk:
                self.tray._quit_worker()
                self.tray.on_quit.assert_called_once()
                gtk.main_quit.assert_not_called()
                glib.idle_add.assert_called_once_with(self.tray._quit_finished, True)
                self.tray._quit_finished(True)
                gtk.main_quit.assert_called_once()
        notify.assert_called_once_with(self.tray.labels["quit_saved"], self.tray.labels["quit_saved_detail"])

    def test_failed_stop_neither_stops_server_nor_quits_gtk(self):
        with mock.patch.object(tray, "prepare_shutdown", side_effect=tray.ShutdownError("stop")):
            with mock.patch.object(tray, "GLib", create=True) as glib, mock.patch.object(tray, "notify") as notify:
                self.tray._quit_worker()
                self.tray.on_quit.assert_not_called()
                glib.idle_add.assert_called_once_with(self.tray._quit_finished, False)
                notify.assert_called_once_with(self.tray.labels["quit_failed"], self.tray.labels["quit_stop"], urgency="critical")
        with mock.patch.object(self.tray, "_refresh"):
            self.tray._quit_finished(False)
        self.assertFalse(self.tray.quitting)
        self.tray.quit_item.set_sensitive.assert_called_once_with(True)


if __name__ == "__main__":
    unittest.main()
