import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aparte import diagnostics, session
from aparte.config import Settings
from aparte.diagnostics import collect_checks, collect_diagnostics, walled_venv_config


class DiagnosticsTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        env = {
            "APARTE_CONFIG": str(self.root / "config.json"),
            "APARTE_RUNTIME_DIR": str(self.root),
            **{key: str(self.root / key.lower()) for key in (
                "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME",
                "XDG_RUNTIME_DIR", "XDG_CACHE_HOME",
            )},
        }
        environment = mock.patch.dict(os.environ, env)
        environment.start()
        self.addCleanup(environment.stop)
        hotkey = mock.patch.object(diagnostics, "hotkey_info", return_value={})
        hotkey.start()
        self.addCleanup(hotkey.stop)

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

    def test_only_a_live_capture_reports_an_open_microphone(self):
        for state in ("recording", "processing", "recoverable", "idle"):
            with self.subTest(state=state), mock.patch.object(
                diagnostics, "get_dictation_state", return_value=state,
            ):
                data = collect_diagnostics(Settings())
            self.assertEqual(data["recording_active"], state == "recording")
            self.assertEqual(data["dictation_state"], state)

    def test_stopped_capture_is_recoverable_without_an_open_microphone(self):
        audio = self.root / "toggle-synthetic.wav"
        audio.write_bytes(b"\x00" * (44 + 16000))
        session_path = session.get_session_path()
        session_path.write_text(json.dumps({
            "pid": -1,  # No real process or microphone belongs to this fixture.
            "audio_path": str(audio),
            "sample_rate": 16000,
            "started_at": 1.0,
        }), encoding="utf-8")

        data = collect_diagnostics(Settings())

        self.assertFalse(data["recording_active"])
        self.assertEqual(data["dictation_state"], "recoverable")
        self.assertTrue(session_path.exists())
        self.assertTrue(audio.exists())

    def test_unreadable_or_transitioning_state_does_not_claim_microphone_closed(self):
        for error in (OSError("runtime unavailable"), session.ToggleSessionError("transition")):
            with self.subTest(error=type(error).__name__), mock.patch.object(
                diagnostics, "get_dictation_state", side_effect=error,
            ):
                data = collect_diagnostics(Settings())
            self.assertEqual(data["dictation_state"], "unknown")
            self.assertIsNone(data["recording_active"])


class TrayFixTest(unittest.TestCase):
    """Deux pannes distinctes derrière la même icône absente, et elles demandent
    des gestes opposés. Les confondre a fait tourner en rond le 31/07 : les
    paquets système étaient installés et fonctionnels, le venv ne les voyait pas,
    et le diagnostic répondait « sudo apt install » — à quoi apt répond « déjà à
    la version la plus récente »."""

    def _venv(self, line):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        (Path(directory.name) / "pyvenv.cfg").write_text(
            f"home = /usr/bin\n{line}\nversion = 3.12.3\n", encoding="utf-8"
        )
        patcher = mock.patch.multiple(
            diagnostics.sys, prefix=directory.name, base_prefix="/usr"
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        return Path(directory.name) / "pyvenv.cfg"

    def test_a_walled_venv_is_named(self):
        config = self._venv("include-system-site-packages = false")
        self.assertEqual(walled_venv_config(), config)

    def test_an_open_venv_is_not_a_problem(self):
        self._venv("include-system-site-packages = true")
        self.assertIsNone(walled_venv_config())

    def test_outside_a_venv_there_is_no_wall(self):
        with mock.patch.multiple(diagnostics.sys, prefix="/usr", base_prefix="/usr"):
            self.assertIsNone(walled_venv_config())

    def test_the_wall_gets_the_command_that_opens_it(self):
        config = self._venv("include-system-site-packages = false")
        fix = diagnostics._tray_fix()
        self.assertIn(str(config), fix)
        self.assertNotIn("apt install", fix)

    def test_a_genuinely_missing_pygobject_still_points_at_apt(self):
        self._venv("include-system-site-packages = true")
        self.assertIn("apt install python3-gi", diagnostics._tray_fix())


if __name__ == "__main__":
    unittest.main()
