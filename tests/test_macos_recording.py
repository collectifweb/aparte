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
    def test_shutdown_discards_a_live_recording_without_transcribing(self):
        self.controller.toggle()
        self.sd.streams[0].feed(16000)
        self.controller.shutdown()
        self.assertTrue(self.sd.streams[0].stopped and self.sd.streams[0].closed)
        self.assertEqual(self.controller.state, IDLE)
        self.assertEqual(self.transcribed, [])
        self.assertIsNone(self.controller._worker)


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


if __name__ == "__main__":
    unittest.main()
