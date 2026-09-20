import os
import tempfile
import threading
import sys
import types
import unittest
import wave
from pathlib import Path
from unittest import mock

from aparte import macos_recording
from aparte.macos_recording import ERROR, IDLE, PROCESSING, RECORDING, RecordingController


def _settings(**overrides):
    base = dict(max_recording_seconds=300, microphone=None, beep=False,
                history_persist=False, paste_mode="clipboard")
    base.update(overrides)
    return types.SimpleNamespace(**base)


class FakeRawInputStream:
    def __init__(self, *, samplerate, channels, dtype, device, callback):
        self.samplerate = samplerate
        self.channels = channels
        self.dtype = dtype
        self.device = device
        self.callback = callback
        self.started = False
        self.stopped = False
        self.closed = False
        self.start_error: Exception | None = None
        self.stop_error: Exception | None = None

    def start(self):
        if self.start_error is not None:
            raise self.start_error
        self.started = True

    def stop(self):
        self.stopped = True
        if self.stop_error is not None:
            raise self.stop_error

    def close(self):
        self.closed = True

    def feed(self, frames: int, status=0):
        """Drive the real-time callback by hand: `frames` int16 mono samples."""
        self.callback(b"\x01\x02" * frames, frames, None, status)


class FakeSounddevice:
    def __init__(self):
        self.streams: list[FakeRawInputStream] = []
        self.raw_error: Exception | None = None
        self.start_error: Exception | None = None
        self.stop_error: Exception | None = None

    def RawInputStream(self, **kwargs):
        if self.raw_error is not None:
            raise self.raw_error
        stream = FakeRawInputStream(**kwargs)
        stream.start_error = self.start_error
        stream.stop_error = self.stop_error
        self.streams.append(stream)
        return stream


class ControllerTestBase(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.runtime = Path(temporary.name)
        environment = mock.patch.dict(os.environ, {"APARTE_RUNTIME_DIR": str(self.runtime / "runtime"),
                                                   "APARTE_CONFIG": str(self.runtime / "config.json")})
        environment.start()
        self.addCleanup(environment.stop)
        self.sd = FakeSounddevice()
        self.now = 1000.0
        self.settings = _settings()
        self.transcribed: list[Path] = []

        def transcribe_fn(path):
            self.transcribed.append(path)
            return "bonjour le monde"

        self.controller = RecordingController(
            transcribe_fn,
            lambda: self.settings,
            sample_rate=16000,
            clock=lambda: self.now,
        )
        # Never let a lingering cap timer or open stream leak between tests.
        self.addCleanup(self.controller.shutdown)
        # No test may reach GTK: notify() and the shared deliver helper are stubbed
        # at the boundary. deliver_transcript keeps its real empty→False contract so
        # the worker's branches behave, but records instead of touching the clipboard.
        self.notify = mock.patch.object(macos_recording, "notify").start()
        mock.patch.object(macos_recording, "ensure_microphone_access").start()
        self.addCleanup(mock.patch.stopall)
        self.delivered: list[tuple] = []

        def deliver(output, target, settings):
            self.delivered.append((output, target, settings))
            return bool(output.strip())

        self.deliver = mock.patch("aparte.cli.deliver_transcript", side_effect=deliver).start()
        # The worker polishes before delivering. Stub the shared helper to an
        # identity so worker tests assert on the raw transcript; PolishTest overrides
        # the side effect to prove the polished output is what actually reaches
        # deliver. The real polish chain is exercised in test_cli.
        self.polish = mock.patch(
            "aparte.cli.polish_for_delivery", side_effect=lambda text, settings: text
        ).start()
        self._sd_patch = mock.patch.dict(sys.modules, {"sounddevice": self.sd})
        self._sd_patch.start()
        self.addCleanup(self._sd_patch.stop)

    def _run_worker(self):
        worker = self.controller._worker
        self.assertIsNotNone(worker)
        worker.join(timeout=2.0)
        self.assertFalse(worker.is_alive())

    def _record_and_stop(self, frames=16000):
        self.controller.toggle()
        self.sd.streams[0].feed(frames)
        self.now += 1.0
        self.controller.toggle()
        self._run_worker()


class StartStopTest(ControllerTestBase):
    def test_first_toggle_opens_and_starts_a_stream(self):
        self.controller.toggle()
        self.assertEqual(self.controller.state, RECORDING)
        self.assertEqual(len(self.sd.streams), 1)
        stream = self.sd.streams[0]
        self.assertTrue(stream.started)
        self.assertEqual(stream.samplerate, 16000)
        self.assertEqual(stream.channels, 1)
        self.assertEqual(stream.dtype, "int16")

    def test_toggle_stop_transcribes_then_delivers_then_idle(self):
        order = []
        self.controller._transcribe_fn = lambda p: order.append("transcribe") or "salut"
        self.deliver.side_effect = lambda *a: order.append("deliver")
        self._record_and_stop()
        self.assertEqual(order, ["transcribe", "deliver"])
        self.assertEqual(self.deliver.call_args.args[:2], ("salut", "paste"))
        stream = self.sd.streams[0]
        self.assertTrue(stream.stopped and stream.closed)
        self.assertEqual(self.controller.state, IDLE)

    def test_delivered_text_and_target_reach_the_shared_helper(self):
        self._record_and_stop()
        self.assertEqual(self.delivered, [("bonjour le monde", "paste", self.settings)])


class CallbackTest(ControllerTestBase):
    def test_buffer_is_bounded_at_the_frame_ceiling(self):
        self.controller.toggle()
        self.controller._cancel_timer()   # drop the real cap timer; drive the cap by hand
        capture = self.controller._capture
        capture.max_frames = 100
        stream = self.sd.streams[0]
        stream.feed(40)
        stream.feed(40)
        stream.feed(40)   # count 120 ≥ 100 on the next feed
        stream.feed(40)   # dropped
        self.assertEqual(len(capture.frames), 3)
        self.assertTrue(capture.truncated)
        self.assertEqual(capture.frame_count, 100)
        self.assertEqual(sum(map(len, capture.frames)), 200)

    def test_a_portaudio_status_is_recorded_as_overflow(self):
        self.controller.toggle()
        self.sd.streams[0].feed(10, status="input overflow")
        self.assertTrue(self.controller._capture.overflowed)


class ShortAndEmptyTest(ControllerTestBase):
    def test_a_too_short_capture_is_silence_not_a_transcription(self):
        self.controller.toggle()
        self.sd.streams[0].feed(100)  # ~0.006 s, below the 0.3 s floor
        self.now += 1.0
        self.controller.toggle()
        self._run_worker()
        # Routed through the shared helper as an empty string; Whisper is skipped.
        self.assertEqual(self.transcribed, [])
        self.assertEqual(self.delivered, [("", "paste", self.settings)])
        self.assertEqual(self.controller.state, IDLE)

    def test_an_empty_transcription_delegates_the_nothing_notice(self):
        # deliver_transcript owns the empty→nothing decision; the worker just calls it.
        self.controller._transcribe_fn = lambda p: "   "
        self._record_and_stop()
        self.deliver.assert_called_once()
        self.assertEqual(self.deliver.call_args.args[0], "   ")
        self.assertEqual(self.controller.state, IDLE)


class WorkerFailureTest(ControllerTestBase):
    def test_a_transcription_error_goes_to_observable_error_state(self):
        self.controller._transcribe_fn = lambda p: (_ for _ in ()).throw(RuntimeError("boom"))
        self._record_and_stop()
        self.assertEqual(self.controller.state, ERROR)
        self.assertEqual(self.notify.call_args.kwargs.get("urgency"), "critical")

    def test_a_stop_hiccup_never_costs_the_recording(self):
        self.sd.stop_error = RuntimeError("device busy")
        self._record_and_stop()
        # stop() raised, but the audio was already captured: it still transcribes.
        self.assertTrue(self.sd.streams[0].closed)
        self.deliver.assert_called_once()
        self.assertEqual(self.controller.state, IDLE)


class ConflictTest(ControllerTestBase):
    def test_a_rapid_second_press_is_debounced(self):
        self.controller.toggle()          # start at now=1000
        self.now += 0.1                   # within the 0.25 s window
        self.controller.toggle()          # swallowed, not a stop
        self.assertEqual(self.controller.state, RECORDING)
        self.assertFalse(self.sd.streams[0].stopped)
        self.assertEqual(len(self.sd.streams), 1)

    def test_a_press_while_processing_is_refused_not_queued(self):
        self.controller._state = PROCESSING
        self.now += 10.0  # well past the debounce window
        self.controller.toggle()
        self.notify.assert_called_once()
        self.assertEqual(self.controller.state, PROCESSING)
        self.assertEqual(self.sd.streams, [])

    def test_the_cap_timer_stops_a_forgotten_recording(self):
        self.controller.toggle()
        self.sd.streams[0].feed(16000)
        self.controller._stop_on_cap()  # what the timer would have called
        self._run_worker()
        self.assertTrue(self.sd.streams[0].stopped)
        self.assertEqual(self.controller.state, IDLE)


class ShutdownTest(ControllerTestBase):
    def test_shutdown_preserves_a_live_recording_without_transcribing(self):
        self.controller.toggle()
        self.sd.streams[0].feed(16000)
        self.controller.shutdown()
        self.assertTrue(self.sd.streams[0].stopped and self.sd.streams[0].closed)
        self.assertEqual(self.controller.state, IDLE)
        self.assertEqual(self.transcribed, [])
        self.assertIsNone(self.controller._worker)
        self.assertEqual(len(macos_recording.recovery.entries()), 1)


class MissingFrameworkTest(ControllerTestBase):
    def test_a_missing_sounddevice_is_observable_error_not_a_crash(self):
        with mock.patch.dict(sys.modules, {"sounddevice": None}):
            self.controller.toggle()
        self.assertEqual(self.controller.state, ERROR)
        self.assertEqual(self.notify.call_args.kwargs.get("urgency"), "critical")

    def test_a_stream_that_wont_start_is_closed_and_errors(self):
        self.sd.start_error = RuntimeError("no device")
        self.controller.toggle()
        self.assertTrue(self.sd.streams[0].closed)
        self.assertEqual(self.controller.state, ERROR)


class MicrophonePermissionTest(ControllerTestBase):
    """A refused microphone must stop the recording before it opens.

    PortAudio would open the stream anyway and capture silence — that is what a
    fresh Mac did in M8. The refusal has to happen *before* the stream, and be
    observable, rather than produce a recording of nothing.
    """

    def test_a_refused_microphone_never_opens_a_stream(self):
        with mock.patch.object(
            macos_recording, "ensure_microphone_access",
            side_effect=macos_recording.RecordingError("no mic"),
        ):
            self.controller.toggle()
        self.assertEqual(self.sd.streams, [])
        self.assertEqual(self.controller.state, ERROR)
        self.assertEqual(self.notify.call_args.kwargs.get("urgency"), "critical")

    def test_the_permission_is_settled_before_the_stream_is_built(self):
        order: list[str] = []
        with mock.patch.object(
            macos_recording, "ensure_microphone_access", side_effect=lambda: order.append("ask")
        ):
            with mock.patch.object(
                self.sd, "RawInputStream", side_effect=lambda **kw: order.append("stream")
            ):
                self.controller.toggle()
        self.assertEqual(order, ["ask", "stream"])


class WavTest(ControllerTestBase):
    def test_the_wav_is_16k_mono_16bit_and_holds_the_frames(self):
        path = self.controller._write_wav([b"\x01\x02", b"\x03\x04"])
        try:
            with wave.open(str(path), "rb") as wav:
                self.assertEqual(wav.getnchannels(), 1)
                self.assertEqual(wav.getsampwidth(), 2)
                self.assertEqual(wav.getframerate(), 16000)
                self.assertEqual(wav.readframes(wav.getnframes()), b"\x01\x02\x03\x04")
        finally:
            path.unlink(missing_ok=True)


class LateCallbackTest(ControllerTestBase):
    """A callback that fires after its capture stopped — or from a stream whose
    close() failed — must never write into a later capture."""

    def test_a_late_callback_from_the_old_stream_cannot_contaminate_the_next(self):
        self.sd.stop_error = RuntimeError("close hiccup")  # the old stream lingers
        self.controller.toggle()
        old = self.sd.streams[0]
        old.feed(16000)
        self.now += 1.0
        self.controller.toggle()   # stop: old capsule deactivated, worker runs
        self._run_worker()

        self.now += 1.0
        self.controller.toggle()   # a fresh capture, its own capsule + stream
        new_capture = self.controller._capture
        old.feed(16000)            # the lingering old stream fires again
        self.assertEqual(new_capture.frame_count, 0)  # not contaminated


class BeepOrderTest(ControllerTestBase):
    def test_the_start_beep_finishes_before_the_mic_captures(self):
        self.settings.beep = True
        started_at_beep = {}

        def beep(kind):
            if self.sd.streams:
                started_at_beep[kind] = self.sd.streams[-1].started

        with mock.patch.object(macos_recording, "play_beep", side_effect=beep):
            self.controller.toggle()
        # The opening tone played while the stream existed but had not started yet.
        self.assertIs(started_at_beep.get("start"), False)
        self.assertTrue(self.sd.streams[0].started)


class PolishTest(ControllerTestBase):
    def test_the_worker_polishes_the_transcript_before_delivering(self):
        self.controller._transcribe_fn = lambda p: "brut"
        self.polish.side_effect = lambda text, settings: text.upper()  # visible marker
        self._record_and_stop()
        self.polish.assert_called_once_with("brut", self.settings)
        # The polished text, not the raw one, is what gets delivered.
        self.assertEqual(self.delivered[-1][0], "BRUT")


class StopRobustnessTest(ControllerTestBase):
    def test_a_worker_that_wont_start_errors_instead_of_sticking_on_processing(self):
        self.controller.toggle()
        self.sd.streams[0].feed(16000)
        self.now += 1.0
        with mock.patch.object(
            macos_recording.threading, "Thread"
        ) as Thread:
            Thread.return_value.start.side_effect = RuntimeError("no threads")
            self.controller.toggle()  # stop
        self.assertEqual(self.controller.state, ERROR)
        self.assertTrue(self.sd.streams[0].closed)  # stream freed, not leaked
        self.assertEqual(self.notify.call_args.kwargs.get("urgency"), "critical")

    def test_a_cap_timer_that_wont_arm_closes_the_started_stream(self):
        with mock.patch.object(
            self.controller, "_arm_cap_timer", side_effect=RuntimeError("no timer")
        ):
            self.controller.toggle()
        self.assertEqual(self.controller.state, ERROR)
        self.assertTrue(self.sd.streams[0].closed)  # the started stream is not left open


class SnapshotTest(ControllerTestBase):
    """M6: what the menu-bar tray reads, four times a second, off the lock."""

    def test_idle_has_no_duration(self):
        self.assertEqual(self.controller.recording_snapshot(), (IDLE, None))

    def test_recording_reports_seconds_since_the_press(self):
        self.controller.toggle()
        self.now += 7.5
        self.assertEqual(self.controller.recording_snapshot(), (RECORDING, 7.5))

    def test_the_duration_is_dropped_the_moment_recording_ends(self):
        self.controller.toggle()
        self.now += 3.0
        self.controller.toggle()          # → processing
        self.assertEqual(self.controller.recording_snapshot(), (PROCESSING, None))
        self._run_worker()
        self.assertEqual(self.controller.recording_snapshot(), (IDLE, None))

    def test_a_failed_start_leaves_no_stale_duration_behind(self):
        # The error state must not carry the previous recording's clock: the next
        # press starts fresh, and the tray would otherwise show a running timer.
        self.controller.toggle()
        self.now += 4.0
        self.controller.toggle()
        self._run_worker()
        self.sd.raw_error = RuntimeError("no device")
        self.now += 1.0
        self.controller.toggle()
        self.assertEqual(self.controller.recording_snapshot(), (ERROR, None))

    def test_the_snapshot_never_waits_for_the_controller_lock(self):
        # The real freeze this guards: _start_locked holds the lock across the macOS
        # microphone dialog, up to 30 s. The tray polls from the main thread — a
        # locked read would freeze the menu bar for that whole window.
        self.controller.toggle()
        self.now += 2.0
        acquired = self.controller._lock.acquire()
        self.addCleanup(self.controller._lock.release)
        self.assertTrue(acquired)
        self.assertEqual(self.controller.recording_snapshot(), (RECORDING, 2.0))


class BoundedShutdownTest(ControllerTestBase):
    """M6: quitting must not hang the main thread behind a 30 s permission dialog."""

    def test_shutdown_gives_up_when_the_lock_never_comes(self):
        self.controller.toggle()
        self.controller._lock.acquire()   # stand in for a start blocked on TCC
        self.addCleanup(self.controller._lock.release)
        self.assertFalse(self.controller.shutdown(timeout=0.05))
        self.assertEqual(self.controller.state, RECORDING)  # untouched, not corrupted

    def test_shutdown_closes_an_empty_live_recording_when_it_gets_the_lock(self):
        self.controller.toggle()
        self.assertTrue(self.controller.shutdown(timeout=1.0))
        self.assertEqual(self.controller.recording_snapshot(), (IDLE, None))
        self.assertTrue(self.sd.streams[0].closed)

    def test_the_default_stays_blocking(self):
        # The server's own path is unchanged: no timeout, no give-up.
        self.controller.toggle()
        self.assertTrue(self.controller.shutdown())
        self.assertEqual(self.controller.state, IDLE)


class RecoverySafetyTest(ControllerTestBase):
    def test_transcription_failure_keeps_recoverable_audio(self):
        self.controller._transcribe_fn = mock.Mock(side_effect=RuntimeError("model failed"))
        self._record_and_stop()
        entries = macos_recording.recovery.entries()
        self.assertEqual(len(entries), 1)
        with macos_recording.recovery.claim(entries[0]["id"]) as item:
            with wave.open(str(item.audio_path)) as wav:
                self.assertEqual(wav.getnframes(), 16000)
            self.assertIsNone(item.raw_text)

    def test_capture_cannot_be_deleted_between_storage_and_transcription(self):
        reads = []
        def settings():
            reads.append(True)
            if len(reads) == 2:  # worker reads config after preserving its audio
                entries = macos_recording.recovery.entries()
                self.assertEqual(len(entries), 1)
                self.assertTrue(entries[0]["busy"])
                with self.assertRaises(macos_recording.recovery.RecoveryBusy):
                    macos_recording.recovery.discard(entries[0]["id"])
            return self.settings
        self.controller._settings_provider = settings
        self._record_and_stop()
        self.assertEqual(len(reads), 2)
        self.assertEqual(self.controller.state, IDLE)
        self.assertEqual(len(self.delivered), 1)

    def test_failed_initial_backup_keeps_capsule_until_storage_recovers(self):
        with mock.patch.object(macos_recording.recovery.shutil, "copyfileobj", side_effect=OSError("disk full")):
            self._record_and_stop()
        self.assertEqual(self.controller.state, ERROR)
        self.assertIsNotNone(self.controller._unsaved_capture)
        self.assertEqual(self.transcribed, [])
        self.assertTrue(self.controller.shutdown(timeout=.1))
        self.assertEqual(len(macos_recording.recovery.entries()), 1)

    def test_polish_failure_keeps_raw_text(self):
        self.polish.side_effect = RuntimeError("polish failed")
        self._record_and_stop()
        entry = macos_recording.recovery.entries()[0]
        with macos_recording.recovery.claim(entry["id"]) as item:
            self.assertEqual(item.raw_text, "bonjour le monde")
        self.deliver.assert_not_called()

    def test_success_removes_private_backup(self):
        self._record_and_stop()
        self.assertEqual(macos_recording.recovery.entries(), [])

    def test_shutdown_during_blocked_inference_preserves_and_suppresses_late_paste(self):
        entered, release = threading.Event(), threading.Event()
        def transcribe(path):
            entered.set()
            release.wait(3)
            return "late text"
        self.controller._transcribe_fn = transcribe
        self.controller.toggle()
        self.sd.streams[0].feed(16000)
        self.now += 1
        self.controller.toggle()
        self.assertTrue(entered.wait(2))
        try:
            self.assertTrue(self.controller.shutdown(timeout=.1))
            self.assertTrue(self.controller._worker.is_alive())
            self.assertEqual(len(macos_recording.recovery.entries()), 1)
        finally:
            release.set()
            self._run_worker()
        self.deliver.assert_not_called()
        self.assertEqual(len(macos_recording.recovery.entries()), 1)

    def test_disk_failure_keeps_memory_and_refuses_quit_until_saved(self):
        self.controller.toggle()
        self.sd.streams[0].feed(16000)
        with mock.patch.object(self.controller, "_write_wav", side_effect=OSError("disk full")):
            self.assertFalse(self.controller.shutdown(timeout=.1))
            self.assertIsNotNone(self.controller._unsaved_capture)
        self.assertTrue(self.controller.shutdown(timeout=.1))
        self.assertEqual(len(macos_recording.recovery.entries()), 1)

    def test_overflow_is_visible_after_success(self):
        self.controller.toggle()
        self.sd.streams[0].feed(16000, status="overflow")
        self.now += 1
        self.controller.toggle()
        self._run_worker()
        self.assertEqual(self.controller.warning, "overflow")
        self.assertEqual(self.notify.call_args.kwargs["urgency"], "normal")

    def test_model_preparation_blocks_before_microphone_permission(self):
        self.controller._recording_allowed = mock.Mock(return_value=False)
        with mock.patch.object(macos_recording, "ensure_microphone_access") as permission:
            self.controller.toggle()
        permission.assert_not_called()
        self.assertEqual(self.sd.streams, [])


if __name__ == "__main__":
    unittest.main()
