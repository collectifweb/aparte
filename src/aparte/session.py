from __future__ import annotations

import json
import fcntl
import os
import re
import shutil
import signal
import stat
import subprocess
import tempfile
import time
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, BinaryIO

from .audio import RecordingError


class ToggleSessionError(RuntimeError):
    pass


class RecordingStartError(RecordingError):
    """Un résumé affichable et le diagnostic technique destiné au journal."""

    def __init__(self, user_message: str, diagnostic: str):
        super().__init__(diagnostic)
        self.user_message = user_message


@dataclass(frozen=True)
class RecordingSession:
    pid: int
    audio_path: Path
    sample_rate: int
    started_at: float


# Vrai parce que `start_toggle_recording` impose `-f S16_LE -c 1` : en-tête RIFF,
# `fmt ` de 16 octets, puis `data`. Ne pas réutiliser comme vérité WAV générale.
_ARECORD_WAV_HEADER_BYTES = 44

# En dessous, il n'y a pas de dictée : ce sont les miettes d'un démarrage raté.
# Whisper fabrique du texte sur trois millisecondes de bruit comme sur du silence.
MIN_TRANSCRIBABLE_SECONDS = 0.3

# Le délai qu'on laisse à `arecord` pour prouver qu'il capte vraiment. Mesuré sur
# un micro USB : `Popen` rend la main dès l'exec (0,001 s), le fichier apparaît à
# 0,04 s et le premier échantillon à 0,17 s — mais un `-D plughw:` déjà tenu par
# une autre application ne fait sortir arecord qu'à 0,02-0,05 s. Décider avant,
# c'est annoncer une dictée à un enregistreur déjà condamné.
_START_CONFIRMATION_SECONDS = 0.75
_START_POLL_SECONDS = 0.02

# En dessous, un enregistreur n'est pas encore un oubli : un appui concurrent peut
# être en train de publier sa session. Au-delà, plus personne ne viendra le faire.
_ORPHAN_GRACE_SECONDS = 2.0
# Ce qu'on laisse à un enregistreur ramassé pour rendre le micro.
_ORPHAN_EXIT_SECONDS = 1.0
_DIAGNOSTIC_BYTES = 4096
_transition_state = threading.local()


@contextmanager
def toggle_session_transition() -> Iterator[None]:
    """Décider et effectuer un démarrage/arrêt sans attendre un autre appui.

    Attendre transformerait un deuxième arrêt en un nouveau démarrage. Le
    verrou est réentrant pour que le CLI protège la décision et les fonctions
    start/stop protègent aussi leurs appelants directs. Il ne couvre jamais la
    transcription. Ne pas supprimer son fichier : flock verrouille un inode.
    """
    path = get_runtime_dir() / "toggle-transition.lock"
    key = (os.getpid(), path)
    if getattr(_transition_state, "key", None) == key:
        yield
        return
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_CLOEXEC, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ToggleSessionError("Une ouverture ou un arrêt du micro est déjà en cours.") from exc
        _transition_state.key = key
        try:
            yield
        finally:
            _transition_state.key = None
    finally:
        os.close(fd)


def get_runtime_dir() -> Path:
    override = os.getenv("APARTE_RUNTIME_DIR")
    if override:
        candidates = [Path(override).expanduser()]
    else:
        candidates = []
        if os.getenv("XDG_RUNTIME_DIR"):
            candidates.append(Path(os.environ["XDG_RUNTIME_DIR"]) / "aparte")
        candidates.append(Path(tempfile.gettempdir()) / f"aparte-{os.getuid()}")
    last_error: OSError | None = None
    for path in candidates:
        try:
            path.mkdir(parents=True, exist_ok=True, mode=0o700)
            info = path.lstat()
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
                raise PermissionError(f"Runtime directory must belong to this user and not be a symlink: {path}")
            if info.st_mode & 0o077:
                if override:
                    # Un override peut désigner n'importe quel dossier : ne pas
                    # changer ses permissions à la place de l'utilisateur.
                    raise PermissionError(f"Runtime directory must be private (mode 700): {path}")
                path.chmod(0o700)
            with tempfile.TemporaryFile(dir=path):
                pass
            return path
        except OSError as exc:
            last_error = exc
    raise ToggleSessionError(f"No writable runtime directory found: {last_error}")


def get_session_path() -> Path:
    return get_runtime_dir() / "toggle-session.json"


def _captured_seconds(session: RecordingSession) -> float:
    """Combien de son ce fichier porte vraiment.

    Calculé sur la taille, jamais sur l'en-tête : sans durée imposée, `arecord`
    plafonne le WAV à 2 Gio et écrit un en-tête bouche-trou de 0x40000000
    trames, qu'il ne corrige qu'en sortant proprement. Tué avant, il annonce
    67 108 s pour trois secondes de son — n'importe quel seuil de durée lu là
    laisserait passer les miettes qu'il doit justement rejeter.
    """
    try:
        payload = session.audio_path.stat().st_size - _ARECORD_WAV_HEADER_BYTES
    except OSError:
        return 0.0
    # S16_LE mono : deux octets par échantillon.
    return max(0.0, payload / (session.sample_rate * 2))


def _recorder_alive(session: RecordingSession) -> bool:
    """Ce PID est-il toujours *notre* arecord, et pas un PID recyclé ?

    Le noyau réattribue les PID libérés : `os.kill(pid, 0)` répondrait vrai pour
    le processus de quelqu'un d'autre, et `killpg` enverrait alors un SIGINT à
    tout son groupe. Le chemin du fichier est unique par session, donc il
    distingue même deux arecord lancés en même temps.
    """
    try:
        process_dir = Path(f"/proc/{session.pid}")
        if process_dir.stat().st_uid != os.getuid():
            return False
        argv = (process_dir / "cmdline").read_bytes().split(b"\x00")
    except OSError:
        return False
    return (
        any(os.path.basename(arg) == b"arecord" for arg in argv[:2])
        and os.fsencode(session.audio_path) in argv
    )


def get_active_session() -> RecordingSession | None:
    path = get_session_path()
    if not path.exists():
        return None
    contents = None
    try:
        contents = path.read_bytes()
        data = json.loads(contents)
        session = RecordingSession(
            pid=int(data["pid"]),
            audio_path=Path(str(data["audio_path"])),
            sample_rate=int(data["sample_rate"]),
            started_at=float(data["started_at"]),
        )
    except Exception:
        # L'écriture passe par `_claim_session`, donc un fichier illisible n'est
        # plus un état transitoire : c'est de la corruption. Le supprimer est la
        # récupération — le garder bloquerait toute dictée future.
        _discard_session_snapshot(path, contents)
        return None
    if _recorder_alive(session):
        return session
    # L'enregistreur a fini seul : plafond atteint, ou refus au démarrage. Ce
    # qu'il a capté reste une dictée à transcrire au prochain appui. La
    # supprimer ici détruirait l'enregistrement à la seconde même où
    # l'utilisateur appuie pour le récupérer.
    if _captured_seconds(session) >= MIN_TRANSCRIBABLE_SECONDS:
        return session
    if _discard_session_snapshot(path, contents):
        session.audio_path.unlink(missing_ok=True)
    return None


def _discard_session_snapshot(path: Path, contents: bytes | None) -> bool:
    """Un lecteur ancien (tray) ne doit pas supprimer une nouvelle session."""
    if contents is None:
        return False
    try:
        with toggle_session_transition():
            if path.read_bytes() != contents:
                return False
            path.unlink()
            return True
    except (ToggleSessionError, OSError):
        return False


def _claim_session(session: RecordingSession) -> bool:
    """Prendre la session pour nous. False si un autre appui l'a déjà prise.

    Le lien physique est atomique et exclusif : ou bien il publie le fichier
    complet d'un seul coup, ou bien il échoue parce que la cible existe. Un
    lecteur ne voit donc jamais de JSON tronqué — ce qui, avant, le faisait
    supprimer la session d'un enregistrement bien vivant.
    """
    path = get_session_path()
    fd, name = tempfile.mkstemp(prefix=f"{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump({
                "pid": session.pid,
                "audio_path": str(session.audio_path),
                "sample_rate": session.sample_rate,
                "started_at": session.started_at,
            }, handle)
        os.link(temporary, path)
        return True
    except FileExistsError:
        return False
    finally:
        temporary.unlink(missing_ok=True)


def _clear_stale_temporaries() -> None:
    """Ramasser les temporaires d'un processus tué entre l'écriture et le lien.

    Seulement les vieux : un temporaire tout frais appartient peut-être encore à
    un appui concurrent en train de publier sa session.
    """
    path = get_session_path()
    cutoff = time.time() - 60
    for leftover in path.parent.glob(f"{path.name}.*.tmp"):
        try:
            if leftover.stat().st_mtime < cutoff:
                leftover.unlink(missing_ok=True)
        except OSError:
            continue


def _stop_recorder(session: RecordingSession, number: int = signal.SIGINT) -> None:
    """Arrêter l'enregistreur de cette session, s'il est encore le nôtre."""
    if not _recorder_alive(session):
        return
    try:
        os.killpg(session.pid, number)
    except ProcessLookupError:
        pass
    except PermissionError as exc:
        raise ToggleSessionError(f"Cannot stop recording process {session.pid}: {exc}") from exc


def _capture_confirmed(session: RecordingSession) -> bool:
    """Attendre qu'`arecord` prouve qu'il capte, ou qu'il meure sans avoir capté.

    Le premier échantillon écrit est la seule preuve qu'il a obtenu le micro : un
    périphérique matériel déjà tenu par une autre application le fait sortir sans
    en écrire un seul, et sur une sortie d'erreur qu'on jette. Un enregistreur
    encore vivant au bout du délai est accepté — mieux vaut annoncer un micro lent
    qu'une dictée refusée.
    """
    deadline = time.monotonic() + _START_CONFIRMATION_SECONDS
    while True:
        if _captured_seconds(session) > 0.0:
            return True
        if not _recorder_alive(session):
            return False
        if time.monotonic() >= deadline:
            return True
        time.sleep(_START_POLL_SECONDS)


def _forgotten_recorders() -> list[tuple[int, Path]]:
    """Nos `arecord` vivants que plus aucune session ne suit.

    Reconnus sur ce qu'ils écrivent : notre dossier d'exécution, et le nom
    `toggle-<horodatage>.wav` que nous seuls produisons. L'horodatage donne leur
    âge sans consulter `/proc/<pid>/stat` et ses jiffies.
    """
    runtime = get_runtime_dir()
    cutoff = time.time() - _ORPHAN_GRACE_SECONDS
    forgotten: list[tuple[int, Path]] = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            if entry.stat().st_uid != os.getuid():
                continue
            argv = (entry / "cmdline").read_bytes().rstrip(b"\x00").split(b"\x00")
        except OSError:
            continue  # sorti entre l'énumération et la lecture
        if not any(os.path.basename(arg) == b"arecord" for arg in argv[:2]):
            continue
        audio_path = Path(os.fsdecode(argv[-1]))
        match = re.fullmatch(r"toggle-(\d+)(?:-[a-z0-9_]+)?\.wav", audio_path.name)
        if audio_path.parent != runtime or match is None:
            continue
        started_at = int(match[1]) / 1000
        if started_at <= cutoff:
            forgotten.append((int(entry.name), audio_path))
    return forgotten


def _reap_forgotten_recorders() -> int:
    """Arrêter les enregistreurs que plus aucune session ne suit. Rend leur nombre.

    Quatre fois en quatre jours, un `arecord` est resté vivant sans session, et le
    journal du raccourci n'en garde aucune trace : la cause exacte n'est pas
    établie. Le micro configuré étant ouvert en accès exclusif (`-D plughw:`), ce
    résidu refusait toute dictée jusqu'à son plafond de cinq minutes, en accusant
    « une autre application ». Le ramasser rend la panne sans conséquence, quelle
    qu'en soit l'origine — et c'est la seule protection qui vaille aussi pour les
    variantes qu'on n'a pas encore vues.

    Appelé seulement quand aucune session n'est active : ce qu'une session suit
    encore n'est pas un oubli, c'est la dictée en cours.
    """
    forgotten = _forgotten_recorders()
    if not forgotten:
        return 0
    for pid, audio_path in forgotten:
        if not _recorder_alive(RecordingSession(pid, audio_path, 16000, 0)):
            continue
        try:
            # Le PID seul, pas son groupe : on vise un processus qu'on vient
            # d'identifier par sa ligne de commande, rien de ce qui l'entoure.
            # SIGINT comme `_stop_recorder`, pour qu'il finalise son en-tête.
            os.kill(pid, signal.SIGINT)
        except OSError:
            continue
    # Le fichier reste : il porte de la voix, et `/run` se vide à la déconnexion.
    # Attendre qu'ils rendent le micro, sinon le `Popen` juste derrière le
    # retrouve occupé et échoue sur le résidu qu'on vient de fermer.
    deadline = time.monotonic() + _ORPHAN_EXIT_SECONDS
    while time.monotonic() < deadline:
        if not any(Path(f"/proc/{pid}").exists() for pid, _ in forgotten):
            break
        time.sleep(_START_POLL_SECONDS)
    return len(forgotten)


def _start_toggle_recording(
    sample_rate: int = 16000,
    device: str | None = None,
    max_seconds: int = 300,
) -> RecordingSession:
    if get_active_session():
        raise ToggleSessionError("Recording is already active.")
    executable = shutil.which("arecord")
    if not executable:
        raise RecordingError("Toggle recording requires arecord from alsa-utils.")
    _clear_stale_temporaries()
    reaped = _reap_forgotten_recorders()

    fd, name = tempfile.mkstemp(
        prefix=f"toggle-{int(time.time() * 1000)}-", suffix=".wav", dir=get_runtime_dir()
    )
    os.close(fd)
    audio_path = Path(name)
    command = [
        executable,
        "-q",
        *(["-D", device] if device else []),
        "-f",
        "S16_LE",
        "-r",
        str(sample_rate),
        "-c",
        "1",
        # Un micro qu'on oublie ouvert enregistre jusqu'à saturer le disque.
        # `arecord` sort proprement au plafond, donc l'appui suivant retrouve
        # une session terminée et transcrit ce qui a été capté : une troncature,
        # pas une disparition.
        "-d",
        str(max_seconds),
        str(audio_path),
    ]
    # Anonyme et privé : le fils détaché garde ce descripteur après la sortie
    # du lanceur. Une pipe perdrait son lecteur et pourrait casser arecord.
    # Seule la lecture du diagnostic est bornée ; limiter RLIMIT_FSIZE limiterait
    # aussi le WAV. Aucun journal persistant ni contenu dicté ici.
    with tempfile.TemporaryFile(dir=get_runtime_dir()) as errors:
        process = None
        session = None
        claimed = False
        try:
            process = subprocess.Popen(
                command,
                stdout=subprocess.DEVNULL,
                stderr=errors,
                start_new_session=True,
                env={**os.environ, "LC_ALL": "C"},
            )
            session = RecordingSession(
                pid=process.pid,
                audio_path=audio_path,
                sample_rate=sample_rate,
                started_at=time.time(),
            )
            claimed = _claim_session(session)
            if not claimed:
                raise ToggleSessionError("Recording is already active.")
            if not _capture_confirmed(session):
                try:
                    process.wait(timeout=0.2)
                except subprocess.TimeoutExpired:
                    pass
                raise _recording_failure(errors, process.returncode, device, reaped)
            return session
        except BaseException:
            # Toute exception après Popen, y compris une erreur disque dans
            # _claim_session, doit rendre le micro avant de quitter le lanceur.
            if process is not None:
                _close_failed_recorder(process, session)
            if claimed:
                get_session_path().unlink(missing_ok=True)
            # Ne pas détruire de parole captée pendant un démarrage anormal.
            if session is None or _captured_seconds(session) < MIN_TRANSCRIBABLE_SECONDS:
                audio_path.unlink(missing_ok=True)
            raise


def _recording_failure(
    errors: BinaryIO, returncode: int | None, device: str | None, reaped: int,
) -> RecordingStartError:
    errors.seek(0)
    raw = errors.read(_DIAGNOSTIC_BYTES + 1)
    detail = raw[:_DIAGNOSTIC_BYTES].decode("utf-8", errors="replace")
    detail = " ".join(detail.split())
    if len(raw) > _DIAGNOSTIC_BYTES:
        detail += "…"
    lowered = detail.lower()
    if "device or resource busy" in lowered:
        reason = "Le périphérique audio est occupé (signalé par ALSA)."
    elif any(text in lowered for text in (
        "no such device", "no such file or directory", "cannot find card", "unknown pcm",
        "input/output error", "device disconnected",
    )):
        reason = "Le périphérique audio est indisponible (signalé par ALSA)."
    else:
        reason = "Le démarrage audio a échoué ; la cause n’est pas identifiée."
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    metadata = json.dumps({"utc": stamp, "exit": returncode, "device": device or "default",
                           "closed_recorders": reaped}, ensure_ascii=False)
    return RecordingStartError(
        reason,
        f"Dictée non démarrée. {reason} {metadata} ALSA: {detail or 'aucun diagnostic reçu'}",
    )


def _close_failed_recorder(process: subprocess.Popen, session: RecordingSession | None) -> None:
    # Ce Popen est notre fils, donc wait()/terminate() ne ciblent pas un PID
    # emprunté à un vieux fichier de session. Récolter le fils évite un zombie.
    try:
        if session is not None:
            _stop_recorder(session)
        else:
            process.send_signal(signal.SIGINT)
    except (OSError, ToggleSessionError):
        # Même si la première tentative échoue, terminer et récolter notre fils.
        pass
    try:
        process.wait(timeout=0.5)
    except subprocess.TimeoutExpired:
        process.terminate()
        try:
            process.wait(timeout=0.5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=0.5)


def start_toggle_recording(
    sample_rate: int = 16000,
    device: str | None = None,
    max_seconds: int = 300,
) -> RecordingSession:
    with toggle_session_transition():
        return _start_toggle_recording(sample_rate, device, max_seconds)


def stop_toggle_recording(
    timeout: float = 3.0, *, expected_session: RecordingSession | None = None,
) -> RecordingSession:
    with toggle_session_transition():
        return _stop_toggle_recording(timeout, expected_session=expected_session)


def _stop_toggle_recording(
    timeout: float, *, expected_session: RecordingSession | None,
) -> RecordingSession:
    session = get_active_session()
    if not session:
        raise ToggleSessionError("No active toggle recording.")
    if expected_session is not None and session != expected_session:
        raise ToggleSessionError("La session d’enregistrement a changé ; cet arrêt est ignoré.")

    # Une session peut déjà être terminée — plafond atteint — auquel cas il n'y
    # a rien à signaler : `_stop_recorder` le voit et ne touche à rien.
    _stop_recorder(session)

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and _recorder_alive(session):
        time.sleep(0.05)
    _stop_recorder(session, signal.SIGTERM)
    deadline = time.monotonic() + 0.5
    while _recorder_alive(session) and time.monotonic() < deadline:
        time.sleep(0.02)
    if _recorder_alive(session):
        # Garder le suivi : déclarer l'arrêt ici laisserait le micro ouvert
        # alors que le prochain appui croirait pouvoir démarrer une autre capture.
        raise ToggleSessionError("Le micro ne s’est pas arrêté ; réessayez l’arrêt.")

    get_session_path().unlink(missing_ok=True)
    if not session.audio_path.exists():
        raise ToggleSessionError(f"Recording file was not created: {session.audio_path}")
    return session
