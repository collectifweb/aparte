import os
import unittest
from unittest import mock

from murmur import hotkey


class DesktopDetectionTest(unittest.TestCase):
    def test_detects_cinnamon(self):
        with mock.patch.dict(os.environ, {"XDG_CURRENT_DESKTOP": "X-Cinnamon"}, clear=False):
            self.assertEqual(hotkey.detect_desktop(), "cinnamon")

    def test_detects_gnome_from_session(self):
        with mock.patch.dict(os.environ, {"XDG_CURRENT_DESKTOP": "", "DESKTOP_SESSION": "gnome"}, clear=False):
            self.assertEqual(hotkey.detect_desktop(), "gnome")

    def test_unknown_desktop_is_empty(self):
        with mock.patch.dict(os.environ, {"XDG_CURRENT_DESKTOP": "sway", "DESKTOP_SESSION": ""}, clear=False):
            self.assertEqual(hotkey.detect_desktop(), "")


class HelpersTest(unittest.TestCase):
    def test_key_label_humanizes_accelerator(self):
        self.assertEqual(hotkey.key_label("<Super>space"), "Super+Space")
        self.assertEqual(hotkey.key_label("<Control><Alt>d"), "Ctrl+Alt+D")

    def test_parse_string_list_drops_dummy(self):
        self.assertEqual(hotkey._parse_string_list("['custom0', 'custom1']"), ["custom0", "custom1"])
        self.assertEqual(hotkey._parse_string_list("['__dummy__']"), [])
        self.assertEqual(hotkey._parse_string_list("@as []"), [])

    def test_next_free_slot_skips_used(self):
        self.assertEqual(hotkey._next_free_slot(["custom0", "custom1", "custom3"]), "custom2")
        self.assertEqual(hotkey._next_free_slot(["custom0", "custom1", "custom2"]), "custom3")
        self.assertEqual(hotkey._next_free_slot([]), "custom0")

    def test_toggle_command_is_absolute(self):
        with mock.patch("murmur.hotkey.shutil.which", return_value="/venv/bin/murmur"):
            self.assertEqual(hotkey.toggle_command("paste"), "/venv/bin/murmur toggle --target paste")

    def test_manual_instructions_mention_command_and_key(self):
        text = hotkey.manual_instructions("/venv/bin/murmur toggle --target paste", "<Super>space", "cinnamon")
        self.assertIn("/venv/bin/murmur toggle --target paste", text)
        self.assertIn("Super+Space", text)
        self.assertIn("System Settings", text)


class InstallHotkeyTest(unittest.TestCase):
    def _patch_gsettings(self, custom_list):
        """Fake _gsettings: GET returns custom_list / empty values; SET is recorded."""
        self.calls = []

        def fake(*args):
            self.calls.append(args)
            if args[0] == "get" and args[-1] == hotkey.PROVIDERS["cinnamon"].list_key:
                return custom_list
            if args[0] == "get":
                return "''"  # empty name/command for existing slots
            return ""

        return mock.patch("murmur.hotkey._gsettings", side_effect=fake)

    def test_install_allocates_next_slot_on_cinnamon(self):
        with mock.patch("murmur.hotkey.detect_desktop", return_value="cinnamon"), mock.patch(
            "murmur.hotkey.shutil.which", return_value="/venv/bin/murmur"
        ), self._patch_gsettings("['custom0', 'custom1', 'custom2', 'custom3']"):
            result = hotkey.install_hotkey("<Super>space", "paste", "Murmur dictation")

        self.assertEqual(result.slot, "custom4")
        self.assertEqual(result.desktop, "cinnamon")
        # binding is written as an array on Cinnamon
        binding_set = next(c for c in self.calls if c[0] == "set" and c[-2] == "binding")
        self.assertEqual(binding_set[-1], "['<Super>space']")
        # the new slot is appended to the registered custom-list
        list_set = next(c for c in self.calls if c[0] == "set" and c[2] == "custom-list")
        self.assertIn("custom4", list_set[-1])

    def test_install_uses_string_binding_on_gnome(self):
        def fake(*args):
            if args[0] == "get" and args[-1] == "custom-keybindings":
                return "@as []"
            if args[0] == "get":
                return "''"
            return ""

        with mock.patch("murmur.hotkey.detect_desktop", return_value="gnome"), mock.patch(
            "murmur.hotkey.shutil.which", return_value="/venv/bin/murmur"
        ), mock.patch("murmur.hotkey._gsettings", side_effect=fake) as gs:
            result = hotkey.install_hotkey("<Super>space", "paste", "Murmur dictation")

        self.assertEqual(result.slot, "custom0")
        binding_set = next(c.args for c in gs.call_args_list if c.args[0] == "set" and c.args[-2] == "binding")
        self.assertEqual(binding_set[-1], "'<Super>space'")  # plain string, not an array
        # GNOME registers the shortcut by full dconf path
        list_set = next(c.args for c in gs.call_args_list if c.args[0] == "set" and c.args[2] == "custom-keybindings")
        self.assertIn("/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/custom0/", list_set[-1])

    def test_remove_drops_murmur_slot_and_resets_child(self):
        with mock.patch("murmur.hotkey.detect_desktop", return_value="cinnamon"), mock.patch(
            "murmur.hotkey.shutil.which", return_value="/venv/bin/murmur"
        ), mock.patch("murmur.hotkey._gsettings", side_effect=self._reuse_fake()) as gs:
            removed = hotkey.remove_hotkey()

        self.assertEqual(removed, ["custom0"])
        # the slot is dropped from the registered list (which becomes empty)…
        list_set = next(c.args for c in gs.call_args_list if c.args[0] == "set" and c.args[2] == "custom-list")
        self.assertEqual(list_set[-1], "@as []")
        # …and its child keys are reset
        self.assertTrue(any(c.args[0] == "reset-recursively" for c in gs.call_args_list))

    def test_remove_is_noop_without_murmur_slot(self):
        def fake(*args):
            if args[0] == "get" and args[-1] == "custom-list":
                return "['custom0']"
            return "'/usr/bin/diodon'" if args[-1] == "command" else "'Diodon'"

        with mock.patch("murmur.hotkey.detect_desktop", return_value="cinnamon"), mock.patch(
            "murmur.hotkey.shutil.which", return_value="/venv/bin/murmur"
        ), mock.patch("murmur.hotkey._gsettings", side_effect=fake):
            self.assertEqual(hotkey.remove_hotkey(), [])

    def test_unsupported_desktop_raises_with_instructions(self):
        with mock.patch("murmur.hotkey.detect_desktop", return_value="sway"), mock.patch(
            "murmur.hotkey.shutil.which", return_value=None
        ):
            with self.assertRaises(hotkey.HotkeyUnsupported) as ctx:
                hotkey.install_hotkey()
            self.assertIn("custom shortcut", ctx.exception.instructions().lower())

    def _reuse_fake(self, binding="['<Primary><Shift>End']"):
        def fake(*args):
            if args[0] == "get" and args[-1] == "custom-list":
                return "['custom0']"
            if args[0] == "get" and args[-1] == "command":
                return "'/venv/bin/murmur toggle --target paste'"
            if args[0] == "get" and args[-1] == "binding":
                return binding
            if args[0] == "get":
                return "'Dictée vocale (Murmur)'"
            return ""

        return fake

    def test_install_reuses_existing_murmur_slot(self):
        with mock.patch("murmur.hotkey.detect_desktop", return_value="cinnamon"), mock.patch(
            "murmur.hotkey.shutil.which", return_value="/venv/bin/murmur"
        ), mock.patch("murmur.hotkey._gsettings", side_effect=self._reuse_fake()) as gs:
            result = hotkey.install_hotkey()

        self.assertEqual(result.slot, "custom0")
        # reusing a slot must not rewrite the registered list…
        self.assertFalse(any(c.args[0] == "set" and c.args[2] == "custom-list" for c in gs.call_args_list))
        # …nor overwrite the name the user gave it
        self.assertFalse(any(c.args[0] == "set" and c.args[-2] == "name" for c in gs.call_args_list))

    def test_install_preserves_existing_key_unless_overridden(self):
        with mock.patch("murmur.hotkey.detect_desktop", return_value="cinnamon"), mock.patch(
            "murmur.hotkey.shutil.which", return_value="/venv/bin/murmur"
        ), mock.patch("murmur.hotkey._gsettings", side_effect=self._reuse_fake()):
            # bare install keeps the key the user already chose
            self.assertEqual(hotkey.install_hotkey().key, "<Primary><Shift>End")

        with mock.patch("murmur.hotkey.detect_desktop", return_value="cinnamon"), mock.patch(
            "murmur.hotkey.shutil.which", return_value="/venv/bin/murmur"
        ), mock.patch("murmur.hotkey._gsettings", side_effect=self._reuse_fake()):
            # an explicit --key moves it
            self.assertEqual(hotkey.install_hotkey("<Super>space").key, "<Super>space")


if __name__ == "__main__":
    unittest.main()
