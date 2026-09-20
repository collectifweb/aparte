"""Mac API boundaries and recovery under isolated synthetic settings."""
import argparse
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from aparte import cli, desktop, recovery
from aparte.config import Settings
from test_desktop import make_request


class MacReliabilityTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        env = patch.dict(os.environ, {"APARTE_CONFIG": str(self.root / "config.json"),
                                    "APARTE_RUNTIME_DIR": str(self.root / "run")})
        env.start()
        self.addCleanup(env.stop)
        mac = patch.object(desktop, "is_macos", return_value=True)
        mac.start()
        self.addCleanup(mac.stop)
        self.handler = desktop.handler_factory(Settings())

    def test_mac_capabilities_do_not_offer_system_effects(self):
        response = make_request("GET", "/api/config", handler_class=self.handler)
        data = json.loads(response["body"])
        self.assertEqual(data["platform"], "macos")
        self.assertEqual(data["capabilities"], {"paste": False, "system_clipboard": False})
        for route in ("/api/copy", "/api/paste", "/api/update/apply"):
            self.assertEqual(make_request("POST", route, b'{}', handler_class=self.handler)["status"], 404)

    def test_foreign_host_cannot_read_native_or_private_state(self):
        for route in ("/api/config", "/api/history", "/api/recovery", "/api/recording-state", "/api/hotkey-state"):
            response = make_request("GET", route, headers={"Host": "foreign.invalid:8765"}, handler_class=self.handler)
            self.assertEqual(response["status"], 403)

    def test_model_preparation_gates_the_real_handler_controller(self):
        controller = self.handler._recording_controller
        with patch.object(desktop.model_download, "start"), \
             patch.object(desktop.model_download, "progress", return_value={"state": "downloading"}), \
             patch("aparte.macos_recording.notify"), \
             patch("aparte.macos_recording._sounddevice") as device:
            controller.toggle()
        device.assert_not_called()
        self.assertNotEqual(controller.state, "recording")

    def test_raw_recovery_never_pastes_and_keeps_the_capture(self):
        audio = self.root / "synthetic.wav"
        audio.write_bytes(b"synthetic audio")
        identifier = recovery.save_failure(audio, raw_text="texte brut")
        with patch.object(cli, "copy_text") as copy, patch.object(cli, "paste_text") as paste:
            output = cli.retry_recovery(identifier, argparse.Namespace(no_polish=True, target="stdout"), Settings())
        self.assertEqual(output, "texte brut")
        copy.assert_not_called()
        paste.assert_not_called()
        self.assertEqual(len(recovery.entries()), 1)
