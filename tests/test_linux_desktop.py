import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from whispr_flow_linux.linux_desktop import build_desktop_entry, install_desktop_entry, user_applications_dir


class LinuxDesktopTest(unittest.TestCase):
    def test_build_desktop_entry_uses_command(self):
        entry = build_desktop_entry(["/tmp/whispr-flow", "desktop"])
        self.assertIn("Name=Whispr Flow Linux", entry)
        self.assertIn("Exec=/tmp/whispr-flow desktop", entry)

    def test_user_applications_dir_uses_xdg_data_home(self):
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.dict(os.environ, {"XDG_DATA_HOME": directory}):
                self.assertEqual(user_applications_dir(), Path(directory) / "applications")

    def test_install_desktop_entry_writes_user_file(self):
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.dict(os.environ, {"XDG_DATA_HOME": directory}):
                path = install_desktop_entry(["whispr-flow", "desktop"])
                self.assertEqual(path, Path(directory) / "applications" / "whispr-flow-linux.desktop")
                self.assertIn("Exec=whispr-flow desktop", path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
