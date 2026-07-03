import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from murmur.linux_desktop import (
    autostart_dir,
    build_autostart_entry,
    build_desktop_entry,
    install_autostart_entry,
    install_desktop_entry,
    uninstall_autostart_entry,
    user_applications_dir,
)


class LinuxDesktopTest(unittest.TestCase):
    def test_build_desktop_entry_uses_command(self):
        entry = build_desktop_entry(["/tmp/murmur", "desktop"])
        self.assertIn("Name=Murmur", entry)
        self.assertIn("Exec=/tmp/murmur desktop", entry)

    def test_user_applications_dir_uses_xdg_data_home(self):
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.dict(os.environ, {"XDG_DATA_HOME": directory}):
                self.assertEqual(user_applications_dir(), Path(directory) / "applications")

    def test_install_desktop_entry_writes_user_file(self):
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.dict(os.environ, {"XDG_DATA_HOME": directory}):
                path = install_desktop_entry(["murmur", "desktop"])
                self.assertEqual(path, Path(directory) / "applications" / "murmur.desktop")
                self.assertIn("Exec=murmur desktop", path.read_text(encoding="utf-8"))

    def test_autostart_entry_runs_server_without_browser(self):
        entry = build_autostart_entry(["murmur", "desktop", "--no-browser"])
        self.assertIn("Exec=murmur desktop --no-browser", entry)
        self.assertIn("X-GNOME-Autostart-enabled=true", entry)

    def test_install_and_uninstall_autostart_entry(self):
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": directory}):
                self.assertEqual(autostart_dir(), Path(directory) / "autostart")
                path = install_autostart_entry(["murmur", "desktop", "--no-browser"])
                self.assertEqual(path, Path(directory) / "autostart" / "murmur.desktop")
                self.assertTrue(path.exists())
                self.assertEqual(uninstall_autostart_entry(), path)
                self.assertFalse(path.exists())
                self.assertIsNone(uninstall_autostart_entry())


if __name__ == "__main__":
    unittest.main()
