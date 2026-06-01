from __future__ import annotations

import importlib.util
import os
import shutil
from dataclasses import asdict, dataclass

from .config import Settings
from .session import get_active_session


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
    return importlib.util.find_spec(name) is not None


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
            fix="murmur config init",
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
    active = get_active_session()
    return {
        "checks": [asdict(c) for c in checks],
        "summary": {
            "ready": essentials_ok,
            "can_transcribe": can_transcribe,
            "can_record": can_record,
            "can_insert": can_insert,
        },
        "recording_active": bool(active),
    }
