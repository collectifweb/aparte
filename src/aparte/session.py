from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from .audio import RecordingError


class ToggleSessionError(RuntimeError):
    pass


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
            path.mkdir(parents=True, exist_ok=True)
            probe = path / ".write-test"
            probe.write_text("", encoding="utf-8")
            probe.unlink(missing_ok=True)
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
        cmdline = Path(f"/proc/{session.pid}/cmdline").read_bytes()
    except OSError:
        return False
    return b"arecord" in cmdline and os.fsencode(session.audio_path) in cmdline


def get_active_session() -> RecordingSession | None:
    path = get_session_path()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
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
        path.unlink(missing_ok=True)
        return None
    if _recorder_alive(session):
        return session
    # L'enregistreur a fini seul : plafond atteint, ou refus au démarrage. Ce
    # qu'il a capté reste une dictée à transcrire au prochain appui. La
    # supprimer ici détruirait l'enregistrement à la seconde même où
    # l'utilisateur appuie pour le récupérer.
    if _captured_seconds(session) >= MIN_TRANSCRIBABLE_SECONDS:
        return session
    path.unlink(missing_ok=True)
    session.audio_path.unlink(missing_ok=True)
    return None


def _claim_session(session: RecordingSession) -> bool:
    """Prendre la session pour nous. False si un autre appui l'a déjà prise.

    Le lien physique est atomique et exclusif : ou bien il publie le fichier
    complet d'un seul coup, ou bien il échoue parce que la cible existe. Un
    lecteur ne voit donc jamais de JSON tronqué — ce qui, avant, le faisait
    supprimer la session d'un enregistrement bien vivant.
    """
    path = get_session_path()
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(
            {
                "pid": session.pid,
                "audio_path": str(session.audio_path),
                "sample_rate": session.sample_rate,
                "started_at": session.started_at,
            }
        ),
        encoding="utf-8",
    )
    try:
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


def start_toggle_recording(
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

    audio_path = get_runtime_dir() / f"toggle-{int(time.time() * 1000)}.wav"
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
    process = subprocess.Popen(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    session = RecordingSession(
        pid=process.pid,
        audio_path=audio_path,
        sample_rate=sample_rate,
        started_at=time.time(),
    )
    if not _claim_session(session):
        # Un autre appui a gagné la course. Abandonner le nôtre ici, ce serait
        # laisser un arecord que plus aucune session ne référence — donc que
        # plus aucun appui ne peut arrêter.
        _stop_recorder(session)
        audio_path.unlink(missing_ok=True)
        raise ToggleSessionError("Recording is already active.")
    if not _recorder_alive(session):
        # Gagner la course avec un enregistreur déjà mort annoncerait une dictée
        # qui n'a jamais commencé. arecord écrit son refus sur une sortie qu'on
        # jette : c'est ici, et seulement ici, qu'il peut devenir visible.
        get_session_path().unlink(missing_ok=True)
        audio_path.unlink(missing_ok=True)
        raise RecordingError(
            "Could not start recording. Another application may be holding the microphone."
        )
    return session


def stop_toggle_recording(timeout: float = 3.0) -> RecordingSession:
    session = get_active_session()
    if not session:
        raise ToggleSessionError("No active toggle recording.")

    # Une session peut déjà être terminée — plafond atteint — auquel cas il n'y
    # a rien à signaler : `_stop_recorder` le voit et ne touche à rien.
    _stop_recorder(session)

    deadline = time.time() + timeout
    while time.time() < deadline and _recorder_alive(session):
        time.sleep(0.05)
    _stop_recorder(session, signal.SIGTERM)

    get_session_path().unlink(missing_ok=True)
    if not session.audio_path.exists():
        raise ToggleSessionError(f"Recording file was not created: {session.audio_path}")
    return session
