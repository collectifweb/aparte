import errno
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from aparte import desktop, recovery
from aparte.config import Settings
from aparte.session import ToggleSessionError
from test_desktop import make_request


class RecoveryEndpointTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        env = {
            "APARTE_CONFIG": str(self.root / "config.json"),
            "APARTE_RUNTIME_DIR": str(self.root / "run"),
            "XDG_STATE_HOME": str(self.root / "state"),
            "XDG_CONFIG_HOME": str(self.root / "config"),
        }
        patcher = mock.patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.audio = self.root / "synthetic.wav"
        self.audio.write_bytes(b"synthetic audio")
        self.handler = desktop.handler_factory(Settings())
        self.transcriber = mock.Mock()
        self.transcriber.transcribe.return_value = SimpleNamespace(text="bonjour tout le monde")
        patcher = mock.patch.object(desktop, "build_transcriber", return_value=self.transcriber)
        patcher.start()
        self.addCleanup(patcher.stop)

    def post(self, route, identifier, **extra):
        return make_request("POST", route, json.dumps({"id": identifier, **extra}).encode(),
                            handler_class=self.handler)

    def test_list_contains_only_metadata_and_cannot_be_cached(self):
        identifier = recovery.save_failure(self.audio, "private synthetic text")
        result = make_request("GET", "/api/recovery", handler_class=self.handler)
        self.assertEqual(result["status"], 200)
        entry = json.loads(result["body"])["entries"][0]
        self.assertEqual(entry["id"], identifier)
        self.assertTrue(entry["has_text"])
        self.assertNotIn(b"private synthetic", result["body"])
        self.assertNotIn(str(self.audio).encode(), result["body"])
        self.assertEqual(result["headers"]["Cache-Control"], "no-store")

    def test_foreign_host_cannot_read_any_private_data(self):
        recovery.save_failure(self.audio)
        for route in ("/api/recovery", "/api/history", "/api/config"):
            with self.subTest(route=route):
                result = make_request("GET", route, headers={
                    "Host": "foreign.invalid:8765", "Origin": "http://foreign.invalid:8765",
                }, handler_class=self.handler)
                self.assertEqual(result["status"], 403)

    def test_foreign_origin_cannot_retry_or_delete(self):
        identifier = recovery.save_failure(self.audio)
        for action in ("retry", "delete"):
            result = make_request("POST", "/api/recovery/" + action,
                                  json.dumps({"id": identifier}).encode(),
                                  headers={"Origin": "http://foreign.invalid"},
                                  handler_class=self.handler)
            self.assertEqual(result["status"], 403)
        self.assertEqual(len(recovery.entries()), 1)
        self.transcriber.transcribe.assert_not_called()

    def test_retry_uses_local_cached_model_and_keeps_capture_until_deleted(self):
        identifier = recovery.save_failure(self.audio)
        with mock.patch("aparte.cli.transcribe_path") as delegate, \
                mock.patch.object(desktop, "copy_text") as copy, \
                mock.patch.object(desktop, "paste_text") as paste:
            first = self.post("/api/recovery/retry", identifier)
            second = self.post("/api/recovery/retry", identifier)
        self.assertEqual(first["status"], 200)
        self.assertEqual(json.loads(first["body"])["text"], "Bonjour tout le monde.")
        self.assertEqual(first["body"], second["body"])
        self.transcriber.transcribe.assert_called_once()
        delegate.assert_not_called()
        copy.assert_not_called()
        paste.assert_not_called()
        self.assertEqual(len(recovery.entries()), 1)
        self.assertEqual(self.post("/api/recovery/delete", identifier)["status"], 200)
        self.assertEqual(recovery.entries(), [])

    def test_polish_failure_still_allows_raw_recovery(self):
        identifier = recovery.save_failure(self.audio)
        with mock.patch("aparte.cli.polish_text", side_effect=RuntimeError("polisher unavailable")):
            self.assertEqual(self.post("/api/recovery/retry", identifier)["status"], 500)
            result = self.post("/api/recovery/retry", identifier, raw=True)
        self.assertEqual(result["status"], 200)
        self.assertEqual(json.loads(result["body"])["text"], "bonjour tout le monde")
        self.transcriber.transcribe.assert_called_once()

    def test_expired_capture_is_inaccessible_and_removed(self):
        with mock.patch.object(recovery.time, "time", return_value=1000):
            identifier = recovery.save_failure(self.audio)
        with mock.patch.object(recovery.time, "time", return_value=4601):
            self.assertEqual(self.post("/api/recovery/retry", identifier)["status"], 410)
        self.assertEqual(recovery.entries(), [])
        self.transcriber.transcribe.assert_not_called()

    def test_claim_blocks_competing_retry_and_deletion(self):
        identifier = recovery.save_failure(self.audio)
        with recovery.claim(identifier):
            for action in ("retry", "delete"):
                self.assertEqual(self.post("/api/recovery/" + action, identifier)["status"], 409)
        self.assertEqual(len(recovery.entries()), 1)

    def test_identifiers_cannot_escape_the_recovery_directory(self):
        for identifier in ("../synthetic.wav", str(self.audio), "a" * 31):
            result = self.post("/api/recovery/delete", identifier)
            self.assertIn(result["status"], (400, 410))
        self.assertEqual(self.audio.read_bytes(), b"synthetic audio")

    def test_retry_shares_inference_lock_with_live_preview(self):
        identifier = recovery.save_failure(self.audio)
        started, release = threading.Event(), threading.Event()
        def transcribe(path):
            started.set()
            if not release.wait(3):
                raise RuntimeError("test timed out")
            return SimpleNamespace(text="bonjour")
        self.transcriber.transcribe.side_effect = transcribe
        responses = []
        thread = threading.Thread(target=lambda: responses.append(self.post("/api/recovery/retry", identifier)))
        thread.start()
        try:
            self.assertTrue(started.wait(3))
            result = make_request("POST", "/api/transcribe?preview=1", b"synthetic",
                                  handler_class=self.handler)
            self.assertTrue(json.loads(result["body"])["busy"])
        finally:
            release.set()
            thread.join(3)
        self.assertFalse(thread.is_alive())
        self.assertEqual(responses[0]["status"], 200)

    def test_upload_storage_failure_does_not_poison_recovery_or_preview(self):
        with mock.patch.object(desktop.tempfile, "NamedTemporaryFile",
                               side_effect=OSError(errno.ENOSPC, "No space left")):
            failed = make_request("POST", "/api/transcribe", b"synthetic", handler_class=self.handler)
        self.assertEqual(failed["status"], 500)
        result = make_request("POST", "/api/transcribe?preview=1", b"synthetic", handler_class=self.handler)
        self.assertEqual(json.loads(result["body"])["text"], "bonjour tout le monde")

    def test_failed_browser_final_is_retained_but_preview_and_cli_are_not(self):
        self.transcriber.transcribe.side_effect = RuntimeError("model unavailable")
        for query in ("preview=1&recover=1", ""):
            result = make_request("POST", "/api/transcribe?" + query, b"synthetic",
                                  headers={"Content-Type": "audio/wav"}, handler_class=self.handler)
            self.assertEqual(result["status"], 500)
            self.assertEqual(recovery.entries(), [])
        result = make_request("POST", "/api/transcribe?recover=1", b"browser synthetic",
                              headers={"Content-Type": "audio/wav"}, handler_class=self.handler)
        self.assertEqual(result["status"], 500)
        entry = recovery.entries()[0]
        with recovery.claim(entry["id"]) as item:
            self.assertEqual(item.audio_path.read_bytes(), b"browser synthetic")

    def test_recovery_list_reports_unavailable_runtime_as_service_failure(self):
        with mock.patch.object(recovery, "entries", side_effect=ToggleSessionError("not writable")):
            result = make_request("GET", "/api/recovery", handler_class=self.handler)
        self.assertEqual(result["status"], 503)


class RecoveryMaintenanceTest(unittest.TestCase):
    def test_cleanup_repeats_without_a_browser_and_survives_io_failure(self):
        stop = threading.Event()
        calls = []
        def sweep():
            calls.append(1)
            if len(calls) == 1:
                raise ToggleSessionError("temporarily unavailable runtime")
            stop.set()
        with mock.patch.object(recovery, "sweep", side_effect=sweep):
            desktop._maintain_recovery(stop, interval=0.001)
        self.assertEqual(len(calls), 2)
