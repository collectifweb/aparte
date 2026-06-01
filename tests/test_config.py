import os
import tempfile
import unittest
from pathlib import Path

from whispr_flow_linux.config import Settings, load_config, update_config, write_default_config


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
        old_config = os.environ.get("WHISPR_CONFIG")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text('{"default_style": "casual", "replacements": {"foo": "FOO"}}', encoding="utf-8")
            os.environ["WHISPR_CONFIG"] = str(path)
            try:
                settings = Settings.from_env()
            finally:
                if old_config is None:
                    os.environ.pop("WHISPR_CONFIG", None)
                else:
                    os.environ["WHISPR_CONFIG"] = old_config
            self.assertEqual(settings.default_style, "casual")
            self.assertEqual(settings.replacements, {"foo": "FOO"})


if __name__ == "__main__":
    unittest.main()
