from __future__ import annotations

import importlib.util
import os
import shutil
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

from .config import Settings
from .hotkey import hotkey_info
from .lifecycle import get_dictation_state
from .session import ToggleSessionError


@dataclass(frozen=True)
class Check:
    key: str
    label: str
    ok: bool
    category: str
    detail: str = ""
    fix: str = ""  # shell command the user can run to satisfy the check
    essential: bool = False


def _has_module(name: str) -> bool:
    # find_spec on a dotted name imports the parent package; when the parent is
    # absent (e.g. no "nvidia" namespace) it raises rather than returning None.
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def walled_venv_config() -> Path | None:
    """Le `pyvenv.cfg` d'un venv muré contre les paquets système, s'il l'est.

    PyGObject s'installe par apt, jamais par pip : un venv créé sans
    `--system-site-packages` ne le verra donc **jamais**, quoi qu'on installe.
    C'est un cul-de-sac silencieux — apt répond « déjà à la version la plus
    récente » et l'icône reste absente — et il demande le geste inverse de
    l'autre panne possible, où PyGObject manque pour de bon. Le diagnostic doit
    les distinguer, sinon il envoie tourner en rond.

    Vu le 31/07 sur une installation dont le venv précédait l'ajout du drapeau à
    l'installeur : les paquets système étaient là, parfaitement fonctionnels, et
    invisibles.
    """
    if sys.prefix == sys.base_prefix:
        return None
    config = Path(sys.prefix) / "pyvenv.cfg"
    try:
        content = config.read_text(encoding="utf-8")
    except OSError:
        return None
    for line in content.splitlines():
        key, separator, value = line.partition("=")
        if separator and key.strip() == "include-system-site-packages":
            return config if value.strip().lower() == "false" else None
    return None


def _tray_fix() -> str:
    """La commande qui débloque vraiment, selon laquelle des deux pannes c'est.

    Le `detail` du check, lui, ne bouge pas : il porte une clé i18n statique, et
    la clé gagne toujours sur le texte du backend. Sa phrase reste vraie des deux
    côtés ; seule la commande change.
    """
    walled = walled_venv_config()
    if walled is None:
        return "sudo apt install python3-gi gir1.2-ayatanaappindicator3-0.1"
    return (
        "sed -i 's/^include-system-site-packages = false/"
        f"include-system-site-packages = true/' {walled}"
    )


def _ollama_ok(settings: Settings) -> bool:
    try:
        import requests

        response = requests.get(f"{settings.ollama_url.rstrip('/')}/api/tags", timeout=0.5)
        return response.ok
    except Exception:
        return False


def collect_checks(settings: Settings) -> list[Check]:
    """Build the full diagnostic check list, grouped by category."""
    is_wayland = bool(os.getenv("WAYLAND_DISPLAY"))
    is_x11 = bool(os.getenv("DISPLAY"))

    has_faster = _has_module("faster_whisper")
    has_openai = _has_module("whisper")
    has_cpp = bool(settings.whisper_cpp or shutil.which("whisper-cli") or shutil.which("main"))
    has_cuda_libs = _has_module("nvidia.cublas") and _has_module("nvidia.cudnn")

    has_sounddevice = _has_module("sounddevice")
    has_arecord = shutil.which("arecord") is not None
    has_pw = shutil.which("pw-record") is not None
    has_parec = shutil.which("parec") is not None

    has_wl_paste = shutil.which("wtype") is not None
    has_x11_paste = shutil.which("xdotool") is not None
    has_wl_copy = shutil.which("wl-copy") is not None
    has_x11_copy = shutil.which("xclip") is not None or shutil.which("xsel") is not None

    paste_pkg = "wl-clipboard wtype" if is_wayland else "xdotool"
    copy_pkg = "wl-clipboard" if is_wayland else "xclip"

    checks: list[Check] = [
        # Transcription
        Check(
            "whisper_backend",
            "Local Whisper backend",
            has_faster or has_openai or has_cpp,
            "Transcription",
            detail="faster-whisper, openai-whisper, or whisper.cpp",
            fix='pip install -e ".[whisper]"',
            essential=True,
        ),
        Check(
            "gpu",
            "GPU acceleration (CUDA)",
            has_cuda_libs,
            "Transcription",
            detail="NVIDIA cuBLAS + cuDNN wheels (optional, faster)",
            fix='pip install -e ".[cuda]"',
        ),
        # Microphone
        Check(
            "recorder",
            "Microphone recorder",
            has_sounddevice or has_arecord or has_pw or has_parec,
            "Microphone",
            detail="sounddevice, arecord, pw-record, or parec",
            fix="sudo apt install alsa-utils",
            essential=True,
        ),
        # Insertion / clipboard
        Check(
            "paste",
            "Insert into active app",
            (has_wl_paste and is_wayland) or (has_x11_paste and is_x11),
            "Insertion",
            detail="types dictation into the focused window",
            fix=f"sudo apt install {paste_pkg}",
            essential=True,
        ),
        Check(
            "clipboard",
            "Clipboard copy",
            (has_wl_copy and is_wayland) or has_x11_copy,
            "Insertion",
            detail="fallback when direct paste is unavailable",
            fix=f"sudo apt install {copy_pkg}",
        ),
        # System
        Check(
            "config",
            "Config file",
            bool(settings.config_path and settings.config_path.exists()),
            "System",
            detail=str(settings.config_path or ""),
            fix="aparte config init",
        ),
        Check(
            "tray",
            "System tray icon",
            _has_module("gi"),
            "System",
            detail="needs PyGObject; a virtualenv only sees it with --system-site-packages",
            fix=_tray_fix(),
        ),
        Check(
            "notify",
            "Desktop notifications",
            shutil.which("notify-send") is not None,
            "System",
            detail="recording start/stop popups (optional)",
            fix="sudo apt install libnotify-bin",
        ),
    ]

    if settings.polish_backend == "ollama":
        checks.append(
            Check(
                "ollama",
                "Ollama (LLM polish)",
                _ollama_ok(settings),
                "System",
                detail="local LLM rewrite backend",
                fix="ollama serve",
            )
        )

    return checks


def collect_diagnostics(settings: Settings) -> dict:
    """Structured diagnostics for the desktop app and the CLI doctor."""
    checks = collect_checks(settings)
    by_key = {c.key: c for c in checks}
    can_transcribe = by_key["whisper_backend"].ok
    can_record = by_key["recorder"].ok
    can_insert = by_key["paste"].ok or by_key["clipboard"].ok
    essentials_ok = all(c.ok for c in checks if c.essential)
    try:
        state = get_dictation_state()
    except (OSError, ToggleSessionError):
        # A concurrent transition or inaccessible runtime does not prove the
        # microphone is closed. Keep that uncertainty visible to consumers.
        state = "unknown"
    return {
        "checks": [asdict(c) for c in checks],
        "summary": {
            "ready": essentials_ok,
            "can_transcribe": can_transcribe,
            "can_record": can_record,
            "can_insert": can_insert,
        },
        # A stopped recorder can still have a session carrying recoverable
        # speech. Its presence does not mean the microphone remains open.
        "recording_active": None if state == "unknown" else state == "recording",
        "dictation_state": state,
        "hotkey": hotkey_info(),
    }
