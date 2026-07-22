import unittest
from unittest import mock

from aparte import notify as notify_module
from aparte.notify import _preview, notify


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


if __name__ == "__main__":
    unittest.main()
