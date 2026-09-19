import os
import unittest
from unittest import mock

from aparte import hotkey


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
        with mock.patch("aparte.hotkey.shutil.which", return_value="/venv/bin/aparte"):
            self.assertEqual(hotkey.toggle_command("paste"), "/venv/bin/aparte toggle --target paste --hotkey")

    def test_manual_instructions_mention_command_and_key(self):
        text = hotkey.manual_instructions("/venv/bin/aparte toggle --target paste", "<Super>space", "cinnamon")
        self.assertIn("/venv/bin/aparte toggle --target paste", text)
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

        return mock.patch("aparte.hotkey._gsettings", side_effect=fake)

    def test_install_allocates_next_slot_on_cinnamon(self):
        with mock.patch("aparte.hotkey.detect_desktop", return_value="cinnamon"), mock.patch(
            "aparte.hotkey.shutil.which", return_value="/venv/bin/aparte"
        ), self._patch_gsettings("['custom0', 'custom1', 'custom2', 'custom3']"):
            result = hotkey.install_hotkey("<Super>space", "paste", "Aparté dictation")

        self.assertEqual(result.slot, "custom4")
        self.assertEqual(result.desktop, "cinnamon")
        # binding is written as an array on Cinnamon
        binding_set = next(c for c in self.calls if c[0] == "set" and c[-2] == "binding")
        self.assertEqual(binding_set[-1], "['<Super>space']")
        # the new slot is appended to the registered custom-list
        list_set = next(c for c in self.calls if c[0] == "set" and c[2] == "custom-list")
        self.assertIn("custom4", list_set[-1])

    def test_install_reuses_and_relabels_a_pre_rename_slot(self):
        """A shortcut bound before the rename is updated in place, not duplicated."""

        def fake(*args):
            if args[0] == "get" and args[-1] == "custom-list":
                return "['custom0']"
            if args[0] == "get" and args[-1] == "command":
                return "'/venv/bin/murmur toggle --target paste'"
            if args[0] == "get" and args[-1] == "name":
                return "'Murmur dictation'"
            if args[0] == "get" and args[-1] == "binding":
                return "['<Control>d']"
            return ""

        with mock.patch("aparte.hotkey.detect_desktop", return_value="cinnamon"), mock.patch(
            "aparte.hotkey.shutil.which", return_value="/venv/bin/aparte"
        ), mock.patch("aparte.hotkey._gsettings", side_effect=fake) as gs:
            result = hotkey.install_hotkey(None, "paste", "Aparté dictation")

        calls = [c.args for c in gs.call_args_list]
        self.assertEqual(result.slot, "custom0")  # reused, no duplicate slot
        self.assertEqual(result.key, "<Control>d")  # keeps the key already chosen
        name_set = next(c for c in calls if c[0] == "set" and c[-2] == "name")
        self.assertEqual(name_set[-1], "'Aparté dictation'")  # stale label refreshed
        command_set = next(c for c in calls if c[0] == "set" and c[-2] == "command")
        self.assertIn("aparte toggle", command_set[-1])  # repointed at the new binary
        self.assertFalse(any(c[0] == "set" and c[2] == "custom-list" for c in calls))

    def test_install_uses_string_binding_on_gnome(self):
        def fake(*args):
            if args[0] == "get" and args[-1] == "custom-keybindings":
                return "@as []"
            if args[0] == "get":
                return "''"
            return ""

        with mock.patch("aparte.hotkey.detect_desktop", return_value="gnome"), mock.patch(
            "aparte.hotkey.shutil.which", return_value="/venv/bin/aparte"
        ), mock.patch("aparte.hotkey._gsettings", side_effect=fake) as gs:
            result = hotkey.install_hotkey("<Super>space", "paste", "Aparté dictation")

        self.assertEqual(result.slot, "custom0")
        binding_set = next(c.args for c in gs.call_args_list if c.args[0] == "set" and c.args[-2] == "binding")
        self.assertEqual(binding_set[-1], "'<Super>space'")  # plain string, not an array
        # GNOME registers the shortcut by full dconf path
        list_set = next(c.args for c in gs.call_args_list if c.args[0] == "set" and c.args[2] == "custom-keybindings")
        self.assertIn("/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/custom0/", list_set[-1])

    def test_remove_drops_aparte_slot_and_resets_child(self):
        with mock.patch("aparte.hotkey.detect_desktop", return_value="cinnamon"), mock.patch(
            "aparte.hotkey.shutil.which", return_value="/venv/bin/aparte"
        ), mock.patch("aparte.hotkey._gsettings", side_effect=self._reuse_fake()) as gs:
            removed = hotkey.remove_hotkey()

        self.assertEqual(removed, ["custom0"])
        # the slot is dropped from the registered list (which becomes empty)…
        list_set = next(c.args for c in gs.call_args_list if c.args[0] == "set" and c.args[2] == "custom-list")
        self.assertEqual(list_set[-1], "@as []")
        # …and its child keys are reset
        self.assertTrue(any(c.args[0] == "reset-recursively" for c in gs.call_args_list))

    def test_remove_is_noop_without_aparte_slot(self):
        def fake(*args):
            if args[0] == "get" and args[-1] == "custom-list":
                return "['custom0']"
            return "'/usr/bin/diodon'" if args[-1] == "command" else "'Diodon'"

        with mock.patch("aparte.hotkey.detect_desktop", return_value="cinnamon"), mock.patch(
            "aparte.hotkey.shutil.which", return_value="/venv/bin/aparte"
        ), mock.patch("aparte.hotkey._gsettings", side_effect=fake):
            self.assertEqual(hotkey.remove_hotkey(), [])

    def test_unsupported_desktop_raises_with_instructions(self):
        with mock.patch("aparte.hotkey.detect_desktop", return_value="sway"), mock.patch(
            "aparte.hotkey.shutil.which", return_value=None
        ):
            with self.assertRaises(hotkey.HotkeyUnsupported) as ctx:
                hotkey.install_hotkey()
            self.assertIn("custom shortcut", ctx.exception.instructions().lower())

    def _reuse_fake(self, binding="['<Primary><Shift>End']"):
        def fake(*args):
            if args[0] == "get" and args[-1] == "custom-list":
                return "['custom0']"
            if args[0] == "get" and args[-1] == "command":
                return "'/venv/bin/aparte toggle --target paste'"
            if args[0] == "get" and args[-1] == "binding":
                return binding
            if args[0] == "get":
                return "'Dictée vocale (Aparté)'"
            return ""

        return fake

    def test_install_reuses_existing_aparte_slot(self):
        with mock.patch("aparte.hotkey.detect_desktop", return_value="cinnamon"), mock.patch(
            "aparte.hotkey.shutil.which", return_value="/venv/bin/aparte"
        ), mock.patch("aparte.hotkey._gsettings", side_effect=self._reuse_fake()) as gs:
            result = hotkey.install_hotkey()

        self.assertEqual(result.slot, "custom0")
        # reusing a slot must not rewrite the registered list…
        self.assertFalse(any(c.args[0] == "set" and c.args[2] == "custom-list" for c in gs.call_args_list))
        # …nor overwrite the name the user gave it
        self.assertFalse(any(c.args[0] == "set" and c.args[-2] == "name" for c in gs.call_args_list))

    def test_install_preserves_existing_key_unless_overridden(self):
        with mock.patch("aparte.hotkey.detect_desktop", return_value="cinnamon"), mock.patch(
            "aparte.hotkey.shutil.which", return_value="/venv/bin/aparte"
        ), mock.patch("aparte.hotkey._gsettings", side_effect=self._reuse_fake()):
            # bare install keeps the key the user already chose
            self.assertEqual(hotkey.install_hotkey().key, "<Primary><Shift>End")

        with mock.patch("aparte.hotkey.detect_desktop", return_value="cinnamon"), mock.patch(
            "aparte.hotkey.shutil.which", return_value="/venv/bin/aparte"
        ), mock.patch("aparte.hotkey._gsettings", side_effect=self._reuse_fake()):
            # an explicit --key moves it
            self.assertEqual(hotkey.install_hotkey("<Super>space").key, "<Super>space")


class PrivateShortcutMigrationTest(unittest.TestCase):
    def test_recognizes_stock_commands_in_current_installation(self):
        with mock.patch.object(hotkey.sys, "executable", "/venv/bin/python"):
            for command in ("/venv/bin/aparte toggle", "/venv/bin/murmur toggle --target copy",
                            "/venv/bin/python -m aparte toggle --target paste"):
                with self.subTest(command=command):
                    self.assertEqual(hotkey._private_command(command), command + " --hotkey")

    def test_unwraps_only_known_log_redirection(self):
        command = "/venv/bin/python -m aparte toggle --target paste"
        with mock.patch.object(hotkey.sys, "executable", "/venv/bin/python"):
            self.assertEqual(hotkey._private_command("bash -c '" + command + " >> /tmp/aparte-toggle.log 2>&1'"),
                             command + " --hotkey")
            self.assertIsNone(hotkey._private_command("bash -c '" + command + " >> /tmp/custom.log 2>&1'"))

    def test_preserves_custom_commands_other_installs_and_stdout(self):
        with mock.patch.object(hotkey.sys, "executable", "/venv/bin/python"):
            for command in ("/other/bin/aparte toggle --target paste", "/other/bin/python -m aparte toggle",
                            "/venv/bin/aparte toggle --target stdout", "/venv/bin/aparte toggle --no-polish",
                            "/venv/bin/aparte toggle --hotkey", "env APARTE_LANGUAGE=fr /venv/bin/aparte toggle",
                            "bash -c '/venv/bin/aparte toggle; echo ok >> /tmp/aparte-toggle.log 2>&1'",
                            "bash -c '/venv/bin/aparte toggle $(whoami) >> /tmp/aparte-toggle.log 2>&1'",
                            "my-custom-toggle-script"):
                with self.subTest(command=command):
                    self.assertIsNone(hotkey._private_command(command))

    def test_migration_changes_only_command_and_is_idempotent(self):
        command = "bash -c '/venv/bin/python -m aparte toggle --target copy >> /tmp/aparte-toggle.log 2>&1'"
        state = {"custom0": command, "custom1": "/other/bin/aparte toggle"}
        writes = []
        def fake(*args):
            if args[:1] == ("get",) and args[-1] == "custom-list":
                return "['custom0', 'custom1']"
            slot = args[1].split("/")[-2]
            if args[0] == "get":
                return repr(state[slot])
            writes.append(args)
            state[slot] = hotkey.ast.literal_eval(args[-1])
            return ""
        with mock.patch.object(hotkey, "_provider", return_value=hotkey.PROVIDERS["cinnamon"]), \
             mock.patch.object(hotkey, "_gsettings", side_effect=fake), \
             mock.patch.object(hotkey.sys, "executable", "/venv/bin/python"):
            self.assertEqual(hotkey.migrate_hotkey_logging(), ["custom0"])
            self.assertEqual(hotkey.migrate_hotkey_logging(), [])
        self.assertEqual(len(writes), 1)
        self.assertEqual(writes[0][-2], "command")
        self.assertEqual(state["custom0"], "/venv/bin/python -m aparte toggle --target copy --hotkey")
        self.assertEqual(state["custom1"], "/other/bin/aparte toggle")

    def test_gsettings_failure_does_not_prevent_startup(self):
        with mock.patch.object(hotkey, "_provider", return_value=hotkey.PROVIDERS["cinnamon"]), \
             mock.patch.object(hotkey, "_gsettings", side_effect=hotkey.subprocess.TimeoutExpired("gsettings", 2)):
            self.assertEqual(hotkey.migrate_hotkey_logging(), [])

    def test_gsettings_calls_have_a_timeout(self):
        with mock.patch.object(hotkey.subprocess, "run", return_value=mock.Mock(stdout="''")) as run:
            hotkey._gsettings("get", "schema", "key")
        self.assertEqual(run.call_args.kwargs["timeout"], 2)

    def test_stdout_shortcut_remains_explicit(self):
        with mock.patch.object(hotkey.shutil, "which", return_value="/venv/bin/aparte"):
            self.assertEqual(hotkey.toggle_command("stdout"), "/venv/bin/aparte toggle --target stdout")

    def test_distinct_venvs_pointing_to_same_python_are_not_confused(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            current = root / "current/bin/python"
            other = root / "other/bin/python"
            for path in (current, other):
                path.parent.mkdir(parents=True)
                path.symlink_to(hotkey.sys.executable)
            with mock.patch.object(hotkey.sys, "executable", str(current)):
                self.assertIsNone(hotkey._private_command(f"{other} -m aparte toggle"))
                self.assertEqual(hotkey._private_command(f"{current} -m aparte toggle"),
                                 f"{current} -m aparte toggle --hotkey")


if __name__ == "__main__":
    unittest.main()
