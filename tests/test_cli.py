import argparse
import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from aparte import cli, linux_desktop, platform_dispatch
from aparte.cli import build_parser
from aparte.config import Settings, load_config, update_config, write_default_config


def _run_cli(*argv: str):
    """Run ``cli.main`` capturing exit code, stdout and stderr."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(list(argv))
    return code, out.getvalue(), err.getvalue()


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
        # These are delivery-order tests. Actual audio retention is exercised
        # with private synthetic files in test_cli_recovery.
        polish = mock.patch.object(cli, "polish_text", side_effect=lambda text, *_: text)
        recovery = mock.patch.object(cli.recovery, "save_failure", return_value="0" * 32)
        polish.start()
        recovery.start()
        self.addCleanup(polish.stop)
        self.addCleanup(recovery.stop)
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
        failure = next(call for call in manager.notify.call_args_list
                       if "non insérée" in call.args[0])
        self.assertIn("non insérée", failure.args[0])
        self.assertIn("aparte last", failure.args[1])
        self.assertEqual(failure.kwargs["urgency"], "critical")


class DeliverTranscriptTest(unittest.TestCase):
    """The single home of the empty→nothing / history-before-insert order, shared
    by dictate_once, toggle_dictation and the macOS RecordingController worker."""

    def test_an_empty_transcript_touches_nothing(self):
        with mock.patch.object(cli, "_deliver") as deliver:
            with mock.patch.object(cli.history, "record") as record:
                with mock.patch.object(cli, "_notify_nothing_heard") as nothing:
                    self.assertIs(cli.deliver_transcript("  \n ", "paste", Settings()), False)
        nothing.assert_called_once()
        deliver.assert_not_called()
        record.assert_not_called()

    def test_a_real_transcript_records_before_it_inserts(self):
        settings = Settings()
        manager = mock.Mock()
        with mock.patch.object(cli, "_deliver") as deliver:
            with mock.patch.object(cli.history, "record") as record:
                manager.attach_mock(record, "record")
                manager.attach_mock(deliver, "deliver")
                self.assertIs(cli.deliver_transcript("Bonjour", "paste", settings), True)
        self.assertEqual([name for name, *_ in manager.mock_calls], ["record", "deliver"])
        record.assert_called_once_with("Bonjour", settings.history_persist)
        deliver.assert_called_once_with("Bonjour", "paste", settings)


class PolishForDeliveryTest(unittest.TestCase):
    """The resident shortcut has no per-call flags: it polishes with the config
    defaults, the same chain transcribe_path applies on the CLI side."""

    def test_it_polishes_with_the_settings_defaults(self):
        settings = Settings()
        with mock.patch.object(cli, "polish_text", return_value="poli") as polish:
            out = cli.polish_for_delivery("brut", settings)
        self.assertEqual(out, "poli")
        args = polish.call_args.args[1]
        self.assertTrue(args.polish)
        self.assertEqual(args.style, settings.default_style)
        self.assertEqual(args.cleanup_level, settings.cleanup_level)

    def test_an_empty_transcript_is_returned_untouched_without_polishing(self):
        with mock.patch.object(cli, "polish_text") as polish:
            self.assertEqual(cli.polish_for_delivery("   ", Settings()), "   ")
        polish.assert_not_called()


class MacToggleTest(unittest.TestCase):
    """On macOS the toggle has no detached recorder to drive: recording lives in
    the resident server (M4/M5). The CLI says so plainly instead of crashing on the
    Linux-only arecord path. The dev host is Linux, so the platform is mocked."""

    def test_it_refuses_clearly_without_touching_the_linux_recorder(self):
        with mock.patch.object(cli, "is_macos", return_value=True):
            with mock.patch.object(cli, "get_active_session", return_value=None):
                with mock.patch.object(cli, "start_toggle_recording") as start:
                    with mock.patch.object(cli, "notify") as notify:
                        message = cli.toggle_dictation(_toggle_args(), Settings())
        start.assert_not_called()
        self.assertIn("macOS", message)
        self.assertIn("dictate", message)
        self.assertIn("Bascule indisponible", notify.call_args.args[0])


class MacInstallHotkeyTest(unittest.TestCase):
    """On macOS install-hotkey persists the combo to config.json — no gsettings.
    'Installing' only records the choice; the resident server registers it at
    startup, so a reserved combo surfaces at runtime (doctor), not here. The dev
    host is Linux, so the platform is mocked."""

    def _args(self, **over):
        base = dict(
            command="install-hotkey", key=None, target="paste",
            name="Aparté dictation", print=False, remove=False, diagnostic=False,
        )
        base.update(over)
        return SimpleNamespace(**base)

    def _run(self, args, path):
        env = {
            "APARTE_CONFIG": str(path), "MURMUR_CONFIG": "",
            "APARTE_HOTKEY": "", "MURMUR_HOTKEY": "",
        }
        with mock.patch.object(cli, "is_macos", return_value=True):
            with mock.patch.dict(os.environ, env):
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    cli.handle_install_hotkey(args)
        return out.getvalue()

    def _fresh_config(self, directory):
        path = Path(directory) / "config.json"
        write_default_config(path)
        return path

    def test_the_default_persists_the_default_combo(self):
        with tempfile.TemporaryDirectory() as d:
            path = self._fresh_config(d)
            self._run(self._args(), path)
            self.assertEqual(load_config(path)["hotkey"], "ctrl+opt+d")

    def test_a_custom_combo_is_normalized_and_persisted(self):
        with tempfile.TemporaryDirectory() as d:
            path = self._fresh_config(d)
            self._run(self._args(key="alt+Ctrl+D"), path)
            self.assertEqual(load_config(path)["hotkey"], "ctrl+opt+d")

    def test_remove_clears_the_combo(self):
        with tempfile.TemporaryDirectory() as d:
            path = self._fresh_config(d)
            update_config({"hotkey": "ctrl+opt+d"}, path)
            self._run(self._args(remove=True), path)
            self.assertEqual(load_config(path)["hotkey"], "")

    def test_a_copy_target_is_refused_without_writing(self):
        with tempfile.TemporaryDirectory() as d:
            path = self._fresh_config(d)
            out = self._run(self._args(target="copy"), path)
            self.assertIn("paste", out)
            self.assertEqual(load_config(path)["hotkey"], "")   # untouched

    def test_an_invalid_combo_is_refused_without_writing(self):
        with tempfile.TemporaryDirectory() as d:
            path = self._fresh_config(d)
            out = self._run(self._args(key="ctrl+opt+zz"), path)
            self.assertIn("Invalid", out)
            self.assertEqual(load_config(path)["hotkey"], "")

    def test_print_shows_the_combo_and_never_writes(self):
        with tempfile.TemporaryDirectory() as d:
            path = self._fresh_config(d)
            out = self._run(self._args(print=True), path)
            self.assertIn("⌃⌥D", out)                           # the default combo, pretty
            self.assertEqual(load_config(path)["hotkey"], "")   # print never persists

    def test_the_diagnostic_dispatches_to_the_live_runner(self):
        # --diagnostic registers the combo live (M8); with no configured combo it
        # falls back to the default. The native runner is mocked (Linux dev host).
        with tempfile.TemporaryDirectory() as d:
            path = self._fresh_config(d)
            with mock.patch("aparte.macos_runloop.run_hotkey_diagnostic") as run:
                self._run(self._args(diagnostic=True), path)
            run.assert_called_once_with("ctrl+opt+d")

    def test_the_diagnostic_is_macos_only_on_linux(self):
        with mock.patch.object(cli, "is_macos", return_value=False):
            with mock.patch("aparte.macos_runloop.run_hotkey_diagnostic") as run:
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    cli.handle_install_hotkey(self._args(diagnostic=True))
        self.assertIn("macOS-only", out.getvalue())
        run.assert_not_called()


class StartDictationTest(unittest.TestCase):
    """Ce que le raccourci annonce quand il ouvre le micro — et quand il échoue."""

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


class DesktopIntegrationCliTest(unittest.TestCase):
    """M0 routes install-desktop/-autostart through the platform seam. On Linux
    the observable behaviour must stay identical, and a non-Linux OS must fail
    cleanly — proven at the ``cli.main`` boundary, not just at module level."""

    def test_install_desktop_print_matches_linux_backend(self):
        code, out, err = _run_cli("install-desktop", "--print")
        self.assertEqual(code, 0)
        self.assertEqual(out, linux_desktop.build_desktop_entry())
        self.assertEqual(err, "")

    def test_install_autostart_print_matches_linux_backend(self):
        code, out, err = _run_cli("install-autostart", "--print")
        self.assertEqual(code, 0)
        self.assertEqual(out, linux_desktop.build_autostart_entry())
        self.assertEqual(err, "")

    def test_install_autostart_remove_when_absent(self):
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": directory}):
                code, out, err = _run_cli("install-autostart", "--remove")
        self.assertEqual(code, 0)
        self.assertEqual(out, "no autostart entry to remove\n")
        self.assertEqual(err, "")

    def test_install_desktop_writes_the_same_file_as_before(self):
        with tempfile.TemporaryDirectory() as directory:
            # XDG_CONFIG_HOME too, not just XDG_DATA_HOME: install_desktop_entry
            # calls remove_legacy_entries(), which reaches into ~/.config/autostart
            # and would delete a real legacy murmur.desktop otherwise.
            with mock.patch.dict(os.environ, {"XDG_DATA_HOME": directory, "XDG_CONFIG_HOME": directory}):
                code, out, err = _run_cli("install-desktop")
                expected = Path(directory) / "applications" / "aparte.desktop"
                self.assertEqual(code, 0)
                self.assertEqual(out.strip(), str(expected))
                self.assertEqual(err, "")
                self.assertEqual(expected.read_text(encoding="utf-8"), linux_desktop.build_desktop_entry())

    def test_unsupported_os_fails_cleanly_without_traceback(self):
        with mock.patch.object(platform_dispatch.sys, "platform", "darwin"):
            code, out, err = _run_cli("install-desktop", "--print")
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn("error: Desktop integration", err)
        self.assertNotIn("Traceback", err)


if __name__ == "__main__":
    unittest.main()
