import json
import os
import struct
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

from aparte import session

# Un PID qu'aucun noyau n'a attribué.
DEAD_PID = 999999999


@contextmanager
def _started_recorder(directory: str, pid: int = 4242, alive: bool = True):
    """Un démarrage de dictée où arecord est simulé, pas lancé.

    `_recorder_alive` lit `/proc`, donc un `Popen` simulé n'y survivrait pas :
    le contrôle de vivacité rejetterait un enregistrement parfaitement sain.
    """
    with mock.patch.dict(os.environ, {"APARTE_RUNTIME_DIR": directory}):
        with mock.patch.object(session.shutil, "which", return_value="/usr/bin/arecord"):
            with mock.patch.object(session, "_recorder_alive", return_value=alive):
                with mock.patch.object(session.subprocess, "Popen") as popen:
                    popen.return_value.pid = pid
                    yield popen


def _wav_with_placeholder_header(path: Path, payload_bytes: int, sample_rate: int = 16000) -> None:
    """Le WAV que laisse un arecord tué avant d'avoir pu finaliser son en-tête.

    Les tailles annoncées sont celles du plafond de 2 Gio, pas celles du son
    réellement capté.
    """
    header = b"RIFF" + struct.pack("<I", 0xFFFFFFFF) + b"WAVE"
    header += b"fmt " + struct.pack("<IHHIIHH", 16, 1, 1, sample_rate, sample_rate * 2, 2, 16)
    header += b"data" + struct.pack("<I", 0x80000000)
    path.write_bytes(header + b"\x00" * payload_bytes)


class StartRecordingTest(unittest.TestCase):
    def test_the_chosen_microphone_reaches_arecord(self):
        with tempfile.TemporaryDirectory() as directory:
            with _started_recorder(directory) as popen:
                session.start_toggle_recording(16000, "plughw:CARD=Mini,DEV=0")
            command = popen.call_args.args[0]
        self.assertEqual(command[command.index("-D") + 1], "plughw:CARD=Mini,DEV=0")

    def test_no_microphone_chosen_leaves_the_command_untouched(self):
        with tempfile.TemporaryDirectory() as directory:
            with _started_recorder(directory) as popen:
                session.start_toggle_recording()
            command = popen.call_args.args[0]
        self.assertNotIn("-D", command)

    def test_the_ceiling_reaches_arecord(self):
        with tempfile.TemporaryDirectory() as directory:
            with _started_recorder(directory) as popen:
                session.start_toggle_recording(16000, None, 900)
            command = popen.call_args.args[0]
        self.assertEqual(command[command.index("-d") + 1], "900")

    def test_a_lost_race_stops_its_own_recorder_instead_of_orphaning_it(self):
        """Le perdant nettoie derrière lui.

        Abandonner son arecord, c'est l'enregistrement de 31 minutes que plus
        aucune session ne référençait et que plus aucun appui ne pouvait arrêter.
        """
        with tempfile.TemporaryDirectory() as directory:
            with _started_recorder(directory) as popen:
                with mock.patch.object(session, "_claim_session", return_value=False):
                    with mock.patch.object(session, "_stop_recorder") as stop:
                        with self.assertRaises(session.ToggleSessionError):
                            session.start_toggle_recording()
            command = popen.call_args.args[0]
            audio_path = Path(command[-1])
        stop.assert_called_once()
        self.assertEqual(stop.call_args.args[0].pid, 4242)
        self.assertFalse(audio_path.exists())

    def test_winning_the_race_with_a_dead_recorder_is_reported(self):
        """arecord jette son refus sur une sortie qu'on ignore : micro occupé,
        démarrage annoncé, et rien qui enregistre."""
        with tempfile.TemporaryDirectory() as directory:
            with _started_recorder(directory, alive=False) as popen:
                with self.assertRaises(session.RecordingError):
                    session.start_toggle_recording()
                state = session.get_session_path()
                audio_path = Path(popen.call_args.args[0][-1])
                self.assertFalse(state.exists())
                self.assertFalse(audio_path.exists())

    def test_old_temporaries_are_swept_but_fresh_ones_are_left_alone(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "toggle-session.json"
            stale = state.with_name(f"{state.name}.111.tmp")
            fresh = state.with_name(f"{state.name}.222.tmp")
            stale.write_text("{}", encoding="utf-8")
            fresh.write_text("{}", encoding="utf-8")
            os.utime(stale, (0, 0))
            with _started_recorder(directory):
                session.start_toggle_recording()
            self.assertFalse(stale.exists())
            self.assertTrue(fresh.exists())


class ClaimSessionTest(unittest.TestCase):
    def _session(self, directory: str) -> session.RecordingSession:
        return session.RecordingSession(
            pid=4242,
            audio_path=Path(directory) / "toggle.wav",
            sample_rate=16000,
            started_at=1.0,
        )

    def test_only_one_claim_wins(self):
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.dict(os.environ, {"APARTE_RUNTIME_DIR": directory}):
                first = self._session(directory)
                second = session.RecordingSession(
                    pid=4243, audio_path=first.audio_path, sample_rate=16000, started_at=2.0
                )
                self.assertTrue(session._claim_session(first))
                self.assertFalse(session._claim_session(second))
                written = json.loads(session.get_session_path().read_text(encoding="utf-8"))
        self.assertEqual(written["pid"], 4242)

    def test_a_claim_leaves_no_temporary_behind(self):
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.dict(os.environ, {"APARTE_RUNTIME_DIR": directory}):
                session._claim_session(self._session(directory))
                leftovers = list(Path(directory).glob("toggle-session.json.*.tmp"))
        self.assertEqual(leftovers, [])


class RecorderAliveTest(unittest.TestCase):
    def test_a_live_stranger_is_not_our_recorder(self):
        """Un PID recyclé répond à `os.kill(pid, 0)`. Signaler son groupe
        enverrait un SIGINT à un processus qui n'a rien demandé."""
        stranger = session.RecordingSession(
            pid=os.getpid(),
            audio_path=Path("/tmp/never-recorded.wav"),
            sample_rate=16000,
            started_at=1.0,
        )
        self.assertFalse(session._recorder_alive(stranger))

    def test_a_dead_pid_is_not_alive(self):
        gone = session.RecordingSession(
            pid=DEAD_PID,
            audio_path=Path("/tmp/never-recorded.wav"),
            sample_rate=16000,
            started_at=1.0,
        )
        self.assertFalse(session._recorder_alive(gone))


class CapturedSecondsTest(unittest.TestCase):
    def test_the_duration_comes_from_the_file_size_not_the_header(self):
        """L'en-tête d'un arecord tué annonce 67 108 s pour quelques secondes.

        Ce test verrouille la décision : revenir à `wave.open()` le fait tomber.
        """
        with tempfile.TemporaryDirectory() as directory:
            audio_path = Path(directory) / "toggle.wav"
            _wav_with_placeholder_header(audio_path, payload_bytes=32000)
            recording = session.RecordingSession(
                pid=DEAD_PID, audio_path=audio_path, sample_rate=16000, started_at=1.0
            )
            self.assertAlmostEqual(session._captured_seconds(recording), 1.0, places=3)

            import wave

            with wave.open(str(audio_path)) as handle:
                header_seconds = handle.getnframes() / handle.getframerate()
        self.assertGreater(header_seconds, 60000)

    def test_a_missing_file_captured_nothing(self):
        recording = session.RecordingSession(
            pid=DEAD_PID,
            audio_path=Path("/tmp/never-recorded.wav"),
            sample_rate=16000,
            started_at=1.0,
        )
        self.assertEqual(session._captured_seconds(recording), 0.0)


class FinishedSessionTest(unittest.TestCase):
    def _write_session(self, directory: str, audio_path: Path) -> Path:
        state = Path(directory) / "toggle-session.json"
        state.write_text(
            json.dumps(
                {
                    "pid": DEAD_PID,
                    "audio_path": str(audio_path),
                    "sample_rate": 16000,
                    "started_at": 1.0,
                }
            ),
            encoding="utf-8",
        )
        return state

    def test_a_recording_that_ended_on_its_own_stays_transcribable(self):
        """Plafond atteint : l'appui suivant doit rendre le texte, pas le perdre."""
        with tempfile.TemporaryDirectory() as directory:
            audio_path = Path(directory) / "toggle.wav"
            _wav_with_placeholder_header(audio_path, payload_bytes=32000)
            state = self._write_session(directory, audio_path)
            with mock.patch.dict(os.environ, {"APARTE_RUNTIME_DIR": directory}):
                active = session.get_active_session()
            self.assertIsNotNone(active)
            self.assertTrue(audio_path.exists())
            self.assertTrue(state.exists())

    def test_the_crumbs_of_a_failed_start_are_swept(self):
        with tempfile.TemporaryDirectory() as directory:
            audio_path = Path(directory) / "toggle.wav"
            _wav_with_placeholder_header(audio_path, payload_bytes=1600)  # 0,05 s
            state = self._write_session(directory, audio_path)
            with mock.patch.dict(os.environ, {"APARTE_RUNTIME_DIR": directory}):
                self.assertIsNone(session.get_active_session())
            self.assertFalse(audio_path.exists())
            self.assertFalse(state.exists())

    def test_stopping_a_finished_session_signals_nobody(self):
        with tempfile.TemporaryDirectory() as directory:
            audio_path = Path(directory) / "toggle.wav"
            _wav_with_placeholder_header(audio_path, payload_bytes=32000)
            self._write_session(directory, audio_path)
            with mock.patch.dict(os.environ, {"APARTE_RUNTIME_DIR": directory}):
                with mock.patch.object(session.os, "killpg") as killpg:
                    stopped = session.stop_toggle_recording()
        killpg.assert_not_called()
        self.assertEqual(stopped.audio_path, audio_path)


class ToggleSessionTest(unittest.TestCase):
    def test_runtime_dir_can_be_overridden(self):
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.dict(os.environ, {"APARTE_RUNTIME_DIR": directory}):
                self.assertEqual(session.get_runtime_dir(), Path(directory))

    def test_stale_session_is_cleared(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "toggle-session.json"
            state.write_text(
                '{"pid": 999999999, "audio_path": "/tmp/missing.wav", "sample_rate": 16000, "started_at": 1}',
                encoding="utf-8",
            )
            with mock.patch.dict(os.environ, {"APARTE_RUNTIME_DIR": directory}):
                self.assertIsNone(session.get_active_session())
                self.assertFalse(state.exists())

    def test_runtime_dir_falls_back_when_xdg_runtime_is_not_writable(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            read_only = Path(temp_dir) / "readonly"
            read_only.mkdir()
            read_only.chmod(0o500)
            try:
                with mock.patch.dict(
                    os.environ,
                    {"XDG_RUNTIME_DIR": str(read_only), "TMPDIR": temp_dir},
                    clear=False,
                ):
                    with mock.patch("tempfile.gettempdir", return_value=temp_dir):
                        self.assertEqual(session.get_runtime_dir(), Path(temp_dir) / f"aparte-{os.getuid()}")
            finally:
                read_only.chmod(0o700)


if __name__ == "__main__":
    unittest.main()
