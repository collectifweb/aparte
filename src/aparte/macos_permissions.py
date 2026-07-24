"""macOS privacy (TCC) probes: microphone authorization and Accessibility trust.

The first native PyObjC module in the project. It is imported only on Darwin
(from :func:`aparte.diagnostics._collect_checks_macos`) and every call degrades
to an "unknown" answer rather than raising: a diagnostic must never be the thing
that crashes ``aparte doctor``. Because this code cannot run on the Linux dev
machine, its real behaviour is verified by hand on a Mac; the unit tests here
only pin the mapping and the graceful-degradation contract by mocking the
frameworks.

Neither probe prompts the user. ``AXIsProcessTrusted`` is the no-dialog read;
the prompt-to-grant flow (``AXIsProcessTrustedWithOptions`` with the prompt
option, and opening the right Settings pane) belongs to the guided Accessibility
parcours in M3, not to a passive check.
"""

from __future__ import annotations

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
