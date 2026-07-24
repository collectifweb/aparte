"""macOS privacy (TCC) probes: microphone authorization and Accessibility trust.

The first native PyObjC module in the project. It is imported only on Darwin
(from :func:`aparte.diagnostics._collect_checks_macos`) and every call degrades
to an "unknown" answer rather than raising: a diagnostic must never be the thing
that crashes ``aparte doctor``. Because this code cannot run on the Linux dev
machine, its real behaviour is verified by hand on a Mac; the unit tests here
only pin the mapping and the graceful-degradation contract by mocking the
frameworks.

The two *probes* — :func:`microphone_authorization` and
:func:`accessibility_trusted` — never prompt: they are the no-dialog reads used
by diagnostics. The *guided Accessibility parcours* (M3) does prompt:
:func:`guide_accessibility_once` shows the grant dialog and opens the Settings
pane, and is called by :func:`aparte.clipboard.paste_text` when insertion needs
Accessibility and it is known-denied.
"""

from __future__ import annotations

import subprocess

# AVAuthorizationStatus, as returned by AVCaptureDevice: the raw enum is an int,
# and we translate it to a stable string so callers never depend on PyObjC.
_MIC_STATUS = {
    0: "not_determined",
    1: "restricted",
    2: "denied",
    3: "authorized",
}


def microphone_authorization() -> str:
    """The Microphone TCC status: one of the :data:`_MIC_STATUS` values, or
    ``"unknown"`` when AVFoundation cannot be reached (not a Mac, framework
    missing, or an unexpected enum value)."""
    try:
        import AVFoundation

        status = AVFoundation.AVCaptureDevice.authorizationStatusForMediaType_(
            AVFoundation.AVMediaTypeAudio
        )
    except Exception:
        return "unknown"
    try:
        return _MIC_STATUS.get(int(status), "unknown")
    except (TypeError, ValueError):
        return "unknown"


def accessibility_trusted() -> bool | None:
    """Whether this process is trusted for Accessibility (needed to synthesise
    the Cmd+V paste in M3). ``True``/``False`` when known, ``None`` when the API
    is unreachable. Reads without prompting — the grant dialog is an M3 concern."""
    trusted = None
    for module_name in ("ApplicationServices", "HIServices"):
        try:
            module = __import__(module_name, fromlist=["AXIsProcessTrusted"])
            trusted = module.AXIsProcessTrusted
            break
        except Exception:
            continue
    if trusted is None:
        return None
    try:
        return bool(trusted())
    except Exception:
        return None


# The Accessibility pane of System Settings, addressed by URL scheme.
_ACCESSIBILITY_PANE = (
    "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"
)

# Anti-spam: the guided parcours runs at most once per process, so a user who
# declines Accessibility on purpose is not nagged on every failed insertion. A
# plain module flag is enough — no persistence, the next launch offers it again.
_guided_this_process = False


def prompt_accessibility() -> bool | None:
    """Ask macOS to prompt for Accessibility trust: this registers the process in
    the Accessibility list and shows the grant dialog once. Returns the trust
    state (``True``/``False``), or ``None`` when the API is unreachable. Unlike
    :func:`accessibility_trusted`, this one *prompts* — it belongs to the guided
    flow, never to a passive check."""
    for module_name in ("ApplicationServices", "HIServices"):
        try:
            module = __import__(
                module_name,
                fromlist=["AXIsProcessTrustedWithOptions", "kAXTrustedCheckOptionPrompt"],
            )
            options = {module.kAXTrustedCheckOptionPrompt: True}
            return bool(module.AXIsProcessTrustedWithOptions(options))
        except Exception:
            continue
    return None


def open_accessibility_settings() -> bool:
    """Open System Settings on the Accessibility pane. Returns ``True`` if the
    ``open`` command was launched, ``False`` otherwise. Never raises."""
    try:
        subprocess.run(["open", _ACCESSIBILITY_PANE], check=False)
        return True
    except Exception:
        return False


def guide_accessibility_once() -> None:
    """The guided Accessibility parcours: prompt for trust and open the Settings
    pane — but only the first time in this process (see :data:`_guided_this_process`)."""
    global _guided_this_process
    if _guided_this_process:
        return
    _guided_this_process = True
    prompt_accessibility()
    open_accessibility_settings()
