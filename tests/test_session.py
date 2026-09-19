import json
import os
import struct
import subprocess
import sys
import tempfile
import time
import threading
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
                # Aucun arecord simulé n'écrit d'échantillon : sans ce délai à zéro,
                # chaque test attendrait la confirmation de capture jusqu'au bout.
                with mock.patch.object(session, "_START_CONFIRMATION_SECONDS", 0.0):
                    with mock.patch.object(session.subprocess, "Popen") as popen:
                        popen.return_value.pid = pid
                        popen.return_value.returncode = 1
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

    def test_a_recorder_that_dies_moments_after_exec_is_reported(self):
        """Le cas qui coûtait une dictée entière.

        `Popen` rend la main dès l'exec — 0,001 s — alors qu'un micro déjà tenu par
        une autre application ne fait sortir arecord qu'à 0,05 s. Contrôler la
        vivacité tout de suite le voyait vivant, donc annonçait « Dictée en cours »
        à un enregistreur mort ; l'appui censé arrêter ne trouvait plus de session
        et rouvrait le micro pour un enregistrement entier, que plus rien
        n'arrêtait.
        """
        with tempfile.TemporaryDirectory() as directory:
            with _started_recorder(directory) as popen:
                with mock.patch.object(session, "_START_CONFIRMATION_SECONDS", 0.1):
                    with mock.patch.object(
                        session, "_recorder_alive", side_effect=[True, False, False]
                    ):
                        with self.assertRaises(session.RecordingError):
                            session.start_toggle_recording()
                self.assertFalse(session.get_session_path().exists())
                self.assertFalse(Path(popen.call_args.args[0][-1]).exists())

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


@contextmanager
def _recorder_in_proc(audio_path: Path):
    """Un processus qui ressemble à notre arecord dans `/proc`, sans ouvrir de micro.

    La détection ne lit que la ligne de commande : « arecord » et le chemin de la
    capture suffisent. Un vrai processus, donc un vrai `/proc` et un vrai signal —
    simuler l'un ou l'autre laisserait le ramassage sans preuve.
    """
    process = subprocess.Popen(
        ["arecord", "-c", "import time; time.sleep(60)", str(audio_path)],
        executable=sys.executable,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        yield process
    finally:
        process.kill()
        process.wait(timeout=5)


def _toggle_name(directory: str, age_seconds: float) -> Path:
    """Le nom d'une capture, dont l'horodatage porte l'âge que le test veut."""
    return Path(directory) / f"toggle-{int((time.time() - age_seconds) * 1000)}.wav"


class ForgottenRecorderTest(unittest.TestCase):
    """Le résidu qui bloquait le micro cinq minutes.

    Quatre fois en quatre jours, un `arecord` est resté vivant sans session. Le
    micro étant ouvert en accès exclusif, chaque appui suivant échouait en
    accusant « une autre application » — alors que l'application, c'était Aparté.
    """

    def test_a_recorder_no_session_follows_is_reaped_before_starting(self):
        with tempfile.TemporaryDirectory() as directory:
            audio_path = _toggle_name(directory, age_seconds=120)
            with _recorder_in_proc(audio_path) as process:
                with mock.patch.dict(os.environ, {"APARTE_RUNTIME_DIR": directory}):
                    self.assertEqual(session._reap_forgotten_recorders(), 1)
                self.assertIsNotNone(process.poll())

    def test_a_recorder_younger_than_the_grace_delay_is_left_alone(self):
        """Un appui concurrent peut être en train de publier sa session : son
        enregistreur a quelques dixièmes de seconde et n'est pas un oubli."""
        with tempfile.TemporaryDirectory() as directory:
            audio_path = _toggle_name(directory, age_seconds=0)
            with _recorder_in_proc(audio_path) as process:
                with mock.patch.dict(os.environ, {"APARTE_RUNTIME_DIR": directory}):
                    self.assertEqual(session._reap_forgotten_recorders(), 0)
                self.assertIsNone(process.poll())

    def test_a_recorder_writing_somewhere_else_is_never_touched(self):
        """Le seul signe qu'un enregistreur est le nôtre est le dossier où il
        écrit. Sans ce filtre, on enverrait un SIGINT à l'arecord de n'importe qui."""
        with tempfile.TemporaryDirectory() as directory:
            with tempfile.TemporaryDirectory() as elsewhere:
                audio_path = _toggle_name(elsewhere, age_seconds=120)
                with _recorder_in_proc(audio_path) as process:
                    with mock.patch.dict(os.environ, {"APARTE_RUNTIME_DIR": directory}):
                        self.assertEqual(session._reap_forgotten_recorders(), 0)
                    self.assertIsNone(process.poll())

    def test_an_active_session_is_never_reaped(self):
        """Le ramassage ne s'exécute que faute de session : une dictée en cours
        passe par `stop_toggle_recording`, jamais par un démarrage."""
        with tempfile.TemporaryDirectory() as directory:
            audio_path = _toggle_name(directory, age_seconds=120)
            _wav_with_placeholder_header(audio_path, payload_bytes=32000)
            state = Path(directory) / "toggle-session.json"
            state.write_text(
                json.dumps(
                    {
                        "pid": 4242,
                        "audio_path": str(audio_path),
                        "sample_rate": 16000,
                        "started_at": time.time(),
                    }
                ),
                encoding="utf-8",
            )
            with mock.patch.dict(os.environ, {"APARTE_RUNTIME_DIR": directory}):
                with mock.patch.object(session, "_recorder_alive", return_value=True):
                    with mock.patch.object(session, "_reap_forgotten_recorders") as reap:
                        with self.assertRaises(session.ToggleSessionError):
                            session.start_toggle_recording()
            reap.assert_not_called()

    def test_the_failure_names_us_when_we_just_closed_our_own_recorder(self):
        """Accuser un tiers juste après avoir fermé son propre résidu envoie
        chercher la panne à l'endroit où elle n'est pas."""
        with tempfile.TemporaryDirectory() as directory:
            with _started_recorder(directory, alive=False):
                with mock.patch.object(session, "_reap_forgotten_recorders", return_value=1):
                    with self.assertRaises(session.RecordingError) as raised:
                        session.start_toggle_recording()
        self.assertIn('"closed_recorders": 1', str(raised.exception))
        self.assertNotIn("occupé", str(raised.exception))

    def test_the_failure_does_not_blame_a_third_party_without_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            with _started_recorder(directory, alive=False):
                with mock.patch.object(session, "_reap_forgotten_recorders", return_value=0):
                    with self.assertRaises(session.RecordingError) as raised:
                        session.start_toggle_recording()
        self.assertIn("cause n’est pas identifiée", str(raised.exception))
        self.assertNotIn("Another application", str(raised.exception))


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


class CaptureConfirmedTest(unittest.TestCase):
    def _session(self, audio_path: Path) -> session.RecordingSession:
        return session.RecordingSession(
            pid=DEAD_PID, audio_path=audio_path, sample_rate=16000, started_at=1.0
        )

    def test_a_first_sample_confirms_without_consulting_proc(self):
        """Un échantillon écrit prouve qu'arecord a bien obtenu le micro."""
        with tempfile.TemporaryDirectory() as directory:
            audio_path = Path(directory) / "toggle.wav"
            _wav_with_placeholder_header(audio_path, payload_bytes=320)
            with mock.patch.object(session, "_recorder_alive") as alive:
                self.assertTrue(session._capture_confirmed(self._session(audio_path)))
        alive.assert_not_called()

    def test_a_recorder_that_never_captures_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            audio_path = Path(directory) / "toggle.wav"
            with mock.patch.object(session, "_START_CONFIRMATION_SECONDS", 0.1):
                with mock.patch.object(session, "_recorder_alive", side_effect=[True, False]):
                    self.assertFalse(session._capture_confirmed(self._session(audio_path)))

    def test_a_slow_recorder_still_alive_is_accepted(self):
        """Au bout du délai, un enregistreur vivant garde le bénéfice du doute :
        refuser un micro lent perdrait des dictées que rien n'empêchait."""
        with tempfile.TemporaryDirectory() as directory:
            audio_path = Path(directory) / "toggle.wav"
            with mock.patch.object(session, "_START_CONFIRMATION_SECONDS", 0.0):
                with mock.patch.object(session, "_recorder_alive", return_value=True):
                    self.assertTrue(session._capture_confirmed(self._session(audio_path)))


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


class RecordingSafetyTest(unittest.TestCase):
    def _fake_arecord(self, directory: str, body: str) -> Path:
        executable = Path(directory) / "arecord"
        executable.write_text(f"#!{sys.executable}\n" + body, encoding="utf-8")
        executable.chmod(0o700)
        return executable

    def test_runtime_override_is_not_silently_chmodded_or_followed(self):
        with tempfile.TemporaryDirectory() as directory:
            unsafe = Path(directory) / "shared"
            unsafe.mkdir(mode=0o755)
            with mock.patch.dict(os.environ, {"APARTE_RUNTIME_DIR": str(unsafe)}):
                with self.assertRaises(session.ToggleSessionError):
                    session.get_runtime_dir()
            self.assertEqual(unsafe.stat().st_mode & 0o777, 0o755)
            link = Path(directory) / "link"
            link.symlink_to(Path(directory), target_is_directory=True)
            with mock.patch.dict(os.environ, {"APARTE_RUNTIME_DIR": str(link)}):
                with self.assertRaises(session.ToggleSessionError):
                    session.get_runtime_dir()

    def test_actual_audio_errors_are_preserved_and_distinguished(self):
        cases = (
            ("Device or resource busy", "occupé"),
            ("No such device", "indisponible"),
            ("Unknown PCM plughw:CARD=Removed", "indisponible"),
            ("Permission denied", "cause n’est pas identifiée"),
        )
        for stderr, expected in cases:
            with self.subTest(stderr=stderr), tempfile.TemporaryDirectory() as directory:
                executable = self._fake_arecord(
                    directory, f"import sys, time\ntime.sleep(0.04)\n"
                    f"print({stderr!r}, file=sys.stderr)\nsys.exit(17)\n",
                )
                with mock.patch.dict(os.environ, {"APARTE_RUNTIME_DIR": directory}):
                    with mock.patch.object(session.shutil, "which", return_value=str(executable)):
                        with self.assertRaises(session.RecordingError) as raised:
                            session.start_toggle_recording(device="plughw:CARD=Removed")
                    self.assertFalse(session.get_session_path().exists())
                message = str(raised.exception)
                self.assertIsInstance(raised.exception, session.RecordingStartError)
                self.assertIn(expected, raised.exception.user_message)
                for technical in ('"exit"', '"utc"', '"device"', "plughw:", "{", "17"):
                    self.assertNotIn(technical, raised.exception.user_message)
                self.assertIn(expected, message)
                self.assertIn(stderr, message)
                self.assertIn('"exit": 17', message)
                self.assertIn('"device": "plughw:CARD=Removed"', message)
                self.assertRegex(message, r'"utc": "[^" ]+\+00:00"')
                self.assertFalse(list(Path(directory).glob("*.wav")))
                self.assertFalse(list(Path(directory).glob("*.log")))

    def test_diagnostic_is_bounded_and_does_not_capture_stdout(self):
        with tempfile.TemporaryDirectory() as directory:
            executable = self._fake_arecord(
                directory, "import sys\nprint('private audio placeholder')\n"
                "sys.stderr.write('x' * 20000)\nsys.exit(2)\n",
            )
            with mock.patch.dict(os.environ, {"APARTE_RUNTIME_DIR": directory}):
                with mock.patch.object(session.shutil, "which", return_value=str(executable)):
                    with self.assertRaises(session.RecordingError) as raised:
                        session.start_toggle_recording()
            message = str(raised.exception)
            self.assertLess(len(message), session._DIAGNOSTIC_BYTES + 400)
            self.assertIn("…", message)
            self.assertNotIn("private audio placeholder", message)

    def test_claim_disk_error_reaps_the_real_child(self):
        with tempfile.TemporaryDirectory() as directory:
            executable = self._fake_arecord(directory, "import time\ntime.sleep(60)\n")
            children = []
            popen = subprocess.Popen

            def launch(*args, **kwargs):
                process = popen(*args, **kwargs)
                children.append(process)
                return process

            try:
                with mock.patch.dict(os.environ, {"APARTE_RUNTIME_DIR": directory}):
                    with mock.patch.object(session.shutil, "which", return_value=str(executable)):
                        with mock.patch.object(session.subprocess, "Popen", side_effect=launch):
                            with mock.patch.object(session.os, "link", side_effect=OSError("disk full")):
                                with self.assertRaisesRegex(OSError, "disk full"):
                                    session.start_toggle_recording()
                self.assertEqual(len(children), 1)
                self.assertIsNotNone(children[0].poll())
                self.assertFalse(list(Path(directory).glob("*.wav")))
                self.assertFalse(list(Path(directory).glob("*.tmp")))
            finally:
                for process in children:
                    if process.poll() is None:
                        process.kill()
                    process.wait(timeout=5)

    def test_detached_recorder_can_write_stderr_after_start_has_returned(self):
        with tempfile.TemporaryDirectory() as directory:
            executable = self._fake_arecord(
                directory, "import pathlib, sys, time\n"
                "path = pathlib.Path(sys.argv[-1])\n"
                "path.write_bytes(b'0' * 32044)\n"
                "time.sleep(0.15)\n"
                "sys.stderr.write('later ALSA diagnostic\\n')\nsys.stderr.flush()\n"
                "with path.open('ab') as out: out.write(b'1')\n"
                "time.sleep(60)\n",
            )
            recording = None
            children = []
            popen = subprocess.Popen

            def launch(*args, **kwargs):
                process = popen(*args, **kwargs)
                children.append(process)
                return process

            with mock.patch.dict(os.environ, {"APARTE_RUNTIME_DIR": directory}):
                try:
                    with mock.patch.object(session.shutil, "which", return_value=str(executable)):
                        with mock.patch.object(session.subprocess, "Popen", side_effect=launch):
                            recording = session.start_toggle_recording()
                    deadline = time.monotonic() + 3
                    while recording.audio_path.stat().st_size == 32044 and time.monotonic() < deadline:
                        time.sleep(0.01)
                    self.assertEqual(recording.audio_path.stat().st_size, 32045)
                    self.assertTrue(session._recorder_alive(recording))
                    self.assertEqual(session.stop_toggle_recording(), recording)
                finally:
                    if recording is not None:
                        session._stop_recorder(recording, session.signal.SIGKILL)
                    for process in children:
                        process.wait(timeout=5)

    def test_two_starts_at_same_millisecond_use_different_private_files(self):
        with tempfile.TemporaryDirectory() as directory:
            with _started_recorder(directory):
                with mock.patch.object(session.time, "time", return_value=1234567.0):
                    first = session.start_toggle_recording()
                    first.audio_path.write_bytes(b"first capture must survive")
                    session.get_session_path().unlink()
                    second = session.start_toggle_recording()
            self.assertNotEqual(first.audio_path, second.audio_path)
            self.assertEqual(first.audio_path.read_bytes(), b"first capture must survive")
            self.assertEqual(second.audio_path.stat().st_mode & 0o777, 0o600)

    def test_stale_reader_cannot_remove_the_next_session(self):
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.dict(os.environ, {"APARTE_RUNTIME_DIR": directory}):
                path = session.get_session_path()
                path.write_bytes(b"new session")
                self.assertFalse(session._discard_session_snapshot(path, b"old session"))
                self.assertEqual(path.read_bytes(), b"new session")

    def test_an_old_stop_request_cannot_consume_a_new_session(self):
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.dict(os.environ, {"APARTE_RUNTIME_DIR": directory}):
                audio_path = Path(directory) / "capture.wav"
                _wav_with_placeholder_header(audio_path, 32000)
                current = session.RecordingSession(DEAD_PID, audio_path, 16000, 2)
                old = session.RecordingSession(DEAD_PID, Path(directory) / "old.wav", 16000, 1)
                session._claim_session(current)
                with self.assertRaisesRegex(session.ToggleSessionError, "changé"):
                    session.stop_toggle_recording(expected_session=old)
                self.assertEqual(session.get_active_session(), current)
                self.assertTrue(audio_path.exists())

    def test_a_concurrent_stop_is_rejected_without_waiting_or_consuming_audio(self):
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.dict(os.environ, {"APARTE_RUNTIME_DIR": directory}):
                audio_path = Path(directory) / "capture.wav"
                _wav_with_placeholder_header(audio_path, 32000)
                recording = session.RecordingSession(DEAD_PID, audio_path, 16000, 1)
                session._claim_session(recording)
                entered = threading.Event()
                release = threading.Event()
                result = []

                def delayed_stop(*args):
                    entered.set()
                    if not release.wait(5):
                        raise TimeoutError("test did not release stop")

                def stop():
                    try:
                        result.append(session.stop_toggle_recording())
                    except BaseException as exc:
                        result.append(exc)

                with mock.patch.object(session, "_stop_recorder", side_effect=delayed_stop):
                    worker = threading.Thread(target=stop)
                    worker.start()
                    try:
                        self.assertTrue(entered.wait(5))
                        with self.assertRaisesRegex(session.ToggleSessionError, "déjà en cours"):
                            session.stop_toggle_recording()
                        self.assertTrue(session.get_session_path().exists())
                    finally:
                        release.set()
                        worker.join(5)
                self.assertEqual(result, [recording])
                self.assertTrue(audio_path.exists())
                self.assertFalse(session.get_session_path().exists())

    def test_transition_lock_excludes_another_process_and_is_reentrant(self):
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.dict(os.environ, {"APARTE_RUNTIME_DIR": directory}):
                with session.toggle_session_transition():
                    with session.toggle_session_transition():
                        script = (
                            "from aparte.session import toggle_session_transition, ToggleSessionError\n"
                            "try:\n"
                            "    with toggle_session_transition(): pass\n"
                            "except ToggleSessionError:\n"
                            "    raise SystemExit(23)\n"
                        )
                        result = subprocess.run([sys.executable, "-c", script], timeout=5)
                        self.assertEqual(result.returncode, 23)
                result = subprocess.run([sys.executable, "-c", script], timeout=5)
                self.assertEqual(result.returncode, 0)

    def test_new_unique_names_are_reaped_but_adjacent_directories_are_not(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = Path(directory) / "runtime"
            runtime.mkdir(mode=0o700)
            timestamp = int((time.time() - 120) * 1000)
            audio_path = runtime / f"toggle-{timestamp}-random_1.wav"
            with _recorder_in_proc(audio_path) as process:
                with mock.patch.dict(os.environ, {"APARTE_RUNTIME_DIR": str(runtime)}):
                    self.assertEqual(session._reap_forgotten_recorders(), 1)
                self.assertIsNotNone(process.poll())
            adjacent = Path(directory) / "runtime-extra"
            adjacent.mkdir()
            audio_path = adjacent / f"toggle-{timestamp}-random_2.wav"
            with _recorder_in_proc(audio_path) as process:
                with mock.patch.dict(os.environ, {"APARTE_RUNTIME_DIR": str(runtime)}):
                    self.assertEqual(session._reap_forgotten_recorders(), 0)
                self.assertIsNone(process.poll())


if __name__ == "__main__":
    unittest.main()
