import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import contextmanager
from unittest import mock

from aparte import lifecycle, recovery, session
from test_session import DEAD_PID, _recorder_in_proc, _wav_with_placeholder_header


class LifecycleTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.env = mock.patch.dict(os.environ, {"APARTE_RUNTIME_DIR": str(self.root)})
        self.env.start()
        self.addCleanup(self.env.stop)

    def capture(self, pid=DEAD_PID):
        audio = self.root / "toggle-test.wav"
        _wav_with_placeholder_header(audio, 32000)
        capture = session.RecordingSession(pid, audio, 16000, time.time())
        session._claim_session(capture)
        return capture

    @contextmanager
    def locked_transition_in_child(self, duration):
        code = ("from aparte.session import toggle_session_transition; import time;\n"
                "with toggle_session_transition():\n print('ready', flush=True)\n"
                f" time.sleep({duration!r})")
        process = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE,
                                   stderr=subprocess.DEVNULL, text=True)
        try:
            self.assertEqual(process.stdout.readline().strip(), "ready")
            yield process
        finally:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=5)
            process.stdout.close()

    def test_processing_can_wait_for_another_process_to_finish_its_transition(self):
        with self.locked_transition_in_child(0.12):
            started = time.monotonic()
            with lifecycle.processing_dictation(wait=1):
                self.assertTrue(lifecycle.is_processing())
                self.assertGreaterEqual(time.monotonic() - started, 0.08)
        self.assertFalse(lifecycle.is_processing())

    def test_processing_wait_has_a_deadline_and_does_not_publish_a_marker(self):
        with self.locked_transition_in_child(10):
            started = time.monotonic()
            with self.assertRaises(session.ToggleSessionError):
                with lifecycle.processing_dictation(wait=0.08):
                    self.fail("must not enter while locked")
            elapsed = time.monotonic() - started
            self.assertGreaterEqual(elapsed, 0.07)
            self.assertLess(elapsed, 0.8)
        self.assertFalse(list(self.root.glob("processing-*.lock")))

    def test_processing_remains_nonblocking_by_default(self):
        with self.locked_transition_in_child(10):
            with mock.patch.object(lifecycle.time, "sleep") as sleep:
                with self.assertRaises(session.ToggleSessionError):
                    with lifecycle.processing_dictation():
                        self.fail("must not enter while locked")
                sleep.assert_not_called()

    def test_processing_does_not_retry_storage_failure_or_body_exception(self):
        with mock.patch.object(lifecycle.time, "sleep") as sleep:
            with mock.patch.object(session, "get_runtime_dir", side_effect=session.ToggleSessionError("unavailable")):
                with self.assertRaises(session.ToggleSessionError):
                    with lifecycle.processing_dictation(wait=1):
                        self.fail("must not enter without runtime")
            with self.assertRaises(session.ToggleSessionError):
                with lifecycle.processing_dictation(wait=1):
                    raise session.ToggleSessionError("processing failed")
            sleep.assert_not_called()

    def test_fifo_marker_does_not_block_inspection(self):
        fifo = self.root / "processing-corrupt.lock"
        os.mkfifo(fifo, 0o600)
        result = subprocess.run([sys.executable, "-c",
                                 "from aparte.lifecycle import is_processing; assert not is_processing()"],
                                check=False, timeout=2)
        self.assertEqual(result.returncode, 0)
        self.assertTrue(fifo.exists())

    def test_hardlinked_marker_is_not_locked_or_deleted(self):
        source = self.root / "unrelated"
        source.write_text("other data")
        marker = self.root / "processing-linked.lock"
        os.link(source, marker)
        self.assertFalse(lifecycle.is_processing())
        self.assertEqual(marker.read_text(), "other data")

    def test_idle_and_finished_capture_do_not_report_an_open_microphone(self):
        self.assertEqual(lifecycle.get_dictation_state(), "idle")
        capture = self.capture()
        self.assertEqual(lifecycle.get_dictation_state(), "recoverable")
        self.assertEqual(session.get_active_session(), capture)

    def test_live_process_changes_to_recoverable_after_actual_exit(self):
        audio = self.root / "toggle-test.wav"
        with _recorder_in_proc(audio) as process:
            self.capture(process.pid)
            self.assertEqual(lifecycle.get_dictation_state(), "recording")
            process.terminate()
            process.wait(timeout=5)
            self.assertEqual(lifecycle.get_dictation_state(), "recoverable")

    def test_processing_marker_holds_flock_in_same_process_and_contains_nothing(self):
        with lifecycle.processing_dictation():
            self.assertTrue(lifecycle.is_processing())
            self.assertEqual(lifecycle.get_dictation_state(), "processing")
            paths = list(self.root.glob("processing-*.lock"))
            self.assertEqual(len(paths), 1)
            self.assertEqual(paths[0].read_bytes(), b"")
            self.assertEqual(paths[0].stat().st_mode & 0o777, 0o600)
        self.assertFalse(lifecycle.is_processing())
        self.assertEqual(list(self.root.glob("processing-*.lock")), [])

    def test_multiple_processing_operations_remain_visible_until_last_exits(self):
        with lifecycle.processing_dictation():
            with lifecycle.processing_dictation():
                self.assertTrue(lifecycle.is_processing())
            self.assertTrue(lifecycle.is_processing())
        self.assertFalse(lifecycle.is_processing())

    def test_crashed_worker_does_not_leave_processing_stuck(self):
        code = "from aparte.lifecycle import processing_dictation; import time;\nwith processing_dictation():\n print('ready', flush=True)\n time.sleep(60)"
        process = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE,
                                   stderr=subprocess.DEVNULL, text=True)
        try:
            self.assertEqual(process.stdout.readline().strip(), "ready")
            self.assertTrue(lifecycle.is_processing())
            process.kill()
            process.wait(timeout=5)
            self.assertFalse(lifecycle.is_processing())
            self.assertFalse(list(self.root.glob("processing-*.lock")))
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
            process.stdout.close()

    def test_quit_stops_actual_process_and_saves_capture_without_transcription(self):
        audio = self.root / "toggle-test.wav"
        with _recorder_in_proc(audio) as process:
            self.capture(process.pid)
            with lifecycle.prepare_shutdown() as identifier:
                self.assertIsNotNone(identifier)
                self.assertIsNotNone(process.poll())
                self.assertFalse(session.get_session_path().exists())
                self.assertFalse(audio.exists())
                with recovery.claim(identifier) as item:
                    self.assertGreater(item.audio_path.stat().st_size, 32000)
                    self.assertEqual(item.expires_at - item.created_at, 3600)
            self.assertEqual(lifecycle.get_dictation_state(), "recoverable")

    def test_quit_saves_already_stopped_capture(self):
        self.capture()
        with lifecycle.prepare_shutdown() as identifier:
            self.assertIsNotNone(identifier)
        self.assertEqual(len(recovery.entries()), 1)

    def test_quit_refused_during_processing(self):
        with lifecycle.processing_dictation():
            with self.assertRaises(lifecycle.ShutdownError) as caught:
                with lifecycle.prepare_shutdown():
                    self.fail("must not shut down")
            self.assertEqual(caught.exception.reason, "processing")

    def test_unconfirmed_stop_keeps_original_session_and_refuses_quit(self):
        capture = self.capture()
        with mock.patch.object(session, "stop_toggle_recording", side_effect=session.ToggleSessionError("still running")):
            with self.assertRaises(lifecycle.ShutdownError) as caught:
                with lifecycle.prepare_shutdown():
                    self.fail("must not shut down")
        self.assertEqual(caught.exception.reason, "stop")
        self.assertEqual(session.get_active_session(), capture)
        self.assertTrue(capture.audio_path.exists())
        self.assertFalse(recovery.entries())

    def test_failed_recovery_save_keeps_original_and_session_retriable(self):
        capture = self.capture()
        with mock.patch.object(recovery, "save_failure", side_effect=OSError("disk full")):
            with self.assertRaises(lifecycle.ShutdownError) as caught:
                with lifecycle.prepare_shutdown():
                    self.fail("must not shut down")
        self.assertEqual(caught.exception.reason, "save")
        self.assertEqual(session.get_active_session(), capture)
        self.assertTrue(capture.audio_path.exists())
        self.assertEqual(session.stop_toggle_recording(), capture)

    def test_metadata_cleanup_failure_after_save_still_quits_with_recovery(self):
        capture = self.capture()
        original_unlink = Path.unlink

        def unlink(path, *args, **kwargs):
            if path.name == "toggle-session.json":
                raise PermissionError("metadata cleanup unavailable")
            return original_unlink(path, *args, **kwargs)

        with mock.patch.object(Path, "unlink", unlink):
            with lifecycle.prepare_shutdown() as identifier:
                self.assertIsNotNone(identifier)
        self.assertFalse(capture.audio_path.exists())
        self.assertEqual(len(recovery.entries()), 1)
        self.assertEqual(lifecycle.get_dictation_state(), "recoverable")

    def test_audio_cleanup_failure_keeps_original_retriable_and_refuses_quit(self):
        capture = self.capture()
        original_unlink = Path.unlink

        def unlink(path, *args, **kwargs):
            if path == capture.audio_path:
                raise PermissionError("audio cleanup unavailable")
            return original_unlink(path, *args, **kwargs)

        with mock.patch.object(Path, "unlink", unlink):
            with self.assertRaises(lifecycle.ShutdownError) as caught:
                with lifecycle.prepare_shutdown():
                    self.fail("must not shut down")
        self.assertEqual(caught.exception.reason, "save")
        self.assertEqual(session.get_active_session(), capture)
        self.assertTrue(capture.audio_path.exists())
        self.assertEqual(len(recovery.entries()), 1)

    def test_shutdown_keeps_transition_locked_until_callback_returns(self):
        code = ("from aparte.session import toggle_session_transition, ToggleSessionError;\n"
                "try:\n with toggle_session_transition(): pass\n"
                "except ToggleSessionError: raise SystemExit(17)")
        with lifecycle.prepare_shutdown():
            result = subprocess.run([sys.executable, "-c", code], check=False)
            self.assertEqual(result.returncode, 17)
        self.assertEqual(subprocess.run([sys.executable, "-c", code], check=False).returncode, 0)

    def test_storage_failure_is_not_reported_as_idle(self):
        with mock.patch.object(session, "get_runtime_dir", side_effect=session.ToggleSessionError("unavailable")):
            with self.assertRaises(session.ToggleSessionError):
                lifecycle.get_dictation_state()


if __name__ == "__main__":
    unittest.main()
