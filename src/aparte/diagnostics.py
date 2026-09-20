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


def collect_checks(settings: Settings, *, hotkey_state=None) -> list[Check]:
    """Build the diagnostic check list for the current OS, grouped by category.

    ``hotkey_state`` is the macOS global-shortcut snapshot the resident server
    owns; passed in-process by the desktop handler, it spares the macOS hotkey
    check a self-request. ``None`` (Linux, or the CLI ``doctor`` standing apart
    from the server) is fine — the Linux path ignores it and the macOS path then
    asks a running server itself, falling back to a static reply.
    """
    if is_macos():
        return _collect_checks_macos(settings, hotkey_state)
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


def _collect_checks_macos(settings: Settings, hotkey_state=None) -> list[Check]:
    """The macOS check list: TCC permissions (microphone, Accessibility), the
    speech model's download state, the global shortcut, Homebrew/Settings fixes.
    Synthetic paste is not checked yet — it lands in M3, and Accessibility is only
    its prerequisite.

    Most checks' ``detail`` is static and describes what it IS, never its live
    state: the web panel translates it by key and would otherwise show one fixed
    string regardless of the icon. The hotkey check is the deliberate exception —
    its detail varies, so it carries NO i18n key (see :func:`_hotkey_check`)."""
    from . import macos_permissions

    has_faster = _has_module("faster_whisper")
    has_openai = _has_module("whisper")
    has_cpp = bool(settings.whisper_cpp or shutil.which("whisper-cli") or shutil.which("main"))
    has_sounddevice = _has_module("sounddevice")

    mic = macos_permissions.microphone_authorization()
    accessibility = macos_permissions.accessibility_trusted()
    model_cached = _whisper_model_cached(settings)
    # In-process the resident server hands us the state it owns; standing apart
    # (CLI doctor) we ask a running one over its read-only route, else None.
    hotkey = hotkey_state if hotkey_state is not None else _query_hotkey_state()

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
        _hotkey_check(settings, hotkey),
        _tray_check(),
        _app_bundle_check(),
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


def _app_bundle_check() -> Check:
    """Is Aparté.app installed, and does it still match the fingerprint on record?

    Never essential: without the bundle Aparté runs perfectly, the permission
    dialogs simply carry the name of whatever launched Python. The detail is
    **dynamic and therefore carries no i18n key** — a static key would overwrite it
    in the web panel and could contradict its own icon (CLAUDE.md, § Interface).

    The mismatch case is the one worth naming and the one nothing can detect from
    outside: the permissions are already gone, while System Settings still shows
    them granted.
    """
    from .macos_desktop import bundle_path
    from .macos_install import installed_state

    label = "Aparté.app"
    state = installed_state()
    if not state["installed"]:
        return Check(
            "app_bundle",
            label,
            False,
            "System",
            detail="permission dialogs will name whatever launched Aparté",
            fix="aparte install-app --open",
        )
    if state["matches_reference"] is False:
        return Check(
            "app_bundle",
            label,
            False,
            "System",
            detail="installed bundle differs from the one on record — permissions were lost",
            fix="aparte install-app --force",
        )
    return Check("app_bundle", label, True, "System", detail=str(bundle_path()))


def _hotkey_check(settings: Settings, state) -> Check:
    """The macOS global-shortcut check.

    Its ``detail`` is DYNAMIC — it names the combo and why it is or isn't active —
    so it carries NO ``check.hotkey.detail`` i18n key: a static key would overwrite
    the live text and could contradict the icon (the same reason the ``config``
    check has no detail key). Only the label is translated, and it stays neutral.
    Never essential — the app still dictates from the browser with no shortcut.

    The web panel always calls doctor in-process, so it only ever hits the neutral
    branches (a combo, an ``OSStatus``, or a command). The English guidance line
    is reachable solely from the CLI ``doctor`` (``state is None``), where the
    terminal output is English anyway — so no untranslated sentence hits the UI."""
    from .macos_hotkey import safe_hotkey_label

    label = "Dictation shortcut"
    configured = (getattr(settings, "hotkey", "") or "").strip()

    if state is not None:
        if state.registered and state.configured_key:
            return Check("hotkey", label, True, "System", detail=safe_hotkey_label(state.configured_key))
        if state.configured_key:
            reason = f"OSStatus {state.status}" if state.status is not None else (state.error or "unavailable")
            return Check(
                "hotkey", label, False, "System",
                detail=f"{safe_hotkey_label(state.configured_key)} · {reason}",
            )
        # Server up, no shortcut configured — opt in with install-hotkey.
        return Check("hotkey", label, False, "System", detail="aparte install-hotkey")

    # No in-process state and no running server answered (CLI, app not started).
    if configured:
        return Check(
            "hotkey", label, False, "System",
            detail=f"{safe_hotkey_label(configured)} · start Aparté to activate it",
        )
    return Check("hotkey", label, False, "System", detail="aparte install-hotkey")


def _tray_check() -> Check:
    """The menu-bar icon check (macOS only).

    On Mac the icon is the only permanent sign that the microphone is open, so a tray
    that failed to appear must be sayable somewhere — silence there is the very defect
    M6 closes. Never essential: dictating from the browser or the shortcut still works.

    Its ``detail`` is DYNAMIC, so it carries NO ``check.tray.detail`` i18n key — the
    ``hotkey`` and ``config`` convention. The branches the web panel can reach are
    language-free (an install command, or the system's own error): the panel is served
    by the very process that built the tray, so it never lands on the English guidance
    line, which belongs to the CLI ``doctor`` running beside a started app.
    """
    from .macos_tray import MISSING_DEPENDENCY, tray_build_outcome

    label = "Menu-bar icon"
    # In-process (the resident server) the answer is right here; standing apart —
    # the CLI — ask a running server over its read-only route. Skipping that step
    # printed "start Aparté" under an icon that was on screen, which is the one
    # thing this check must never do.
    outcome = tray_build_outcome()
    if outcome is None:
        outcome = _query_tray_state()
    if outcome == "ok":
        return Check("menubar", label, True, "System", detail="rumps")
    if outcome is not None:
        fix = MISSING_DEPENDENCY if outcome == MISSING_DEPENDENCY else None
        return Check("menubar", label, False, "System", detail=outcome, fix=fix)
    # Nothing tried here: the CLI, standing beside the app rather than inside it.
    if not _has_module("rumps"):
        return Check("menubar", label, False, "System", detail=MISSING_DEPENDENCY, fix=MISSING_DEPENDENCY)
    return Check("menubar", label, False, "System", detail="rumps · start Aparté to show the icon")


def _query_tray_state() -> str | None:
    """CLI ``doctor``: ask a running server whether it built its menu-bar icon.

    Same shape as :func:`_query_hotkey_state` and for the same reason: the fact
    lives in the server's memory, and a second process can only ask. ``None`` when
    nothing answers (bounded, best-effort) — the check then falls back to what is
    installed. Never reached in-process, where the outcome is a local variable."""
    import json
    import urllib.request

    try:
        with urllib.request.urlopen("http://127.0.0.1:8765/api/tray-state", timeout=0.5) as response:
            payload = json.loads(response.read())
    except (OSError, ValueError):
        return None
    outcome = payload.get("outcome") if isinstance(payload, dict) else None
    return outcome if isinstance(outcome, str) else None


def _query_hotkey_state():
    """CLI ``doctor``: ask a running resident server for its shortcut state over
    the read-only route. Returns a :class:`~aparte.macos_hotkey.HotkeyState`, or
    ``None`` when nothing answers (bounded, best-effort) — ``doctor`` then falls
    back to a static reply from the config file. Only reached on macOS, where the
    shortcut lives in the resident server, and never in-process (the handler
    passes the state it owns). The default port matches the app's."""
    import json
    import urllib.request

    from .macos_hotkey import HotkeyState

    try:
        with urllib.request.urlopen("http://127.0.0.1:8765/api/hotkey-state", timeout=0.5) as response:
            payload = json.loads(response.read())
    except (OSError, ValueError):
        return None
    if not isinstance(payload, dict) or "registered" not in payload:
        return None
    return HotkeyState(
        registered=bool(payload.get("registered")),
        configured_key=payload.get("configured_key"),
        status=payload.get("status"),
        error=payload.get("error"),
    )


def _whisper_model_cached(settings: Settings) -> bool:
    """Use the same offline, exact-model verdict as native preparation."""
    from .model_download import model_cached

    return model_cached(settings)


def collect_diagnostics(settings: Settings, *, hotkey_state=None) -> dict:
    """Structured diagnostics for the desktop app and the CLI doctor.

    ``hotkey_state`` is forwarded to the macOS hotkey check (see
    :func:`collect_checks`); the resident desktop handler passes the state it owns
    so that check reads it in-process rather than self-requesting."""
    checks = collect_checks(settings, hotkey_state=hotkey_state)
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
