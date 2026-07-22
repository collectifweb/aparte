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
