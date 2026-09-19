"""Shortcut delivery is sequential, with real process-owned processing markers."""
from contextlib import ExitStack, contextmanager
import os
from pathlib import Path
import selectors
import subprocess
import sys
import tempfile
import textwrap
import unittest
from unittest import mock

from aparte import cli, lifecycle
from aparte.config import Settings


_PROCESSING_DICTATION = textwrap.dedent("""
    import sys
    from pathlib import Path
    from types import SimpleNamespace
    from unittest import mock
    from aparte import cli
    from aparte.config import Settings

    capture = SimpleNamespace(audio_path=Path(sys.argv[1]))
    def transcribe(*args):
        print('processing', flush=True)
        assert sys.stdin.readline().strip() == 'finish'
        return 'synthetic dictation A'

    with mock.patch.object(cli, 'get_active_session', return_value=capture), \\
         mock.patch.object(cli, 'stop_toggle_recording', return_value=capture), \\
         mock.patch.object(cli, 'transcribe_path', side_effect=transcribe), \\
         mock.patch.object(cli, 'notify'), \\
         mock.patch.object(cli, 'play_beep'), \\
         mock.patch.object(cli.history, 'record'), \\
         mock.patch.object(cli, 'copy_text'), \\
         mock.patch.object(cli, 'paste_text') as paste:
        cli.toggle_dictation(cli.build_parser().parse_args(['toggle']), Settings())
        paste.assert_called_once_with('synthetic dictation A', 'clipboard')
    print('delivered', flush=True)
""")


class SuccessiveDictationsTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(mock.patch.dict(os.environ, {
            "APARTE_CONFIG": str(self.root / "config.json"),
            "APARTE_RUNTIME_DIR": str(self.root),
            "XDG_CONFIG_HOME": str(self.root / "config"),
            "XDG_DATA_HOME": str(self.root / "data"),
            "XDG_STATE_HOME": str(self.root / "state"),
            "XDG_RUNTIME_DIR": str(self.root / "runtime"),
            "XDG_CACHE_HOME": str(self.root / "cache"),
        }))
        self.notify = self.stack.enter_context(mock.patch.object(cli, "notify"))
        self.beep = self.stack.enter_context(mock.patch.object(cli, "play_beep"))
        self.start = self.stack.enter_context(mock.patch.object(cli, "start_toggle_recording"))
        self.copy = self.stack.enter_context(mock.patch.object(cli, "copy_text"))
        self.paste = self.stack.enter_context(mock.patch.object(cli, "paste_text"))
        self.args = cli.build_parser().parse_args(["toggle"])
        self.settings = Settings(beep=True)

    def read_child(self, process):
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            self.assertTrue(selector.select(timeout=5), "child did not reach expected stage")
        return process.stdout.readline().strip()

    @contextmanager
    def processing_in_child(self):
        source = self.root / "synthetic-a.wav"
        source.write_bytes(b"synthetic capture, never decoded")
        process = subprocess.Popen([sys.executable, "-c", _PROCESSING_DICTATION, str(source)],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True)
        try:
            self.assertEqual(self.read_child(process), "processing")
            yield process
        finally:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=5)
            process.stdin.close()
            process.stdout.close()
            process.stderr.close()

    def test_a_processing_refuses_b_before_beep_then_a_delivery_allows_b(self):
        with self.processing_in_child() as process:
            self.assertTrue(lifecycle.is_processing())
            with self.assertRaises(cli.ToggleSessionError):
                cli.toggle_dictation(self.args, self.settings)
            self.start.assert_not_called()
            self.beep.assert_not_called()
            self.copy.assert_not_called()
            self.paste.assert_not_called()
            self.assertEqual(self.notify.call_args.args[0], "Dictée précédente en cours")
            self.assertIn("réappuie", self.notify.call_args.args[1])

            process.stdin.write("finish\n")
            process.stdin.flush()
            self.assertEqual(self.read_child(process), "delivered")
            self.assertEqual(process.wait(timeout=5), 0)
            self.assertFalse(lifecycle.is_processing())
            cli.toggle_dictation(self.args, self.settings)
            self.start.assert_called_once()
            self.beep.assert_called_once_with("start")
            self.assertEqual(self.notify.call_args.args[0], "🎙️ Dictée en cours")

    def test_existing_capture_can_be_stopped_while_a_previous_dictation_processes(self):
        capture = mock.Mock(audio_path=self.root / "synthetic-b.wav")
        with self.processing_in_child():
            with mock.patch.object(cli, "get_active_session", return_value=capture):
                with mock.patch.object(cli, "stop_toggle_recording", return_value=capture) as stop:
                    with mock.patch.object(cli, "_finish_dictation", return_value="dictation B") as finish:
                        self.assertEqual(cli.toggle_dictation(self.args, self.settings), "dictation B")
            stop.assert_called_once()
            finish.assert_called_once_with(capture.audio_path, self.args, self.settings)
            self.start.assert_not_called()
            self.beep.assert_called_once_with("stop")
            self.assertTrue(lifecycle.is_processing())

    def test_processing_check_still_owns_the_capture_transition(self):
        script = ("from aparte.session import toggle_session_transition, ToggleSessionError;\n"
                  "try:\n with toggle_session_transition(): pass\n"
                  "except ToggleSessionError: raise SystemExit(17)")

        def inspect_processing():
            result = subprocess.run([sys.executable, "-c", script], check=False, timeout=5)
            self.assertEqual(result.returncode, 17)
            return True

        with mock.patch.object(cli, "is_processing", side_effect=inspect_processing):
            with self.assertRaises(cli.ToggleSessionError):
                cli.toggle_dictation(self.args, self.settings)
        self.start.assert_not_called()
        self.beep.assert_not_called()


if __name__ == "__main__":
    unittest.main()
