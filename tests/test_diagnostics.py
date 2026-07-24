import contextlib
import unittest
from unittest import mock

from aparte import diagnostics
from aparte.config import Settings
from aparte.diagnostics import collect_checks, collect_diagnostics


class DiagnosticsTest(unittest.TestCase):
    def test_essential_checks_are_present(self):
        keys = {c.key for c in collect_checks(Settings())}
        self.assertIn("whisper_backend", keys)
        self.assertIn("recorder", keys)
        self.assertIn("paste", keys)

    def test_missing_essential_checks_carry_a_fix_command(self):
        for check in collect_checks(Settings()):
            if check.essential and not check.ok:
                self.assertTrue(check.fix, f"{check.key} should expose a fix command")

    def test_collect_diagnostics_shape(self):
        data = collect_diagnostics(Settings())
        self.assertEqual(set(data["summary"]), {"ready", "can_transcribe", "can_record", "can_insert"})
        self.assertTrue(all({"key", "label", "ok", "category"} <= set(c) for c in data["checks"]))
        # ready implies every essential check passed
        essentials = [c for c in data["checks"] if c["essential"]]
        self.assertEqual(data["summary"]["ready"], all(c["ok"] for c in essentials))


class MacDiagnosticsTest(unittest.TestCase):
    """On macOS the check list is different — TCC permissions, no ALSA/paste —
    but the same summary and panel must keep working. Permissions are mocked;
    the machine here is Linux."""

    def _mac_env(self, mic="authorized", accessibility=True, model_cached=True):
        stack = contextlib.ExitStack()
        stack.enter_context(mock.patch.object(diagnostics, "is_macos", return_value=True))
        stack.enter_context(
            mock.patch.object(diagnostics, "_whisper_model_cached", return_value=model_cached)
        )
        stack.enter_context(
            mock.patch("aparte.macos_permissions.microphone_authorization", return_value=mic)
        )
        stack.enter_context(
            mock.patch("aparte.macos_permissions.accessibility_trusted", return_value=accessibility)
        )
        return stack

    def test_the_macos_list_has_permissions_and_no_linux_only_checks(self):
        with self._mac_env():
            keys = {c.key for c in collect_checks(Settings())}
        self.assertLessEqual(
            {"whisper_backend", "recorder", "mic_permission", "accessibility", "model_ready"},
            keys,
        )
        self.assertNotIn("paste", keys)  # synthetic paste is M3
        self.assertNotIn("tray", keys)  # PyGObject tray is Linux-only

    def test_the_summary_does_not_crash_without_a_paste_check(self):
        with self._mac_env():
            data = collect_diagnostics(Settings())
        self.assertEqual(
            set(data["summary"]), {"ready", "can_transcribe", "can_record", "can_insert"}
        )
        self.assertTrue(data["summary"]["can_insert"])  # pbcopy is always there

    def test_a_denied_microphone_fails_and_points_to_settings(self):
        with self._mac_env(mic="denied"):
            checks = collect_checks(Settings())
        mic = next(c for c in checks if c.key == "mic_permission")
        self.assertFalse(mic.ok)
        self.assertIn("Settings", mic.detail)

    def test_an_authorized_microphone_passes(self):
        with self._mac_env(mic="authorized"):
            checks = collect_checks(Settings())
        mic = next(c for c in checks if c.key == "mic_permission")
        self.assertTrue(mic.ok)

    def test_the_cli_doctor_surfaces_a_permission_that_has_no_shell_fix(self):
        import io

        from aparte import cli

        with self._mac_env(mic="denied"):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                cli.print_doctor(Settings())
        text = out.getvalue()
        # The microphone permission carries no `fix`; without the guidance branch
        # in print_doctor its remedy would never reach a CLI user.
        self.assertIn("Microphone permission", text)
        self.assertIn("System Settings", text)


if __name__ == "__main__":
    unittest.main()
