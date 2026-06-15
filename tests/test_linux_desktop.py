import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from murmur.linux_desktop import (
    autostart_dir,
    build_autostart_entry,
    build_desktop_entry,
    detect_desktop_environment,
    hotkey_guidance,
    install_autostart_entry,
    install_desktop_entry,
    toggle_command,
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


class HotkeyGuidanceTest(unittest.TestCase):
    def test_toggle_command_binds_toggle_with_target(self):
        with mock.patch("murmur.linux_desktop.shutil.which", return_value="/venv/bin/murmur"):
            self.assertEqual(toggle_command("paste"), ["/venv/bin/murmur", "toggle", "--target", "paste"])

    def test_toggle_command_falls_back_to_module_invocation(self):
        with mock.patch("murmur.linux_desktop.shutil.which", return_value=None):
            command = toggle_command("copy")
        self.assertEqual(command[1:], ["-m", "murmur", "toggle", "--target", "copy"])

    def test_detect_desktop_environment_normalizes_tokens(self):
        with mock.patch.dict(os.environ, {"XDG_CURRENT_DESKTOP": "X-Cinnamon"}, clear=False):
            self.assertEqual(detect_desktop_environment(), "cinnamon")
        with mock.patch.dict(os.environ, {"XDG_CURRENT_DESKTOP": "ubuntu:GNOME"}, clear=False):
            self.assertEqual(detect_desktop_environment(), "gnome")

    def test_detect_desktop_environment_unknown_is_generic(self):
        env = {"XDG_CURRENT_DESKTOP": "Weird-WM", "DESKTOP_SESSION": ""}
        with mock.patch.dict(os.environ, env, clear=False):
            self.assertEqual(detect_desktop_environment(), "generic")

    def test_hotkey_guidance_uses_paste_when_tool_present(self):
        env = {"WAYLAND_DISPLAY": "wayland-0", "DISPLAY": "", "XDG_CURRENT_DESKTOP": "GNOME"}
        with mock.patch.dict(os.environ, env, clear=False):
            with mock.patch("murmur.linux_desktop.shutil.which", return_value="/usr/bin/wtype"):
                guidance = hotkey_guidance()
        self.assertTrue(guidance["paste_ok"])
        self.assertEqual(guidance["target"], "paste")
        self.assertIn("toggle --target paste", guidance["command"])
        self.assertEqual(guidance["session_type"], "wayland")

    def test_hotkey_guidance_falls_back_to_copy_without_paste_tool(self):
        env = {"WAYLAND_DISPLAY": "", "DISPLAY": ":0", "XDG_CURRENT_DESKTOP": "XFCE"}
        with mock.patch.dict(os.environ, env, clear=False):
            with mock.patch("murmur.linux_desktop.shutil.which", return_value=None):
                guidance = hotkey_guidance()
        self.assertFalse(guidance["paste_ok"])
        self.assertEqual(guidance["target"], "copy")
        self.assertIn("toggle --target copy", guidance["command"])
        self.assertEqual(guidance["session_type"], "x11")


if __name__ == "__main__":
    unittest.main()
