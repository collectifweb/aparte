import argparse
import contextlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aparte import cli
from aparte.cli import build_parser
from aparte.config import Settings


def _toggle_args(target: str = "paste") -> argparse.Namespace:
    return argparse.Namespace(
        status=False,
        target=target,
        no_polish=False,
        keep_audio=True,
        style=None,
        cleanup_level=None,
        sample_rate=16000,
    )


class StopDictationTest(unittest.TestCase):
    """Ce que le raccourci fait du texte, une fois la transcription finie."""

    def setUp(self):
        transition = mock.patch.object(cli, "toggle_session_transition", side_effect=contextlib.nullcontext)
        transition.start()
        self.addCleanup(transition.stop)

    def _run(self, transcript: str, target: str = "paste", paste_raises: Exception | None = None):
        recording = mock.Mock(audio_path=Path("/tmp/aparte-test.wav"))
        manager = mock.Mock()
        with mock.patch.object(cli, "get_active_session", return_value=recording):
            with mock.patch.object(cli, "stop_toggle_recording", return_value=recording):
                with mock.patch.object(cli, "transcribe_path", return_value=transcript):
                    with mock.patch.object(cli, "paste_text", side_effect=paste_raises) as paste:
                        with mock.patch.object(cli, "copy_text") as copy:
                            with mock.patch.object(cli, "notify") as notify:
                                with mock.patch.object(cli.history, "record") as record:
                                    manager.attach_mock(paste, "paste")
                                    manager.attach_mock(copy, "copy")
                                    manager.attach_mock(notify, "notify")
                                    manager.attach_mock(record, "record")
                                    error = None
                                    try:
                                        cli.toggle_dictation(_toggle_args(target), Settings())
                                    except Exception as exc:  # noqa: BLE001 - rendu à l'appelant
                                        error = exc
        return manager, error

    def test_nothing_heard_leaves_the_clipboard_alone(self):
        """`paste_text` copie avant de coller : une dictée vide effaçait ce que
        l'utilisateur gardait en réserve."""
        manager, error = self._run("   \n  ")
        self.assertIsNone(error)
        manager.paste.assert_not_called()
        manager.copy.assert_not_called()
        manager.record.assert_not_called()
        self.assertIn("Rien à transcrire", manager.notify.call_args.args[0])

    def test_the_text_is_inserted_before_success_is_announced(self):
        manager, error = self._run("Bonjour")
        self.assertIsNone(error)
        called = [name for name, *_ in manager.mock_calls]
        # L'historique d'abord — filet si le collage casse —, puis le collage,
        # et seulement ensuite la notification de succès.
        self.assertEqual(called, ["notify", "record", "paste", "notify"])
        manager.paste.assert_called_once_with("Bonjour", "clipboard")

    def test_copy_target_never_types_into_the_window(self):
        manager, error = self._run("Bonjour", target="copy")
        self.assertIsNone(error)
        manager.copy.assert_called_once_with("Bonjour")
        manager.paste.assert_not_called()

    def test_a_failed_insertion_is_announced_and_not_swallowed(self):
        """L'erreur part sur stderr, qu'un raccourci clavier n'a personne pour
        lire. Sans cette notification, l'échec est parfaitement muet."""
        manager, error = self._run("Bonjour", paste_raises=RuntimeError("xdotool absent"))
        self.assertIsInstance(error, RuntimeError)
        manager.record.assert_called_once_with("Bonjour", False)
        failure = manager.notify.call_args
        self.assertIn("non insérée", failure.args[0])
        self.assertIn("aparte last", failure.args[1])
        self.assertEqual(failure.kwargs["urgency"], "critical")


class StartDictationTest(unittest.TestCase):
    """Ce que le raccourci annonce quand il ouvre le micro — et quand il échoue."""

    def setUp(self):
        transition = mock.patch.object(cli, "toggle_session_transition", side_effect=contextlib.nullcontext)
        transition.start()
        self.addCleanup(transition.stop)

    def _run(self, start_raises: Exception | None = None):
        recording = mock.Mock(audio_path=Path("/tmp/aparte-test.wav"))
        with mock.patch.object(cli, "get_active_session", return_value=None):
            with mock.patch.object(
                cli,
                "start_toggle_recording",
                side_effect=start_raises,
                return_value=recording,
            ):
                with mock.patch.object(cli, "notify") as notify:
                    error = None
                    try:
                        cli.toggle_dictation(_toggle_args(), Settings())
                    except Exception as exc:  # noqa: BLE001 - rendu à l'appelant
                        error = exc
        return notify, error

    def test_a_started_recording_is_announced(self):
        notify, error = self._run()
        self.assertIsNone(error)
        self.assertIn("Dictée en cours", notify.call_args.args[0])

    def test_a_microphone_that_stays_shut_is_announced_too(self):
        """Sans cette notification, un démarrage refusé est un appui muet : on
        parle dans le vide, puis l'appui censé arrêter ouvre le micro pour de
        bon."""
        notify, error = self._run(cli.RecordingError("Could not start recording."))
        self.assertIsInstance(error, cli.RecordingError)
        self.assertIn("non démarrée", notify.call_args.args[0])
        self.assertEqual(notify.call_args.kwargs["urgency"], "critical")
        self.assertNotIn("Dictée en cours", str(notify.call_args_list))


class CliParserTest(unittest.TestCase):
    def test_dictate_defaults_to_paste_and_polish(self):
        args = build_parser().parse_args(["dictate"])
        self.assertEqual(args.command, "dictate")
        self.assertEqual(args.target, "paste")
        self.assertFalse(args.no_polish)
        self.assertIsNone(args.style)

    def test_dictate_can_copy_without_polish(self):
        args = build_parser().parse_args(["dictate", "--target", "copy", "--no-polish"])
        self.assertEqual(args.target, "copy")
        self.assertTrue(args.no_polish)

    def test_toggle_defaults_to_paste_and_polish(self):
        args = build_parser().parse_args(["toggle"])
        self.assertEqual(args.command, "toggle")
        self.assertEqual(args.target, "paste")
        self.assertFalse(args.no_polish)

    def test_toggle_status_flag(self):
        args = build_parser().parse_args(["toggle", "--status"])
        self.assertTrue(args.status)

    def test_install_desktop_parser(self):
        args = build_parser().parse_args(["install-desktop", "--print"])
        self.assertEqual(args.command, "install-desktop")
        self.assertTrue(args.print)

    def test_install_hotkey_defaults(self):
        args = build_parser().parse_args(["install-hotkey"])
        self.assertEqual(args.command, "install-hotkey")
        self.assertIsNone(args.key)  # resolved to Super+Space or the existing binding at run time
        self.assertEqual(args.target, "paste")
        self.assertFalse(args.remove)

    def test_install_hotkey_custom_key_and_remove(self):
        args = build_parser().parse_args(["install-hotkey", "--key", "<Control><Alt>d", "--remove"])
        self.assertEqual(args.key, "<Control><Alt>d")
        self.assertTrue(args.remove)


class FailedDictationRecoveryTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.source = self.base / "synthetic.wav"
        self.source.write_bytes(b"synthetic capture")
        env = mock.patch.dict(os.environ, {"APARTE_RUNTIME_DIR": str(self.base)})
        env.start()
        self.addCleanup(env.stop)
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.notify = self.stack.enter_context(mock.patch.object(cli, "notify"))
        self.history = self.stack.enter_context(mock.patch.object(cli.history, "record"))
        self.copy = self.stack.enter_context(mock.patch.object(cli, "copy_text"))
        self.paste = self.stack.enter_context(mock.patch.object(cli, "paste_text"))
        self.stack.enter_context(mock.patch.object(cli, "record_wav", return_value=self.source))
        self.stack.enter_context(mock.patch.object(cli, "toggle_session_transition", side_effect=contextlib.nullcontext))
        recording = mock.Mock(audio_path=self.source)
        self.stack.enter_context(mock.patch.object(cli, "get_active_session", return_value=recording))
        self.stack.enter_context(mock.patch.object(cli, "stop_toggle_recording", return_value=recording))

    def test_both_dictation_paths_retain_processing_failures(self):
        for command, handler in (("dictate", cli.dictate_once), ("toggle", cli.toggle_dictation)):
            with self.subTest(command=command):
                self.source.write_bytes(b"synthetic capture")
                args = build_parser().parse_args([command])
                with mock.patch.object(cli, "transcribe_path", side_effect=RuntimeError("backend unavailable")):
                    with self.assertRaisesRegex(RuntimeError, "backend unavailable"):
                        handler(args, Settings())
                entry = cli.recovery.entries()[0]
                with cli.recovery.claim(entry["id"]) as item:
                    self.assertEqual(item.audio_path.read_bytes(), b"synthetic capture")
                self.assertFalse(self.source.exists())
                self.assertIn("une heure", self.notify.call_args.args[1])
                cli.recovery.discard(entry["id"])
        self.copy.assert_not_called()
        self.paste.assert_not_called()
        self.history.assert_not_called()

    def test_polish_failure_preserves_real_transcription_and_raw_retry(self):
        with mock.patch.object(cli, "transcribe_via_running_app", return_value="texte brut"):
            with mock.patch.object(cli, "polish_text", side_effect=RuntimeError("polish unavailable")):
                with self.assertRaisesRegex(RuntimeError, "polish unavailable"):
                    cli.dictate_once(build_parser().parse_args(["dictate"]), Settings())
        entry = cli.recovery.entries()[0]
        self.assertTrue(entry["has_text"])
        args = build_parser().parse_args(["recover", "retry", entry["id"], "--no-polish"])
        with mock.patch.object(cli, "transcribe_path") as transcribe:
            self.assertEqual(cli.retry_recovery(entry["id"], args, Settings()), "texte brut")
        transcribe.assert_not_called()
        self.copy.assert_called_once_with("texte brut")
        self.paste.assert_not_called()
        self.assertEqual(cli.recovery.entries(), [])
        with self.assertRaises(cli.recovery.RecoveryNotFound):
            cli.retry_recovery(entry["id"], args, Settings())
        self.copy.assert_called_once()

    def test_failed_recovery_keeps_new_raw_text_without_renewing_expiry(self):
        identifier = cli.recovery.save_failure(self.source)
        expiry = cli.recovery.entries()[0]["expires_at"]
        args = build_parser().parse_args(["recover", "retry", identifier])
        with mock.patch.object(cli, "transcribe_path", return_value="transcrit une fois"):
            with mock.patch.object(cli, "polish_text", side_effect=RuntimeError("offline")):
                with self.assertRaises(RuntimeError):
                    cli.retry_recovery(identifier, args, Settings())
        entry = cli.recovery.entries()[0]
        self.assertTrue(entry["has_text"])
        self.assertEqual(entry["expires_at"], expiry)
        self.assertEqual(entry["id"], identifier)

    def test_silent_recovery_skips_polisher_and_clipboard(self):
        identifier = cli.recovery.save_failure(self.source, raw_text="  \n")
        args = build_parser().parse_args(["recover", "retry", identifier])
        with mock.patch.object(cli, "polish_text", side_effect=RuntimeError("unavailable")) as polish:
            self.assertEqual(cli.retry_recovery(identifier, args, Settings()), "  \n")
        polish.assert_not_called()
        self.copy.assert_not_called()
        self.paste.assert_not_called()
        self.history.assert_not_called()
        self.assertEqual(cli.recovery.entries(), [])

    def test_save_failure_keeps_original_audio(self):
        args = build_parser().parse_args(["dictate"])
        with mock.patch.object(cli, "transcribe_path", side_effect=RuntimeError("backend")):
            with mock.patch.object(cli.recovery, "save_failure", side_effect=OSError("disk full")):
                with self.assertRaisesRegex(RuntimeError, "backend"):
                    cli.dictate_once(args, Settings())
        self.assertTrue(self.source.exists())
        self.assertIn("audio original", self.notify.call_args.args[1])

    def test_success_and_silence_leave_no_recovery(self):
        for output in ("bonjour", "   "):
            with self.subTest(output=output):
                self.source.write_bytes(b"synthetic capture")
                args = build_parser().parse_args(["dictate"])
                with mock.patch.object(cli, "transcribe_path", return_value=output):
                    self.assertEqual(cli.dictate_once(args, Settings()), output)
                self.assertFalse(self.source.exists())
                self.assertEqual(cli.recovery.entries(), [])

    def test_failed_stop_is_visible_without_claiming_microphone_closed(self):
        args = build_parser().parse_args(["toggle"])
        with mock.patch.object(cli, "stop_toggle_recording", side_effect=cli.ToggleSessionError("micro toujours actif")):
            with mock.patch.object(cli, "transcribe_path") as transcribe:
                with self.assertRaises(cli.ToggleSessionError):
                    cli.toggle_dictation(args, Settings())
        self.assertIn("non confirmé", self.notify.call_args.args[0])
        self.assertEqual(self.notify.call_args.kwargs["urgency"], "critical")
        self.assertTrue(self.source.exists())
        transcribe.assert_not_called()

    def test_capture_transition_is_released_before_transcription(self):
        in_transition = False

        @contextlib.contextmanager
        def transition():
            nonlocal in_transition
            in_transition = True
            try:
                yield
            finally:
                in_transition = False

        def transcribe(*args):
            self.assertFalse(in_transition)
            return "texte"

        with mock.patch.object(cli, "toggle_session_transition", side_effect=transition):
            with mock.patch.object(cli, "transcribe_path", side_effect=transcribe):
                cli.toggle_dictation(build_parser().parse_args(["toggle"]), Settings())


if __name__ == "__main__":
    unittest.main()
