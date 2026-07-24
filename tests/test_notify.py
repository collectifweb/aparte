import unittest
from unittest import mock

from aparte import notify as notify_module
from aparte.notify import _applescript_escape, _preview, notify


class NotifyTest(unittest.TestCase):
    def test_returns_false_and_stays_silent_when_notify_send_missing(self):
        with mock.patch.object(notify_module.shutil, "which", return_value=None):
            with mock.patch.object(notify_module.subprocess, "run") as run:
                self.assertFalse(notify("hi", "there"))
                run.assert_not_called()

    def test_invokes_notify_send_when_available(self):
        with mock.patch.object(notify_module.shutil, "which", return_value="/usr/bin/notify-send"):
            with mock.patch.object(notify_module.subprocess, "run") as run:
                self.assertTrue(notify("Title", "Body", urgency="low"))
                run.assert_called_once()
                command = run.call_args.args[0]
                self.assertEqual(command[0], "/usr/bin/notify-send")
                self.assertIn("Title", command)
                self.assertIn("Body", command)
                self.assertIn("low", command)

    def test_never_raises_when_subprocess_fails(self):
        with mock.patch.object(notify_module.shutil, "which", return_value="/usr/bin/notify-send"):
            with mock.patch.object(notify_module.subprocess, "run", side_effect=OSError("boom")):
                self.assertFalse(notify("x"))

    def test_preview_collapses_whitespace_and_truncates(self):
        self.assertEqual(_preview("hello   world\n\nfoo"), "hello world foo")
        long = "word " * 40
        preview = _preview(long, limit=20)
        self.assertLessEqual(len(preview), 20)
        self.assertTrue(preview.endswith("…"))


class NotifyMacTest(unittest.TestCase):
    """macOS has no notify-send: notifications go through ``osascript``."""

    def test_invokes_osascript_with_display_notification(self):
        with mock.patch.object(notify_module, "is_macos", return_value=True):
            with mock.patch.object(notify_module.shutil, "which", return_value="/usr/bin/osascript"):
                with mock.patch.object(notify_module.subprocess, "run") as run:
                    self.assertTrue(notify("Titre", "Corps"))
        command = run.call_args.args[0]
        self.assertEqual(command[0], "/usr/bin/osascript")
        self.assertEqual(command[1], "-e")
        self.assertIn("display notification", command[2])
        self.assertIn('"Corps"', command[2])
        self.assertIn('with title "Titre"', command[2])

    def test_returns_false_when_osascript_missing(self):
        with mock.patch.object(notify_module, "is_macos", return_value=True):
            with mock.patch.object(notify_module.shutil, "which", return_value=None):
                with mock.patch.object(notify_module.subprocess, "run") as run:
                    self.assertFalse(notify("x"))
                    run.assert_not_called()

    def test_never_raises_on_mac_when_subprocess_fails(self):
        with mock.patch.object(notify_module, "is_macos", return_value=True):
            with mock.patch.object(notify_module.shutil, "which", return_value="/usr/bin/osascript"):
                with mock.patch.object(notify_module.subprocess, "run", side_effect=OSError("boom")):
                    self.assertFalse(notify("x"))

    def test_a_quote_in_the_text_cannot_break_the_applescript(self):
        # A dictation preview ending in a quote must not close the literal early.
        self.assertEqual(_applescript_escape('il a dit "oui"'), 'il a dit \\"oui\\"')
        self.assertEqual(_applescript_escape("c:\\\\chemin"), "c:\\\\\\\\chemin")
        # A raw newline would break the -e script syntax; it becomes an escape.
        self.assertEqual(_applescript_escape("ligne1\nligne2"), "ligne1\\nligne2")

    def test_notify_never_raises_even_if_the_argument_is_not_a_string(self):
        # The "never raises" guarantee must hold by construction, not by luck of
        # the current callers all happening to pass strings.
        with mock.patch.object(notify_module, "is_macos", return_value=True):
            with mock.patch.object(notify_module.shutil, "which", return_value="/usr/bin/osascript"):
                self.assertFalse(notify(object()))  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
