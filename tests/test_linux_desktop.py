import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aparte.linux_desktop import (
    autostart_dir,
    build_autostart_entry,
    build_desktop_entry,
    install_autostart_entry,
    install_desktop_entry,
    remove_legacy_entries,
    uninstall_autostart_entry,
    user_applications_dir,
)


class LinuxDesktopTest(unittest.TestCase):
    def test_build_desktop_entry_uses_command(self):
        entry = build_desktop_entry(["/tmp/aparte", "desktop"])
        self.assertIn("Name=Aparté", entry)
        self.assertIn("Exec=/tmp/aparte desktop", entry)

    def test_user_applications_dir_uses_xdg_data_home(self):
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.dict(os.environ, {"XDG_DATA_HOME": directory}):
                self.assertEqual(user_applications_dir(), Path(directory) / "applications")

    def test_install_desktop_entry_writes_user_file(self):
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.dict(os.environ, {"XDG_DATA_HOME": directory}):
                path = install_desktop_entry(["aparte", "desktop"])
                self.assertEqual(path, Path(directory) / "applications" / "aparte.desktop")
                self.assertIn("Exec=aparte desktop", path.read_text(encoding="utf-8"))

    def test_autostart_entry_runs_server_without_browser(self):
        entry = build_autostart_entry(["aparte", "desktop", "--no-browser"])
        self.assertIn("Exec=aparte desktop --no-browser", entry)
        self.assertIn("X-GNOME-Autostart-enabled=true", entry)

    def test_install_and_uninstall_autostart_entry(self):
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": directory}):
                self.assertEqual(autostart_dir(), Path(directory) / "autostart")
                path = install_autostart_entry(["aparte", "desktop", "--no-browser"])
                self.assertEqual(path, Path(directory) / "autostart" / "aparte.desktop")
                self.assertTrue(path.exists())
                self.assertEqual(uninstall_autostart_entry(), path)
                self.assertFalse(path.exists())
                self.assertIsNone(uninstall_autostart_entry())


@unittest.skipUnless(shutil.which("desktop-file-validate"), "desktop-file-validate not installed")
class DesktopEntrySpecTest(unittest.TestCase):
    """Both entries must satisfy the freedesktop spec, not merely look right.

    `Audio` without `AudioVideo` is an error the validator promises to make
    fatal, and three main categories make the app show up three times in the
    application menu.
    """

    def _validate(self, contents: str) -> str:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "aparte.desktop"
            path.write_text(contents, encoding="utf-8")
            result = subprocess.run(
                ["desktop-file-validate", str(path)],
                capture_output=True,
                text=True,
            )
            return result.stdout + result.stderr

    def test_the_launcher_entry_is_valid(self):
        self.assertEqual(self._validate(build_desktop_entry()), "")

    def test_the_autostart_entry_is_valid(self):
        self.assertEqual(self._validate(build_autostart_entry()), "")


class LegacyEntriesTest(unittest.TestCase):
    """Installing must not leave the pre-rename Murmur entries behind."""

    def test_install_removes_the_old_launcher_and_autostart_entry(self):
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.dict(os.environ, {"XDG_DATA_HOME": directory, "XDG_CONFIG_HOME": directory}):
                old_launcher = Path(directory) / "applications" / "murmur.desktop"
                old_autostart = Path(directory) / "autostart" / "murmur.desktop"
                for path in (old_launcher, old_autostart):
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text("[Desktop Entry]\nName=Murmur\n", encoding="utf-8")

                install_desktop_entry(["aparte", "desktop"])
                install_autostart_entry(["aparte", "desktop", "--no-browser"])

                self.assertFalse(old_launcher.exists())
                self.assertFalse(old_autostart.exists())
                self.assertTrue((Path(directory) / "applications" / "aparte.desktop").exists())
                self.assertTrue((Path(directory) / "autostart" / "aparte.desktop").exists())

    def test_removing_legacy_entries_is_safe_when_absent(self):
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.dict(os.environ, {"XDG_DATA_HOME": directory, "XDG_CONFIG_HOME": directory}):
                self.assertEqual(remove_legacy_entries(), [])


if __name__ == "__main__":
    unittest.main()
