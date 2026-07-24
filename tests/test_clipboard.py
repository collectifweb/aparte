import contextlib
import unittest
from unittest import mock

from aparte import clipboard as clipboard_module
from aparte.clipboard import ClipboardError, copy_text, paste_text


def _which(available):
    return lambda name: f"/usr/bin/{name}" if name in available else None


def _getenv(env):
    return lambda name, default=None: env.get(name, default)


def run_paste(text, mode, available, env):
    with mock.patch.object(clipboard_module.shutil, "which", side_effect=_which(available)):
        with mock.patch.object(clipboard_module.os, "getenv", side_effect=_getenv(env)):
            with mock.patch.object(clipboard_module.subprocess, "run") as run:
                tool = paste_text(text, mode)
    return tool, [call.args[0] for call in run.call_args_list]


X11 = ({"xclip", "xdotool"}, {"DISPLAY": ":0"})
WAYLAND = ({"wl-copy", "wtype"}, {"WAYLAND_DISPLAY": "wayland-0"})


class PasteModeTest(unittest.TestCase):
    """Ctrl+V does nothing in a terminal, and some apps refuse a paste entirely."""

    def test_terminal_mode_sends_ctrl_shift_v(self):
        _, commands = run_paste("ls -la", "terminal", *X11)
        self.assertEqual(commands[-1], ["xdotool", "key", "--clearmodifiers", "ctrl+shift+v"])

        _, commands = run_paste("ls -la", "terminal", *WAYLAND)
        self.assertEqual(
            commands[-1],
            ["wtype", "-M", "ctrl", "-M", "shift", "-k", "v", "-m", "shift", "-m", "ctrl"],
        )

    def test_direct_mode_types_the_text_out(self):
        _, commands = run_paste("bonjour", "direct", *X11)
        self.assertEqual(commands[-1], ["xdotool", "type", "--clearmodifiers", "--", "bonjour"])

        _, commands = run_paste("bonjour", "direct", *WAYLAND)
        self.assertEqual(commands[-1], ["wtype", "bonjour"])

    def test_every_mode_copies_to_the_clipboard_first(self):
        for mode in clipboard_module.PASTE_MODES:
            _, commands = run_paste("filet de sécurité", mode, *X11)
            self.assertEqual(commands[0][0], "xclip", mode)

    def test_an_unknown_mode_falls_back_to_a_plain_paste(self):
        _, commands = run_paste("bonjour", "n'importe quoi", *X11)
        self.assertEqual(commands[-1], ["xdotool", "key", "--clearmodifiers", "ctrl+v"])


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


class CopyMacTest(unittest.TestCase):
    """On macOS the clipboard is pbcopy, not the Linux wl-copy/xclip/xsel trio."""

    def test_copy_text_uses_pbcopy(self):
        with mock.patch.object(clipboard_module, "is_macos", return_value=True):
            with mock.patch.object(clipboard_module.subprocess, "run") as run:
                tool = copy_text("bonjour")
        self.assertEqual(tool, "pbcopy")
        self.assertEqual(run.call_args.args[0], ["pbcopy"])
        self.assertEqual(run.call_args.kwargs["input"], "bonjour")


class PasteMacTest(unittest.TestCase):
    """On macOS, paste_text copies with pbcopy then synthesises Cmd+V — gated on
    Accessibility trust, because CGEvent posts are ignored without it and macOS
    returns no error, so a missing permission would otherwise look like success."""

    def _paste(self, mode="clipboard", trusted=True):
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(clipboard_module, "is_macos", return_value=True))
            run = stack.enter_context(mock.patch.object(clipboard_module.subprocess, "run"))  # pbcopy
            stack.enter_context(
                mock.patch("aparte.macos_permissions.accessibility_trusted", return_value=trusted)
            )
            guide = stack.enter_context(mock.patch("aparte.macos_permissions.guide_accessibility_once"))
            paste = stack.enter_context(
                mock.patch("aparte.macos_insert.insert_via_paste", return_value="cgevent-paste")
            )
            typed = stack.enter_context(
                mock.patch("aparte.macos_insert.type_unicode", return_value="cgevent-type")
            )
            result, error = None, None
            try:
                result = paste_text("bonjour", mode)
            except ClipboardError as exc:
                error = exc
        return {"result": result, "error": error, "run": run, "guide": guide, "paste": paste, "type": typed}

    def test_trusted_copies_first_then_pastes_with_cmd_v(self):
        out = self._paste(mode="clipboard", trusted=True)
        self.assertIsNone(out["error"])
        self.assertEqual(out["result"], "cgevent-paste")
        self.assertEqual(out["run"].call_args_list[0].args[0], ["pbcopy"])  # copy is first
        out["paste"].assert_called_once()
        out["type"].assert_not_called()
        out["guide"].assert_not_called()

    def test_direct_mode_types_the_text_out(self):
        out = self._paste(mode="direct", trusted=True)
        self.assertIsNone(out["error"])
        self.assertEqual(out["result"], "cgevent-type")
        out["type"].assert_called_once()
        out["paste"].assert_not_called()

    def test_terminal_mode_falls_back_to_cmd_v(self):
        # No terminal-paste on macOS: terminal collapses to Cmd+V, not typing.
        out = self._paste(mode="terminal", trusted=True)
        self.assertEqual(out["result"], "cgevent-paste")
        out["paste"].assert_called_once()
        out["type"].assert_not_called()

    def test_denied_accessibility_copies_guides_and_raises(self):
        out = self._paste(trusted=False)
        self.assertIsInstance(out["error"], ClipboardError)
        # Copied first — recoverable from the clipboard even though the paste failed.
        self.assertEqual(out["run"].call_args_list[0].args[0], ["pbcopy"])
        out["guide"].assert_called_once()  # walked through granting the permission
        out["paste"].assert_not_called()  # never posted a keystroke that would be dropped

    def test_unreachable_accessibility_raises_without_guiding(self):
        out = self._paste(trusted=None)
        self.assertIsInstance(out["error"], ClipboardError)
        self.assertEqual(out["run"].call_args_list[0].args[0], ["pbcopy"])
        out["guide"].assert_not_called()  # opening Settings off a Mac would be noise
        out["paste"].assert_not_called()


if __name__ == "__main__":
    unittest.main()
