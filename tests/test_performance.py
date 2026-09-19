import json
from http import HTTPStatus
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest import mock
import wave

from aparte import performance, technical_log


class PerformanceTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        environment = mock.patch.dict(os.environ, {"XDG_STATE_HOME": str(self.root)})
        environment.start()
        self.addCleanup(environment.stop)
        self.logs = self.root / "aparte/logs"

    def events(self):
        return [json.loads(line) for path in sorted(self.logs.glob("*.jsonl*"))
                for line in path.read_text().splitlines()]

    def test_stage_and_total_use_monotonic_elapsed_time_and_load_snapshot(self):
        with mock.patch.object(performance.time, "monotonic", side_effect=[10, 10.1, 10.35, 11]), \
                mock.patch.object(performance.os, "getloadavg", return_value=(2.345, 0, 0)), \
                mock.patch.object(performance.os, "cpu_count", return_value=8):
            with performance.operation("shortcut", "a" * 32) as identifier:
                self.assertEqual(identifier, "a" * 32)
                with performance.stage("transcription"):
                    self.assertEqual(performance.current_id(), identifier)
        stage, total = self.events()
        self.assertEqual(stage["duration_ms"], 250)
        self.assertEqual(stage["stage"], "transcription")
        self.assertEqual(total["duration_ms"], 1000)
        self.assertEqual(total["load1"], 2.35)
        self.assertEqual(total["cpu_count"], 8)
        self.assertTrue(total["success"])
        self.assertEqual(total["trace_id"], "a" * 32)
        self.assertIsNone(performance.current_id())

    def test_nested_operation_reuses_trace_source_and_emits_one_total(self):
        with performance.operation("shortcut") as identifier:
            with performance.operation("http", "SECRET_PRIVATE_ID") as nested:
                self.assertEqual(nested, identifier)
                with performance.stage("polish"):
                    pass
        events = self.events()
        self.assertEqual([entry["event"] for entry in events], ["performance_stage", "performance_total"])
        self.assertTrue(all(entry["source"] == "shortcut" for entry in events))
        self.assertTrue(all(entry["trace_id"] == identifier for entry in events))

    def test_invalid_incoming_trace_is_replaced_and_never_logged(self):
        with performance.operation("http", "SECRET_PRIVATE_HEADER") as identifier:
            self.assertTrue(technical_log.valid_trace_id(identifier))
        self.assertNotIn("SECRET", json.dumps(self.events()))

    def test_handled_http_error_marks_total_failed_without_inventing_an_exception(self):
        with performance.operation("http"):
            with performance.operation("recovery"):
                with performance.stage("queue"):
                    performance.response_status(HTTPStatus.GONE)
        stage, total = self.events()
        self.assertTrue(stage["success"])
        self.assertNotIn("http_status", stage)
        self.assertFalse(total["success"])
        self.assertEqual(total["http_status"], 410)
        self.assertNotIn("error_type", total)
        with performance.operation("http"):
            for invalid in (True, 99, 600, "SECRET_STATUS"):
                performance.response_status(invalid)
        self.assertNotIn("http_status", self.events()[-1])
        self.assertTrue(self.events()[-1]["success"])

    def test_missing_context_or_invalid_source_or_stage_is_a_noop(self):
        with performance.stage("polish"):
            performance.execution("faster-whisper", "cpu", "int8", "small")
        with performance.operation("SECRET_PRIVATE_SOURCE") as identifier:
            self.assertIsNone(identifier)
            with performance.stage("delivery"):
                pass
        self.assertEqual(self.events(), [])
        with performance.operation("cli"):
            with performance.stage("SECRET_PRIVATE_STAGE"):
                pass
        self.assertEqual(len(self.events()), 1)
        self.assertNotIn("SECRET", json.dumps(self.events()))

    def test_failure_preserves_original_exception_and_logs_only_known_class(self):
        error = ValueError("SECRET_DICTATION /private/SECRET_PATH")
        with self.assertRaises(ValueError) as caught:
            with performance.operation("cli"):
                with performance.stage("delivery"):
                    raise error
        self.assertIs(caught.exception, error)
        self.assertEqual([entry["error_type"] for entry in self.events()], ["ValueError", "ValueError"])
        self.assertTrue(all(entry["success"] is False for entry in self.events()))
        self.assertNotIn("SECRET", json.dumps(self.events()))
        self.assertIsNone(performance.current_id())

    def test_custom_exception_class_name_cannot_smuggle_private_text(self):
        custom_error = type("SECRET_PRIVATE_CLASS", (Exception,), {})
        with self.assertRaises(custom_error):
            with performance.operation("recovery"):
                raise custom_error("SECRET_MESSAGE")
        self.assertEqual(self.events()[0]["error_type"], "Exception")
        self.assertNotIn("SECRET", json.dumps(self.events()))

    def test_execution_records_effective_enums_and_redacts_custom_values(self):
        with performance.operation("http"):
            performance.execution("faster-whisper", "cuda", "float16", "small")
            performance.execution("SECRET_BACKEND", "SECRET_DEVICE", "SECRET_COMPUTE", "/private/SECRET_MODEL")
        first, second, _ = self.events()
        self.assertEqual([first[key] for key in ("backend", "device", "compute_type", "model")],
                         ["faster-whisper", "cuda", "float16", "small"])
        self.assertTrue(all(second[key] == "unknown" for key in ("backend", "device", "compute_type", "model")))
        self.assertNotIn("SECRET", json.dumps(self.events()))

    def test_logger_rejects_invalid_schema_fields_and_numeric_values(self):
        common = {"trace_id": "a" * 32, "source": "http"}
        for duration in (-1, True, float("nan"), float("inf"), "SECRET_DURATION", technical_log.MAX_DURATION_MS + 1):
            technical_log.write_performance("total", **common, duration_ms=duration, success=True)
        technical_log.write_performance("stage", **common, stage="SECRET_STAGE", duration_ms=1, success=True)
        technical_log.write_performance("execution", **common, backend="text", device="cpu",
                                        compute_type="unknown", model="SECRET_MODEL")
        technical_log.write_performance("SECRET_KIND", **common)
        technical_log.write_performance("audio", trace_id="SECRET_HEADER", source="http", audio_ms=2)
        self.assertEqual(self.events(), [])
        technical_log.write_performance("total", **common, duration_ms=1, success=True,
                                        load1=float("nan"), cpu_count=True)
        self.assertNotIn("load1", self.events()[0])
        self.assertNotIn("cpu_count", self.events()[0])

    def _wav(self):
        path = self.root / "SECRET_AUDIO.wav"
        with wave.open(str(path), "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(16000)
            audio.writeframes(b"\x00" * 16000)
        return path

    def test_wav_duration_reads_metadata_without_decoding_samples_or_logging_path(self):
        path = self._wav()
        with performance.operation("cli"), \
                mock.patch.object(wave.Wave_read, "readframes", side_effect=AssertionError("must not decode")):
            self.assertEqual(performance.audio_duration(path), 0.5)
        self.assertEqual(self.events()[0]["audio_ms"], 500)
        self.assertNotIn("SECRET", json.dumps(self.events()))

    def test_missing_nonwav_placeholder_and_special_files_are_optional(self):
        text = self.root / "SECRET_TEXT"
        text.write_text("SECRET_DICTATION")
        placeholder = self._wav()
        data = bytearray(placeholder.read_bytes())
        data[40:44] = (0x80000000).to_bytes(4, "little")
        placeholder.write_bytes(data)
        fifo = self.root / "fifo"
        os.mkfifo(fifo)
        symlink = self.root / "symlink"
        symlink.symlink_to(text)
        with performance.operation("cli"):
            for path in (text, placeholder, fifo, symlink, self.root / "absent"):
                self.assertIsNone(performance.audio_duration(path), str(path))
        self.assertEqual(len(self.events()), 1)
        self.assertNotIn("SECRET", json.dumps(self.events()))

    def test_logger_or_system_metadata_failure_cannot_break_success_or_mask_error(self):
        error = ValueError("SECRET_ORIGINAL")
        with mock.patch.object(technical_log, "write_performance", side_effect=RuntimeError("SECRET_LOGGER")), \
                mock.patch.object(performance.os, "getloadavg", side_effect=OSError("unavailable")), \
                mock.patch.object(performance.os, "cpu_count", side_effect=RuntimeError("unavailable")):
            with performance.operation("cli"):
                with performance.stage("polish"):
                    performance.execution("text", "cpu", "unknown")
            with self.assertRaises(ValueError) as caught:
                with performance.operation("cli"):
                    with performance.stage("delivery"):
                        raise error
        self.assertIs(caught.exception, error)
        self.assertIsNone(performance.current_id())

    def test_broken_clock_does_not_mask_the_original_error(self):
        error = ValueError("SECRET_ORIGINAL")
        with mock.patch.object(performance.time, "monotonic", side_effect=OSError("clock")):
            with self.assertRaises(ValueError) as caught:
                with performance.operation("cli"):
                    with performance.stage("polish"):
                        raise error
        self.assertIs(caught.exception, error)
        self.assertIsNone(performance.current_id())
        self.assertEqual(self.events(), [])

    def test_threads_keep_distinct_contexts_and_parent_context_is_restored(self):
        barrier = threading.Barrier(3)
        observations = []
        events = []

        def worker(source):
            before = performance.current_id()
            with performance.operation(source) as identifier:
                performance.response_status(404 if source == "http" else 200)
                barrier.wait(timeout=3)
                observations.append((before, identifier, performance.current_id()))
                barrier.wait(timeout=3)

        with mock.patch.object(technical_log, "write_performance", side_effect=lambda kind, **fields: events.append((kind, fields))):
            with performance.operation("shortcut") as parent:
                performance.response_status(201)
                workers = [threading.Thread(target=worker, args=(source,)) for source in ("http", "preview")]
                for worker_thread in workers:
                    worker_thread.start()
                barrier.wait(timeout=3)
                self.assertEqual(performance.current_id(), parent)
                barrier.wait(timeout=3)
                for worker_thread in workers:
                    worker_thread.join(timeout=3)
                    self.assertFalse(worker_thread.is_alive())
        self.assertEqual(len(observations), 2)
        self.assertTrue(all(before is None and identifier == active for before, identifier, active in observations))
        self.assertEqual(len({identifier for _, identifier, _ in observations} | {parent}), 3)
        self.assertEqual(len(events), 3)
        totals = {fields["source"]: fields for kind, fields in events if kind == "total"}
        self.assertFalse(totals["http"]["success"])
        self.assertEqual(totals["http"]["http_status"], 404)
        self.assertTrue(totals["preview"]["success"])
        self.assertEqual(totals["preview"]["http_status"], 200)
        self.assertTrue(totals["shortcut"]["success"])
        self.assertEqual(totals["shortcut"]["http_status"], 201)
        self.assertIsNone(performance.current_id())

    def test_performance_shares_private_bounded_rotation_with_existing_events(self):
        original = os.umask(0)
        try:
            with mock.patch.object(technical_log, "MAX_BYTES", 1024):
                for _ in range(30):
                    technical_log.write_event("invoked")
                    with performance.operation("shortcut"):
                        with performance.stage("transcription"):
                            pass
        finally:
            os.umask(original)
        self.assertEqual({path.name for path in self.logs.iterdir()}, {"hotkey.jsonl", "hotkey.jsonl.1"})
        self.assertEqual(self.logs.stat().st_mode & 0o777, 0o700)
        for path in self.logs.iterdir():
            self.assertLessEqual(path.stat().st_size, 1024)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertTrue(self.events())


if __name__ == "__main__":
    unittest.main()
