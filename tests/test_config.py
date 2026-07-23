import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aparte.config import (
    Settings,
    load_config,
    migrate_legacy_config,
    update_config,
    write_default_config,
)


class RecordingCeilingTest(unittest.TestCase):
    """Le plafond qui empêche un micro oublié d'enregistrer sans fin."""

    def _ceiling(self, value) -> int:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            write_default_config(path)
            update_config({"max_recording_seconds": value}, path)
            with mock.patch.dict(os.environ, {"APARTE_CONFIG": str(path)}):
                return Settings.from_env().max_recording_seconds

    def test_a_chosen_ceiling_is_kept(self):
        self.assertEqual(self._ceiling(900), 900)

    def test_zero_falls_back_instead_of_meaning_no_limit(self):
        """`positive_int` rend 0 sur une valeur illisible : en faire « pas de
        plafond » rendrait une faute de frappe indistinguable d'un choix."""
        self.assertEqual(self._ceiling(0), 300)
        self.assertEqual(self._ceiling("bientôt"), 300)
        self.assertEqual(self._ceiling(-5), 300)

    def test_french_is_the_default_language(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            write_default_config(path)
            self.assertEqual(load_config(path)["language"], "fr")


class ConfigTest(unittest.TestCase):
    def test_write_and_load_default_config(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            write_default_config(path)
            data = load_config(path)
            self.assertEqual(data["transcriber"], "auto")
            self.assertIn("whisper flow", data["replacements"])

    def test_update_config_merges_and_ignores_unknown_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            write_default_config(path)
            merged = update_config(
                {"model": "base", "language": "fr", "bogus": "nope"}, path
            )
            self.assertEqual(merged["model"], "base")
            self.assertEqual(merged["language"], "fr")
            self.assertNotIn("bogus", merged)
            # Untouched defaults are preserved across the write.
            self.assertEqual(merged["cleanup_level"], "medium")
            self.assertEqual(load_config(path)["model"], "base")

    def test_update_config_creates_file_when_absent(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nested" / "config.json"
            merged = update_config({"default_style": "casual"}, path)
            self.assertTrue(path.exists())
            self.assertEqual(merged["default_style"], "casual")

    def test_settings_uses_whispr_config_override(self):
        old_config = os.environ.get("APARTE_CONFIG")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text('{"default_style": "casual", "replacements": {"foo": "FOO"}}', encoding="utf-8")
            os.environ["APARTE_CONFIG"] = str(path)
            try:
                settings = Settings.from_env()
            finally:
                if old_config is None:
                    os.environ.pop("APARTE_CONFIG", None)
                else:
                    os.environ["APARTE_CONFIG"] = old_config
            self.assertEqual(settings.default_style, "casual")
            self.assertEqual(settings.replacements, {"foo": "FOO"})


class LegacyConfigMigrationTest(unittest.TestCase):
    """The app was renamed from Murmur to Aparté; existing configs must survive."""

    def _clean_env(self, directory):
        return mock.patch.dict(
            os.environ,
            {"XDG_CONFIG_HOME": directory, "APARTE_CONFIG": "", "MURMUR_CONFIG": ""},
            clear=False,
        )

    def test_pre_rename_config_moves_to_the_new_location(self):
        with tempfile.TemporaryDirectory() as directory:
            with self._clean_env(directory):
                legacy = Path(directory) / "murmur" / "config.json"
                legacy.parent.mkdir(parents=True)
                legacy.write_text('{"model": "base"}', encoding="utf-8")

                moved = migrate_legacy_config()

                self.assertEqual(moved, Path(directory) / "aparte" / "config.json")
                self.assertFalse(legacy.exists())
                self.assertEqual(load_config()["model"], "base")

    def test_existing_config_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            with self._clean_env(directory):
                legacy = Path(directory) / "murmur" / "config.json"
                legacy.parent.mkdir(parents=True)
                legacy.write_text('{"model": "base"}', encoding="utf-8")
                current = Path(directory) / "aparte" / "config.json"
                current.parent.mkdir(parents=True)
                current.write_text('{"model": "medium"}', encoding="utf-8")

                self.assertIsNone(migrate_legacy_config())
                self.assertTrue(legacy.exists())
                self.assertEqual(load_config()["model"], "medium")

    def test_legacy_env_var_is_still_read(self):
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.dict(
                os.environ,
                {"XDG_CONFIG_HOME": directory, "APARTE_MODEL": "", "MURMUR_MODEL": "medium"},
                clear=False,
            ):
                self.assertEqual(Settings.from_env().model, "medium")


if __name__ == "__main__":
    unittest.main()
