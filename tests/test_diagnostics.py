import unittest

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


if __name__ == "__main__":
    unittest.main()
