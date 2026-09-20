"""CLI capture ownership: synthetic audio survives engine, polish and delivery errors."""
import argparse
from contextlib import redirect_stderr, redirect_stdout
import io
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from aparte import cli, recovery
from aparte.config import Settings


class CliRecoveryTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="aparte-cli-recovery-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.audio = self.root / "synthetic.wav"
        self.audio.write_bytes(b"synthetic audio only")
        environment = {
            "APARTE_CONFIG": str(self.root / "config.json"),
            "APARTE_RUNTIME_DIR": str(self.root / "runtime"),
            **{key: str(self.root / key.lower()) for key in (
                "XDG_CONFIG_HOME", "XDG_STATE_HOME", "XDG_DATA_HOME",
                "XDG_RUNTIME_DIR", "XDG_CACHE_HOME",
            )},
        }
        for patch in (mock.patch.dict(os.environ, environment),
                      mock.patch.object(cli, "notify"),
                      mock.patch.object(cli, "record_wav", return_value=self.audio),
                      mock.patch.object(cli, "copy_text"),
                      mock.patch.object(cli, "paste_text"),
                      mock.patch.object(cli, "is_macos", return_value=False)):
            patch.start()
            self.addCleanup(patch.stop)
        self.settings = Settings(beep=False)
        self.args = argparse.Namespace(seconds=1, sample_rate=16000, no_polish=False,
                                       style=None, cleanup_level=None, target="stdout",
                                       keep_audio=False, status=False)
        self.stderr = io.StringIO()
        context = redirect_stderr(self.stderr)
        context.__enter__()
        self.addCleanup(context.__exit__, None, None, None)

    def run_capture(self, command):
        if command == "dictate":
            return cli.dictate_once(self.args, self.settings)
        if command == "toggle":
            session = SimpleNamespace(audio_path=self.audio)
            with mock.patch.object(cli, "get_active_session", return_value=session), \
                    mock.patch.object(cli, "stop_toggle_recording", return_value=session):
                return cli.toggle_dictation(self.args, self.settings)
        output = io.StringIO()
        with redirect_stdout(output):
            return cli.main(["record", "--polish"])

    def assert_recoverable(self, expected_raw):
        entries = recovery.entries()
        self.assertEqual(len(entries), 1)
        with recovery.claim(entries[0]["id"]) as item:
            self.assertEqual(item.audio_path.read_bytes(), b"synthetic audio only")
            self.assertEqual(item.raw_text, expected_raw)
        self.assertFalse(self.audio.exists())
        self.assertIn("aparte recover retry", self.stderr.getvalue())

    def test_each_cli_capture_retains_audio_when_transcription_fails(self):
        for command in ("dictate", "toggle", "record"):
            with self.subTest(command=command):
                self.audio.write_bytes(b"synthetic audio only")
                with mock.patch.object(cli, "transcribe_path", side_effect=RuntimeError("engine failure")):
                    if command == "record":
                        self.assertEqual(self.run_capture(command), 1)
                    else:
                        with self.assertRaisesRegex(RuntimeError, "engine failure"):
                            self.run_capture(command)
                self.assert_recoverable(None)
                recovery.discard(recovery.entries()[0]["id"])

    def test_polish_failure_keeps_raw_without_running_the_engine_again(self):
        with mock.patch.object(cli, "transcribe_path", return_value="texte brut") as transcribe, \
                mock.patch.object(cli, "polish_text", side_effect=RuntimeError("polish failure")):
            with self.assertRaisesRegex(RuntimeError, "polish failure"):
                self.run_capture("dictate")
        self.assertFalse(transcribe.call_args.args[1].polish)
        self.assert_recoverable("texte brut")
        entry = recovery.entries()[0]
        retry_args = argparse.Namespace(no_polish=True, target="stdout")
        with mock.patch.object(cli, "transcribe_path", side_effect=AssertionError("must not retranscribe")):
            self.assertEqual(cli.retry_recovery(entry["id"], retry_args, self.settings), "texte brut")

    def test_delivery_failure_keeps_original_raw_text_and_audio(self):
        with mock.patch.object(cli, "transcribe_path", return_value="texte brut"), \
                mock.patch.object(cli, "polish_text", return_value="Texte poli."), \
                mock.patch.object(cli, "deliver_transcript", side_effect=RuntimeError("paste failed")):
            with self.assertRaisesRegex(RuntimeError, "paste failed"):
                self.run_capture("dictate")
        self.assert_recoverable("texte brut")

    def test_full_recovery_disk_keeps_original_and_reports_path(self):
        with mock.patch.object(cli, "transcribe_path", side_effect=RuntimeError("engine failure")), \
                mock.patch.object(recovery, "save_failure", side_effect=OSError("disk full")):
            with self.assertRaisesRegex(RuntimeError, "engine failure"):
                self.run_capture("dictate")
        self.assertTrue(self.audio.exists())
        self.assertEqual(self.audio.read_bytes(), b"synthetic audio only")
        self.assertIn(str(self.audio), self.stderr.getvalue())
        self.assertEqual(recovery.entries(), [])

    def test_success_removes_owned_audio_for_all_cli_capture_commands(self):
        for command in ("dictate", "toggle", "record"):
            with self.subTest(command=command):
                self.audio.write_bytes(b"synthetic audio only")
                with mock.patch.object(cli, "transcribe_path", return_value="bonjour"):
                    self.run_capture(command)
                self.assertFalse(self.audio.exists())
                self.assertEqual(recovery.entries(), [])

    def test_keep_audio_is_respected_after_success_and_failure(self):
        self.args.keep_audio = True
        with mock.patch.object(cli, "transcribe_path", return_value="bonjour"):
            self.run_capture("dictate")
        self.assertTrue(self.audio.exists())
        with mock.patch.object(cli, "transcribe_path", side_effect=RuntimeError("engine failure")):
            with self.assertRaises(RuntimeError):
                self.run_capture("dictate")
        self.assertTrue(self.audio.exists())
        self.assertEqual(len(recovery.entries()), 1)

    def test_keyboard_interrupt_never_removes_the_original(self):
        with mock.patch.object(cli, "transcribe_path", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.run_capture("dictate")
        self.assertTrue(self.audio.exists())

    def test_no_polish_skips_polisher_and_imported_audio_is_never_deleted(self):
        self.args.no_polish = True
        self.args.keep_audio = True
        with mock.patch.object(cli, "transcribe_path", return_value="brut"), \
                mock.patch.object(cli, "polish_text") as polish:
            self.assertEqual(self.run_capture("dictate"), "brut")
        polish.assert_not_called()
        with mock.patch.object(cli, "transcribe_path", return_value="importé"), \
                redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(["transcribe", str(self.audio)]), 0)
        self.assertTrue(self.audio.exists())


if __name__ == "__main__":
    unittest.main()
