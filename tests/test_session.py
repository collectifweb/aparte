import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from murmur import session


class ToggleSessionTest(unittest.TestCase):
    def test_runtime_dir_can_be_overridden(self):
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.dict(os.environ, {"MURMUR_RUNTIME_DIR": directory}):
                self.assertEqual(session.get_runtime_dir(), Path(directory))

    def test_stale_session_is_cleared(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "toggle-session.json"
            state.write_text(
                '{"pid": 999999999, "audio_path": "/tmp/missing.wav", "sample_rate": 16000, "started_at": 1}',
                encoding="utf-8",
            )
            with mock.patch.dict(os.environ, {"MURMUR_RUNTIME_DIR": directory}):
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
                        self.assertEqual(session.get_runtime_dir(), Path(temp_dir) / f"murmur-{os.getuid()}")
            finally:
                read_only.chmod(0o700)


if __name__ == "__main__":
    unittest.main()
