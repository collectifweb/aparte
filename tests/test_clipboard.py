import unittest
from unittest import mock

from murmur import clipboard as clipboard_module
from murmur.clipboard import ClipboardError, paste_text


def _which(available):
    return lambda name: f"/usr/bin/{name}" if name in available else None


def _getenv(env):
    return lambda name, default=None: env.get(name, default)


class PasteTextTest(unittest.TestCase):
    def test_x11_copies_first_then_pastes_with_ctrl_v(self):
        with mock.patch.object(clipboard_module.shutil, "which", side_effect=_which({"xclip", "xdotool"})):
            with mock.patch.object(clipboard_module.os, "getenv", side_effect=_getenv({"DISPLAY": ":0"})):
                with mock.patch.object(clipboard_module.subprocess, "run") as run:
                    tool = paste_text("bonjour le monde")

        self.assertEqual(tool, "xdotool")
        commands = [call.args[0] for call in run.call_args_list]
        # The dictation is copied to the clipboard first, as a safety net.
        self.assertEqual(commands[0][0], "xclip")
        # Then it is pasted in one atomic Ctrl+V — never typed out character by
        # character, so a stray click or key press can't scatter it.
        self.assertEqual(commands[-1], ["xdotool", "key", "--clearmodifiers", "ctrl+v"])
        self.assertNotIn("type", commands[-1])
        self.assertNotIn("bonjour le monde", commands[-1])

    def test_wayland_copies_first_then_pastes_with_ctrl_v(self):
        with mock.patch.object(clipboard_module.shutil, "which", side_effect=_which({"wl-copy", "wtype"})):
            with mock.patch.object(clipboard_module.os, "getenv", side_effect=_getenv({"WAYLAND_DISPLAY": "wayland-0"})):
                with mock.patch.object(clipboard_module.subprocess, "run") as run:
                    tool = paste_text("salut")

        self.assertEqual(tool, "wtype")
        commands = [call.args[0] for call in run.call_args_list]
        self.assertEqual(commands[0][0], "wl-copy")
        self.assertEqual(commands[-1], ["wtype", "-M", "ctrl", "-k", "v", "-m", "ctrl"])
        self.assertNotIn("salut", commands[-1])

    def test_without_paste_tool_still_copies_then_raises(self):
        # A clipboard tool is present but no paste tool: the text must still reach
        # the clipboard before we give up, so it is recoverable with Ctrl+V.
        with mock.patch.object(clipboard_module.shutil, "which", side_effect=_which({"xclip"})):
            with mock.patch.object(clipboard_module.os, "getenv", side_effect=_getenv({"DISPLAY": ":0"})):
                with mock.patch.object(clipboard_module.subprocess, "run") as run:
                    with self.assertRaises(ClipboardError):
                        paste_text("ne pas perdre")
        commands = [call.args[0] for call in run.call_args_list]
        self.assertEqual(commands[0][0], "xclip")


if __name__ == "__main__":
    unittest.main()
