"""OS detection and the seam that routes to OS-specific backends.

Aparté is Linux-first. This module is the single place that answers "which OS
are we on" and picks the OS-specific implementation of a feature. In M0 the only
seam wired here is the ``*_desktop`` family (launcher + autostart); the mixed
modules (clipboard, notify, audio) branch in place in later lots, and the macOS
implementations do not exist yet.

Detection reads ``sys.platform`` at call time on purpose: tests can simulate any
OS by patching ``aparte.platform_dispatch.sys.platform`` without leaving a stale
module-level flag behind.
"""

from __future__ import annotations

import sys


class UnsupportedPlatformError(RuntimeError):
    """Raised when a feature has no implementation for the current OS."""


def is_macos() -> bool:
    return sys.platform == "darwin"


def is_linux() -> bool:
    return sys.platform.startswith("linux")  # linux, linux2


def desktop_integration():
    """Return the OS-specific launcher/autostart backend (the ``*_desktop`` family).

    Linux returns the existing :mod:`aparte.linux_desktop` module unchanged.
    Every other OS raises: there is no per-OS branch and no ``macos_*`` module to
    import yet. The import stays inside the Linux branch so a non-Linux caller
    never touches a module it cannot use.
    """
    if is_linux():
        from . import linux_desktop

        return linux_desktop
    raise UnsupportedPlatformError(
        "Desktop integration (launcher and autostart) is available on Linux only "
        "for now. On other systems, run `aparte desktop` to use browser dictation."
    )
