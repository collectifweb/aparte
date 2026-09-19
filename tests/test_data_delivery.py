"""Storage failures through the real UI/CLI entry points, without user data."""
import errno
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aparte import cli, config, desktop, history
from aparte.config import Settings
from test_desktop import make_request


class DataDeliveryTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        environment = {
            "APARTE_CONFIG": str(self.root / "config.json"),
            "APARTE_RUNTIME_DIR": str(self.root / "runtime"),
            "XDG_CONFIG_HOME": str(self.root / "config"),
            "XDG_STATE_HOME": str(self.root / "state"),
            "MURMUR_CONFIG": "",
        }
        patcher = mock.patch.dict(os.environ, environment)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_settings_save_failure_is_reported_and_previous_values_remain_readable(self):
        config.update_config({"language": None, "hotwords": ["Aparté"], "beep": False})
        before = Path(os.environ["APARTE_CONFIG"]).read_bytes()
        with mock.patch.object(config, "_atomic_write", side_effect=OSError(errno.ENOSPC, "disk full")):
            response = make_request("POST", "/api/config", b'{"beep":true}')
        self.assertEqual(response["status"], 500)
        self.assertFalse(json.loads(response["body"])["ok"])
        self.assertEqual(Path(os.environ["APARTE_CONFIG"]).read_bytes(), before)
        response = make_request("GET", "/api/config")
        self.assertEqual(response["status"], 200)
        values = json.loads(response["body"])
        self.assertIsNone(values["language"])
        self.assertFalse(values["beep"])
        self.assertEqual(values["hotwords"], ["Aparté"])

    def test_history_write_failure_does_not_prevent_dictation_delivery(self):
        history.record("ancienne dictée synthétique")
        source = self.root / "synthetic.wav"
        source.write_bytes(b"synthetic audio")
        args = cli.build_parser().parse_args(["dictate", "--target", "copy", "--no-polish"])
        with mock.patch.object(history, "_write", side_effect=OSError(errno.ENOSPC, "disk full")), \
                mock.patch.object(cli, "record_wav", return_value=source), \
                mock.patch.object(cli, "transcribe_path", return_value="nouvelle dictée synthétique"), \
                mock.patch.object(cli, "notify"), \
                mock.patch.object(cli, "copy_text") as copy:
            result = cli.dictate_once(args, Settings())
        self.assertEqual(result, "nouvelle dictée synthétique")
        copy.assert_called_once_with(result)
        self.assertEqual(history.last(), "ancienne dictée synthétique")
        self.assertFalse(source.exists())

    def test_opening_desktop_migrates_recognized_shortcuts_even_when_server_exists(self):
        with mock.patch.object(desktop, "migrate_hotkey_logging", return_value=["custom0"]) as migrate, \
                mock.patch.object(desktop, "already_running", return_value="http://127.0.0.1:8765"), \
                mock.patch.object(desktop.webbrowser, "open") as browser, \
                mock.patch("builtins.print"):
            desktop.run_desktop("127.0.0.1", 8765, Settings(), open_browser=False)
        migrate.assert_called_once_with()
        browser.assert_not_called()


if __name__ == "__main__":
    unittest.main()
