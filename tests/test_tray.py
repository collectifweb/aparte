import os
import unittest
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


if __name__ == "__main__":
    unittest.main()
