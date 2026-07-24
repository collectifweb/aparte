from __future__ import annotations

import importlib.util
import os
import shutil
from dataclasses import asdict, dataclass

from .config import Settings
from .hotkey import hotkey_info
from .platform_dispatch import is_macos
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
    # find_spec on a dotted name imports the parent package; when the parent is
    # absent (e.g. no "nvidia" namespace) it raises rather than returning None.
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def _ollama_ok(settings: Settings) -> bool:
    try:
        import requests

        response = requests.get(f"{settings.ollama_url.rstrip('/')}/api/tags", timeout=0.5)
        return response.ok
    except Exception:
        return False


def collect_checks(settings: Settings) -> list[Check]:
    """Build the diagnostic check list for the current OS, grouped by category."""
    if is_macos():
        return _collect_checks_macos(settings)
    return _collect_checks_linux(settings)


def _collect_checks_linux(settings: Settings) -> list[Check]:
    """The Linux check list: ALSA/PipeWire recording, X11/Wayland paste, the
    PyGObject tray, notify-send, apt fixes."""
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
            fix="sudo apt install python3-gi gir1.2-ayatanaappindicator3-0.1",
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


def _collect_checks_macos(settings: Settings) -> list[Check]:
    """The macOS check list: TCC permissions (microphone, Accessibility), the
    speech model's download state, Homebrew/Settings fixes. Synthetic paste is
    not checked yet — it lands in M3, and Accessibility is only its prerequisite.

    A check's ``detail`` is static and describes what it IS, never its live state:
    the web panel translates it by key and would otherwise show one fixed string
    regardless of the icon. The granted/denied/not-yet-asked nuance is the job of
    the guided permission flow (M3), not of a passive diagnostic line."""
    from . import macos_permissions

    has_faster = _has_module("faster_whisper")
    has_openai = _has_module("whisper")
    has_cpp = bool(settings.whisper_cpp or shutil.which("whisper-cli") or shutil.which("main"))
    has_sounddevice = _has_module("sounddevice")

    mic = macos_permissions.microphone_authorization()
    accessibility = macos_permissions.accessibility_trusted()
    model_cached = _whisper_model_cached(settings)

    checks: list[Check] = [
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
            "model_ready",
            "Speech model downloaded",
            model_cached,
            "Transcription",
            detail="downloaded once on first use, then offline",
        ),
        Check(
            "recorder",
            "Microphone recorder",
            has_sounddevice,
            "Microphone",
            detail="captures the microphone for transcription",
            fix='pip install -e ".[recording]"',
            essential=True,
        ),
        Check(
            "mic_permission",
            "Microphone permission",
            mic == "authorized",
            "Microphone",
            detail="managed in System Settings → Privacy & Security → Microphone",
            essential=True,
        ),
        Check(
            "accessibility",
            "Accessibility permission",
            bool(accessibility),
            "Insertion",
            detail="for paste; managed in System Settings → Privacy & Security → Accessibility",
        ),
        Check(
            "clipboard",
            "Clipboard copy",
            True,
            "Insertion",
            detail="copies the dictation to the clipboard",
        ),
        Check(
            "notify",
            "Desktop notifications",
            shutil.which("osascript") is not None,
            "System",
            detail="recording start/stop popups (optional)",
        ),
        Check(
            "config",
            "Config file",
            bool(settings.config_path and settings.config_path.exists()),
            "System",
            detail=str(settings.config_path or ""),
            fix="aparte config init",
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


def _whisper_model_cached(settings: Settings) -> bool:
    """Best-effort: is the speech model already local, so the first transcription
    needs no network? A filesystem path counts; otherwise look through the
    HuggingFace hub cache (faster-whisper stores models as ``models--org--repo``).
    Cross-platform, only informational — a false negative merely shows the honest
    "will download once" message."""
    from pathlib import Path

    model = (settings.model or "").strip()
    if not model:
        return False
    if Path(model).expanduser().exists():
        return True
    cache = Path(os.getenv("HF_HOME") or (Path.home() / ".cache" / "huggingface")) / "hub"
    if not cache.is_dir():
        return False
    needle = model.lower().replace("/", "--")
    try:
        return any(
            entry.name.startswith("models--") and needle in entry.name.lower()
            for entry in cache.iterdir()
        )
    except OSError:
        return False


def collect_diagnostics(settings: Settings) -> dict:
    """Structured diagnostics for the desktop app and the CLI doctor."""
    checks = collect_checks(settings)
    by_key = {c.key: c for c in checks}

    def _ok(key: str) -> bool:
        # .get, not [key]: the macOS list has no "paste" check (insertion is M3),
        # and the summary must not KeyError on an OS whose checks differ.
        check = by_key.get(key)
        return bool(check and check.ok)

    can_transcribe = _ok("whisper_backend")
    can_record = _ok("recorder")
    can_insert = _ok("paste") or _ok("clipboard")
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
        "hotkey": hotkey_info(),
    }
