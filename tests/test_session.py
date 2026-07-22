import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aparte import session


class StartRecordingTest(unittest.TestCase):
    def test_the_chosen_microphone_reaches_arecord(self):
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.dict(os.environ, {"APARTE_RUNTIME_DIR": directory}):
                with mock.patch.object(session.shutil, "which", return_value="/usr/bin/arecord"):
                    with mock.patch.object(session.subprocess, "Popen") as popen:
                        popen.return_value.pid = 4242
                        session.start_toggle_recording(16000, "plughw:CARD=Mini,DEV=0")
                command = popen.call_args.args[0]
        self.assertEqual(command[command.index("-D") + 1], "plughw:CARD=Mini,DEV=0")

    def test_no_microphone_chosen_leaves_the_command_untouched(self):
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.dict(os.environ, {"APARTE_RUNTIME_DIR": directory}):
                with mock.patch.object(session.shutil, "which", return_value="/usr/bin/arecord"):
                    with mock.patch.object(session.subprocess, "Popen") as popen:
                        popen.return_value.pid = 4242
                        session.start_toggle_recording()
                command = popen.call_args.args[0]
        self.assertNotIn("-D", command)


class ToggleSessionTest(unittest.TestCase):
    def test_runtime_dir_can_be_overridden(self):
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.dict(os.environ, {"APARTE_RUNTIME_DIR": directory}):
                self.assertEqual(session.get_runtime_dir(), Path(directory))

    def test_stale_session_is_cleared(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "toggle-session.json"
            state.write_text(
                '{"pid": 999999999, "audio_path": "/tmp/missing.wav", "sample_rate": 16000, "started_at": 1}',
                encoding="utf-8",
            )
            with mock.patch.dict(os.environ, {"APARTE_RUNTIME_DIR": directory}):
                self.assertIsNone(session.get_active_session())
                self.assertFalse(state.exists())

    def test_runtime_dir_falls_back_when_xdg_runtime_is_not_writable(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            read_only = Path(temp_dir) / "readonly"
            read_only.mkdir()
            read_only.chmod(0o500)
            try:
                with mock.patch.dict(
                    os.environ,
                    {"XDG_RUNTIME_DIR": str(read_only), "TMPDIR": temp_dir},
                    clear=False,
                ):
                    with mock.patch("tempfile.gettempdir", return_value=temp_dir):
                        self.assertEqual(session.get_runtime_dir(), Path(temp_dir) / f"aparte-{os.getuid()}")
            finally:
                read_only.chmod(0o700)


if __name__ == "__main__":
    unittest.main()
