"""macOS in-process recording — the resident server's toggle state machine.

On Linux the global shortcut spawns short-lived CLI recorders that coordinate
through a session file, ``os.link`` and ``/proc`` (:mod:`aparte.session`). That
only makes sense because a gsettings shortcut has no process of its own.

On macOS the global shortcut (M5) *needs* a resident process, and one already
exists: the desktop server, autostarted at login. So recording happens **in the
server's memory** — no subprocess, no PID, no session file, no ``/proc`` — through
this :class:`RecordingController`. It is less code than transposing
:mod:`aparte.session`, not more.

Native (PortAudio via ``sounddevice``), so it cannot run on the Linux dev machine:
the unit tests inject a fake ``sounddevice`` and a fake ``transcribe_fn`` and lock
the **observable** contract — the state transitions, the bounded real-time
callback, the post-capture order. The real capture is verified by hand on a Mac
(M8).

The controller is built with every dependency **injected** so it stays pure and
testable:

- ``transcribe_fn(wav) -> str`` — server-local **raw** transcription. The desktop
  wiring builds it to take the single ``inference_lock`` and reuse the one cached
  Whisper model, never a self-HTTP call. Polishing (French typography) happens in
  the worker, after transcription — not in this primitive.
- ``settings_provider() -> Settings`` — re-read each recording, so a config change
  (device, beep, cap, polish) takes effect without a restart.

Nothing here is triggered in M4: the shortcut that calls :meth:`toggle` is M5. In
M4 this is dormant infrastructure, proven by mocked tests, wired to a trigger in
M5 and read by the tray in M6.
"""

from __future__ import annotations

import tempfile
import threading
import time
import wave
from pathlib import Path
from typing import Callable

from .audio import RecordingError, play_beep
from .notify import notify

# The four observable states. The tray (M6) and doctor read the current one
# through the `state` provider; "error" is observable and clears on the next
# press, never a stuck state.
IDLE = "idle"
RECORDING = "recording"
PROCESSING = "processing"
ERROR = "error"

# Whisper wants 16 kHz mono; the recorder produces exactly that, like the Linux
# path. There is no per-invocation sample rate on the shortcut, so it is fixed.
_SAMPLE_RATE = 16000

# int16 mono — two bytes per frame, matching `setsampwidth(2)` below.
_BYTES_PER_FRAME = 2

# A double press a few milliseconds apart is one intent, not two: the second is
# swallowed so it can't immediately stop the recording the first just started.
_DEBOUNCE_SECONDS = 0.25

# Below this, there is nothing to transcribe — treat it as silence rather than
# feed Whisper a click. Same threshold as the Linux session recorder.
_MIN_TRANSCRIBABLE_SECONDS = 0.3


class _Capture:
    """One recording's own mutable state, owned by its stream's callback.

    Each capture gets a fresh capsule and a callback closed over it, so a late
    or leaked callback from a *previous* stream can only ever write into its own
    dead capsule — never into the live one. ``active`` is flipped false the moment
    a capture stops; the callback checks it first and becomes a no-op.
    """

    __slots__ = ("frames", "frame_count", "max_frames", "active", "truncated", "overflowed")

    def __init__(self, max_frames: int) -> None:
        self.frames: list[bytes] = []
        self.frame_count = 0
        self.max_frames = max_frames
        self.active = True
        self.truncated = False  # buffer cap hit — recording longer than the ceiling
        self.overflowed = False  # PortAudio reported an over/underflow


def _sounddevice():
    """Import sounddevice, or raise a RecordingError the notification shows as-is."""
    try:
        import sounddevice as sd
    except Exception as exc:  # ImportError, or a broken PortAudio install
        raise RecordingError(
            "macOS in-process recording needs the sounddevice package — install "
            "the macOS extras with: pip install '.[macos]'"
        ) from exc
    return sd


def _play_beep_safe(kind: str) -> None:
    # The audio cue is a nicety; a missing player must never break a recording.
    try:
        play_beep(kind)
    except Exception:
        pass


class RecordingController:
    """In-memory toggle state machine for the resident macOS server.

    Thread model: :meth:`toggle`, :meth:`shutdown` and the cap timer mutate state
    under ``_lock``. The PortAudio callback runs on the real-time audio thread and
    only appends to its own capture's bounded buffer. Transcription, polishing and
    insertion run on a **worker thread**, off both the lock and the audio thread,
    so the shortcut handler never blocks on the run loop.
    """

    def __init__(
        self,
        transcribe_fn: Callable[[Path], str],
        settings_provider: Callable[[], object],
        *,
        sample_rate: int = _SAMPLE_RATE,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._transcribe_fn = transcribe_fn
        self._settings_provider = settings_provider
        self._sample_rate = sample_rate
        self._clock = clock

        self._lock = threading.Lock()
        self._state = IDLE
        self._stream = None
        self._capture: _Capture | None = None
        self._timer: threading.Timer | None = None
        self._worker: threading.Thread | None = None
        self._last_toggle: float | None = None

    @property
    def state(self) -> str:
        """The current state, for the tray/doctor. A plain string read is atomic."""
        return self._state

    # -- Trigger surface (called in-process by the M5 shortcut) -----------------

    def toggle(self) -> None:
        """One press: start if idle, stop if recording, refuse if still processing."""
        with self._lock:
            now = self._clock()
            if self._last_toggle is not None and now - self._last_toggle < _DEBOUNCE_SECONDS:
                return
            self._last_toggle = now
            if self._state in (IDLE, ERROR):
                self._begin_locked()
            elif self._state == RECORDING:
                self._stop_locked()
            else:  # PROCESSING — a dictation is already being transcribed
                self._notify_busy()

    def shutdown(self) -> None:
        """Server closing: drop a live recording cleanly, no last-gasp transcription."""
        with self._lock:
            self._cancel_timer()
            if self._state == RECORDING:
                if self._capture is not None:
                    self._capture.active = False
                self._close_stream(self._stream)
                self._stream = None
                self._capture = None
                self._state = IDLE

    # -- Start ------------------------------------------------------------------

    def _begin_locked(self) -> None:
        try:
            self._start_locked()
        except Exception as exc:
            # A framework or a device that won't open must surface, not fake a
            # recording. Close a stream that already started (e.g. the cap timer
            # failed to arm) before dropping it, so nothing keeps capturing. The
            # next press starts fresh from ERROR.
            self._cancel_timer()
            self._close_stream(self._stream)
            self._stream = None
            self._capture = None
            self._state = ERROR
            self._notify_error(exc)

    def _start_locked(self) -> None:
        settings = self._settings_provider()
        sd = _sounddevice()
        max_frames = max(1, self._sample_rate * int(settings.max_recording_seconds))
        capture = _Capture(max_frames)

        def on_audio(indata, frames, time_info, status, _cap=capture) -> None:
            # PortAudio real-time thread: no disk I/O, no Whisper, no long lock, no
            # raise (a callback exception does not propagate as a normal one). It
            # writes only into its own capsule, and stops the instant the capsule is
            # deactivated — so a late or leaked callback can't touch a live capture.
            if not _cap.active:
                return
            if status:
                _cap.overflowed = True
            if _cap.frame_count >= _cap.max_frames:
                _cap.truncated = True
                return
            _cap.frames.append(bytes(indata))
            _cap.frame_count += frames

        stream = sd.RawInputStream(
            samplerate=self._sample_rate,
            channels=1,
            dtype="int16",
            device=settings.microphone or None,
            callback=on_audio,
        )
        # The opening tone must finish before the mic actually captures, or it ends
        # up in the recording (see audio.play_beep). Construction doesn't capture;
        # stream.start() does — so beep between the two.
        if settings.beep:
            _play_beep_safe("start")
        try:
            stream.start()
        except Exception:
            stream.close()
            raise
        self._stream = stream
        self._capture = capture
        self._state = RECORDING
        self._arm_cap_timer(settings.max_recording_seconds)

    # -- Stop / finalize --------------------------------------------------------

    def _stop_locked(self) -> None:
        self._cancel_timer()
        capture = self._capture
        if capture is not None:
            capture.active = False  # stale callbacks from this stream now no-op
        self._capture = None
        stream = self._stream
        self._stream = None
        self._state = PROCESSING
        # Never transcribe on the trigger thread: hand the capture to a worker. If
        # the worker can't even start (thread exhaustion), close the stream and go
        # to ERROR — never leave the state stuck on PROCESSING, which would refuse
        # every future press. Settings are read in the worker, not here, so nothing
        # between the state change and the worker can raise and strand us.
        try:
            self._worker = threading.Thread(
                target=self._finalize, args=(stream, capture), daemon=True
            )
            self._worker.start()
        except Exception as exc:
            self._close_stream(stream)
            self._state = ERROR
            self._notify_error(exc)

    def _finalize(self, stream, capture: _Capture | None) -> None:
        try:
            # Close first, so the device is freed even if reading settings raises.
            self._close_stream(stream)
            settings = self._settings_provider()
            if getattr(settings, "beep", False):
                _play_beep_safe("stop")
            frames = capture.frames if capture is not None else []
            if self._captured_seconds(frames) < _MIN_TRANSCRIBABLE_SECONDS:
                # Nothing to transcribe — feed the empty string through the shared
                # helper so "nothing heard" is announced in one place, and history
                # and the clipboard are left untouched.
                self._deliver("", settings)
                self._set_state(IDLE)
                return
            wav = self._write_wav(frames)
            try:
                raw = self._transcribe_fn(wav)
                output = self._polish(raw, settings)
                self._deliver(output, settings)
            finally:
                wav.unlink(missing_ok=True)
            self._set_state(IDLE)
        except Exception as exc:
            # The text, if any, is already in history and on the clipboard via
            # deliver_transcript; the state goes observable-error, not silent.
            self._set_state(ERROR)
            self._notify_error(exc)

    def _polish(self, transcript: str, settings) -> str:
        # Lazy import (cli → desktop → this module would cycle at load). The
        # in-process path must polish like the CLI, or the shortcut would deliver
        # raw text with no French typography — the one thing the app exists for.
        from .cli import polish_for_delivery

        return polish_for_delivery(transcript, settings)

    def _deliver(self, output: str, settings) -> None:
        # Lazy import for the same cycle reason. deliver_transcript is the single
        # home of the empty→nothing / history-before-insert / notify-after order,
        # shared with the CLI so the invariants can't drift on this path. One same
        # Settings snapshot polished and delivered, never two.
        from .cli import deliver_transcript

        deliver_transcript(output, "paste", settings)

    # -- Cap timer --------------------------------------------------------------

    def _arm_cap_timer(self, seconds) -> None:
        timer = threading.Timer(max(0.1, float(seconds)), self._stop_on_cap)
        timer.daemon = True
        self._timer = timer
        timer.start()

    def _stop_on_cap(self) -> None:
        with self._lock:
            if self._state == RECORDING:
                self._stop_locked()

    def _cancel_timer(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

    # -- Helpers ----------------------------------------------------------------

    @staticmethod
    def _close_stream(stream) -> None:
        # Best-effort: the frames are already captured in memory before we get
        # here, so a stop/close hiccup only fails to release the device — it must
        # never cost the recording. Safe because the capture's callback is already
        # deactivated, so a stream that refuses to close can't contaminate the next
        # capture. Both stop and close are attempted regardless.
        if stream is None:
            return
        try:
            stream.stop()
        except Exception:
            pass
        try:
            stream.close()
        except Exception:
            pass

    def _captured_seconds(self, frames: list[bytes]) -> float:
        nbytes = sum(len(chunk) for chunk in frames)
        return nbytes / (self._sample_rate * _BYTES_PER_FRAME)

    def _write_wav(self, frames: list[bytes]) -> Path:
        handle = tempfile.NamedTemporaryFile(prefix="aparte-", suffix=".wav", delete=False)
        path = Path(handle.name)
        handle.close()
        # The `wave` module fixes the header on a seekable file, so the SIGKILL
        # header trap that bites arecord on Linux does not apply here.
        with wave.open(str(path), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(_BYTES_PER_FRAME)
            wav.setframerate(self._sample_rate)
            wav.writeframes(b"".join(frames))
        return path

    def _set_state(self, state: str) -> None:
        with self._lock:
            self._state = state

    def _notify_busy(self) -> None:
        notify("🎙️ Déjà en cours", "Une dictée est déjà en traitement.", urgency="low")

    def _notify_error(self, exc: Exception) -> None:
        notify("⚠️ Dictée échouée", f"{exc} Rien n'a été inséré ; réessaie.", urgency="critical")
