"""Timing evidence from the real CLI/HTTP path, with synthetic audio/models."""
import json
import os
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest import mock
import wave

from aparte import cli, desktop, performance, recovery, technical_log
from aparte.config import Settings
from test_desktop import make_request


class PerformanceIntegrationTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        env = {key: value for key, value in os.environ.items()
               if not key.startswith(("APARTE_", "MURMUR_"))}
        env["APARTE_CONFIG"] = str(self.root / "config.json")
        for key in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME",
                    "XDG_RUNTIME_DIR", "XDG_CACHE_HOME"):
            env[key] = str(self.root / key)
        patcher = mock.patch.dict(os.environ, env, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.audio = self.root / "PRIVATE_PATH.wav"
        with wave.open(str(self.audio), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(16000)
            output.writeframes(b"\0\0" * 1600)
        self.args = cli.build_parser().parse_args(["toggle", "--target", "copy", "--keep-audio"])
        self.notifications = mock.patch.object(cli, "notify")
        self.notifications.start()
        self.addCleanup(self.notifications.stop)

    def rows(self):
        directory = self.root / "XDG_STATE_HOME/aparte/logs"
        return [json.loads(line) for file in directory.glob("hotkey.jsonl*")
                for line in file.read_text().splitlines()]

    def serve(self, handler):
        server = desktop.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        def cleanup():
            server.shutdown()
            thread.join(timeout=2)
            server.server_close()

        self.addCleanup(cleanup)
        return server.server_port

    def test_shortcut_http_share_trace_and_cache_load_is_measured_once(self):
        model = SimpleNamespace(transcribe=lambda _: SimpleNamespace(text="PRIVATE_DICTATION"))
        port = self.serve(desktop.handler_factory(Settings()))
        delegate = desktop.transcribe_via_running_app
        events = []
        writer = technical_log.write_performance

        def observe(kind, **fields):
            # Real logging deliberately drops contended writes. Verify emission
            # separately from disk retention while still exercising the writer.
            events.append({"event": "performance_" + kind, **fields})
            writer(kind, **fields)

        with mock.patch.object(desktop, "build_transcriber", return_value=model) as build, \
                mock.patch.object(technical_log, "write_performance", side_effect=observe), \
                mock.patch.object(cli, "transcribe_via_running_app",
                                  side_effect=lambda path, name: delegate(path, name, port=port)), \
                mock.patch.object(cli, "copy_text") as copy:
            for _ in range(2):
                self.assertEqual(cli._finish_dictation(self.audio, self.args, Settings()),
                                 "PRIVATE_DICTATION.")
            self.assertEqual(build.call_count, 1)
            self.assertEqual(copy.call_count, 2)

        self.assertNotIn("PRIVATE", json.dumps(self.rows()))
        rows = events
        totals = [r for r in rows if r["event"] == "performance_total"]
        self.assertEqual(len(totals), 4)  # CLI and HTTP totals overlap, not additive.
        ids = {r["trace_id"] for r in totals}
        self.assertEqual(len(ids), 2)
        for identifier in ids:
            trace = [r for r in rows if r["trace_id"] == identifier]
            self.assertEqual({r["source"] for r in trace}, {"shortcut", "http"})
            stages = {r["stage"] for r in trace if r["event"] == "performance_stage"}
            self.assertTrue({"delegation", "queue", "transcription", "polish", "delivery"} <= stages)
            self.assertTrue(all(r["success"] for r in trace if "success" in r))
        self.assertEqual(sum(r.get("stage") == "model_load" for r in rows), 1)
        self.assertTrue(any(r.get("audio_ms") == 100 for r in rows))
        self.assertNotIn("PRIVATE", json.dumps(rows))

    def test_failed_polish_is_identified_without_logging_content(self):
        with mock.patch.object(cli, "transcribe_via_running_app", return_value="PRIVATE_DICTATION"), \
                mock.patch.object(cli, "build_polisher", side_effect=RuntimeError("PRIVATE_EXCEPTION")), \
                mock.patch.object(cli, "copy_text") as copy:
            with self.assertRaises(cli._PolishFailure):
                cli._finish_dictation(self.audio, self.args, Settings())
            copy.assert_not_called()
        rows = self.rows()
        polish = next(r for r in rows if r.get("stage") == "polish")
        self.assertFalse(polish["success"])
        self.assertEqual(polish["error_type"], "RuntimeError")
        total = next(r for r in rows if r["event"] == "performance_total")
        self.assertFalse(total["success"])
        self.assertNotIn("PRIVATE", json.dumps(rows))

    def test_invalid_client_trace_is_not_logged_or_rejected_as_audio(self):
        model = SimpleNamespace(transcribe=lambda _: SimpleNamespace(text="synthetic"))
        with mock.patch.object(desktop, "build_transcriber", return_value=model):
            response = make_request("POST", "/api/transcribe", self.audio.read_bytes(),
                                    headers={"X-Aparte-Trace": "PRIVATE_HEADER", "Content-Type": "audio/wav"})
        self.assertEqual(response["status"], 200)
        rows = self.rows()
        self.assertTrue(rows)
        self.assertNotIn("PRIVATE", json.dumps(rows))
        self.assertTrue(all(technical_log.valid_trace_id(row["trace_id"]) for row in rows))

    def test_logging_failure_does_not_prevent_delivery(self):
        with mock.patch.object(technical_log, "_directory", side_effect=OSError("disk full")), \
                mock.patch.object(cli, "transcribe_via_running_app", return_value="synthetic"), \
                mock.patch.object(cli, "copy_text") as copy:
            self.assertEqual(cli._finish_dictation(self.audio, self.args, Settings()), "Synthetic.")
            copy.assert_called_once_with("Synthetic.")
        self.assertIsNone(performance.current_id())

    def test_http_recovery_error_is_not_recorded_as_success(self):
        result = make_request("POST", "/api/recovery/retry",
                              json.dumps({"id": "a" * 32}).encode())
        self.assertEqual(result["status"], 410)
        total = next(r for r in self.rows() if r["event"] == "performance_total")
        self.assertFalse(total["success"])
        self.assertEqual(total["http_status"], 410)

    def test_recovery_measures_queue_audio_and_transcription(self):
        identifier = recovery.save_failure(self.audio)
        model = SimpleNamespace(transcribe=lambda _: SimpleNamespace(text="synthetic"))
        with mock.patch.object(desktop, "build_transcriber", return_value=model):
            result = make_request("POST", "/api/recovery/retry",
                                  json.dumps({"id": identifier}).encode())
        self.assertEqual(result["status"], 200)
        rows = self.rows()
        stages = {r["stage"] for r in rows if r["event"] == "performance_stage"}
        self.assertTrue({"queue", "model_load", "transcription", "polish"} <= stages)
        self.assertTrue(any(r.get("audio_ms") == 100 for r in rows))

    def test_local_fallback_has_its_own_loading_and_transcription_stages(self):
        model = SimpleNamespace(transcribe=lambda _: SimpleNamespace(text="synthetic"))
        with mock.patch.object(cli, "transcribe_via_running_app", return_value=None), \
                mock.patch.object(cli, "build_transcriber", return_value=model), \
                mock.patch.object(cli, "copy_text"):
            cli._finish_dictation(self.audio, self.args, Settings())
        rows = self.rows()
        self.assertEqual({r["source"] for r in rows}, {"shortcut"})
        self.assertEqual(len({r["trace_id"] for r in rows}), 1)
        stages = {r["stage"] for r in rows if r["event"] == "performance_stage"}
        self.assertTrue({"delegation", "model_load", "transcription", "polish", "delivery"} <= stages)


if __name__ == "__main__":
    unittest.main()
