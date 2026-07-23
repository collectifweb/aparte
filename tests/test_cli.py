import argparse
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


if __name__ == "__main__":
    unittest.main()
