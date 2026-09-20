"""M7c — install the bundle, and refuse to break it by accident.

:mod:`aparte.macos_desktop` knows how to *describe* a bundle. This module puts one
in ``~/Applications``, and guards the one thing that matters afterwards: the code's
fingerprint. An ad-hoc signature has no team identity, so the requirement macOS
stores against the granted permissions is the ``cdhash``. Replace the bundle with a
different one and the permissions are silently gone — the checkbox in System
Settings stays ticked, which is what makes it silent.

So the install is **idempotent by fingerprint**, not by presence: it builds into a
staging directory, signs it, compares, and only moves it into place when something
actually changed. When it did change and a bundle was already there, it stops and
says what the user will lose, rather than reporting success and letting them find
out at the next dictation.

``codesign`` is a hard prerequisite. A badly signed bundle presented as installed is
worse than no install at all, and Apple Silicon refuses to run unsigned native code.

Two choices are still open, and they live at the top of this module as named
constants: which launcher variant, and ad-hoc versus a local certificate. M7-0
measures both on a real Mac (`.claude/mac-validation/m7/`); applying its verdict is
a one-line change here, deliberately, so nobody has to go hunting.
"""

from __future__ import annotations

import re
import fcntl
import os
import shutil
import stat
import subprocess
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from . import macos_desktop
from .config import _config_home, APP_DIR_NAME

# --- ce que M7-0 doit confirmer -------------------------------------------------
# La variante du lanceur. `exec` est le choix par défaut parce qu'il est le plus
# simple ; M7-0 dira si macOS attribue l'autorisation de la même façon quand le
# processus du lanceur a disparu. Si la réponse est non, cette ligne devient
# LAUNCH_CHILD et rien d'autre ne bouge.
INSTALL_MODE = macos_desktop.LAUNCH_EXEC
# L'identité de signature. « - » est l'ad-hoc. Le scénario C de M7-0 dira s'il faut
# un certificat local à la place ; ce serait alors son nom dans le trousseau.
INSTALL_IDENTITY = "-"
# --------------------------------------------------------------------------------

CDHASH_FILE = "bundle-cdhash"
_CDHASH = re.compile(r"^CDHash=([0-9a-f]+)", re.MULTILINE | re.IGNORECASE)
_LOCK_TIMEOUT_SECONDS = 5.0


class InstallError(RuntimeError):
    """Anything that must stop the install with a non-zero exit code."""


def cdhash_reference_path() -> Path:
    """Where the fingerprint of the installed bundle is remembered.

    **Outside** the bundle. Writing it inside would change the very thing it claims
    to be watching — the bundle would no longer match its own recorded hash.
    """
    return _config_home() / APP_DIR_NAME / CDHASH_FILE


def read_cdhash(bundle: Path) -> str | None:
    """The signed code's fingerprint, or None when it cannot be read.

    ``codesign -dvvv`` writes it on **stderr**, which is why both streams are read.
    """
    try:
        done = subprocess.run(
            ["codesign", "-dvvv", str(bundle)], capture_output=True, text=True, timeout=30
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if done.returncode != 0:
        return None
    found = _CDHASH.search(done.stdout + "\n" + done.stderr)
    return found.group(1).lower() if found else None


def _run(command: list[str]) -> None:
    try:
        done = subprocess.run(command, capture_output=True, text=True, timeout=300)
    except FileNotFoundError as exc:
        raise InstallError(f"{command[0]} not found — run: xcode-select --install") from exc
    except (OSError, subprocess.SubprocessError) as exc:
        raise InstallError(f"{command[0]} failed: {exc}") from exc
    if done.returncode != 0:
        detail = (done.stderr or done.stdout).strip().splitlines()
        raise InstallError(f"{command[0]} failed: {detail[-1] if detail else done.returncode}")


def _build(staging: Path, interpreter: str, mode: str, identity: str) -> Path:
    """Build, compile and sign a complete bundle inside `staging`. Returns it."""
    bundle = staging / macos_desktop.BUNDLE_NAME
    paths = macos_desktop.write_bundle(bundle, interpreter, mode=mode)
    _run(macos_desktop.clang_command(paths["source"], paths["executable"]))
    # The C source has no business in a shipped bundle — and it would be signed with
    # the rest, so leaving it in would make the fingerprint depend on it.
    paths["source"].unlink()
    signature = macos_desktop.codesign_command(bundle)
    if identity != "-":
        signature[signature.index("-", 2)] = identity
    _run(signature)
    _verify_signature(bundle)
    return bundle


def _verify_signature(bundle: Path) -> None:
    # Reading a CDHash merely describes a signature, including one whose sealed
    # resources were modified. Verification must check the actual bundle.
    _run(["codesign", "--verify", "--deep", "--strict", str(bundle)])


@contextmanager
def _installation_lock(destination: Path) -> Iterator[None]:
    """Serialize install and removal; this stable lock is never unlinked."""
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(destination.parent / ".aparte-install.lock",
                 os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK,
                 0o600)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or info.st_nlink != 1):
            raise InstallError("Invalid application installation lock")
        os.fchmod(fd, 0o600)
        deadline = time.monotonic() + _LOCK_TIMEOUT_SECONDS
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise InstallError("Another Aparté installation or removal is in progress; retry later")
                time.sleep(0.02)
        yield
    finally:
        os.close(fd)


def install_app(
    interpreter: str,
    *,
    force: bool = False,
    mode: str = INSTALL_MODE,
    identity: str = INSTALL_IDENTITY,
) -> dict:
    """Put ``Aparté.app`` in ``~/Applications``, or explain why it stopped.

    Returns ``{"outcome": …, "bundle": Path, "cdhash": str}`` where outcome is
    ``installed`` (there was nothing there), ``unchanged`` (same fingerprint, nothing
    to do) or ``replaced`` (different fingerprint, and ``force`` allowed it).

    Raises :class:`InstallError` when the fingerprint differs and ``force`` is not
    set — that is the case where finishing the job would cost the user their granted
    permissions without warning.
    """
    destination = macos_desktop.bundle_path()
    with _installation_lock(destination):
        if destination.is_symlink():
            raise InstallError("The installed application is a symbolic link; refusing to replace it")
        # Same parent means every publication/rollback rename stays on one volume.
        staging = Path(tempfile.mkdtemp(prefix=".aparte-install-", dir=destination.parent))
        backup = staging / "previous.app"
        try:
            fresh = _build(staging, interpreter, mode, identity)
            fingerprint = read_cdhash(fresh)
            if fingerprint is None:
                raise InstallError(
                    "the freshly signed bundle has no readable fingerprint — refusing to "
                    "install something codesign cannot describe"
                )

            installed = None
            if destination.exists():
                try:
                    _verify_signature(destination)
                    installed = read_cdhash(destination)
                except InstallError:
                    pass
            if installed is not None and installed == fingerprint:
                _remember(fingerprint)
                return {"outcome": "unchanged", "bundle": destination, "cdhash": fingerprint}
            if destination.exists() and not force:
                raise InstallError(
                    "the installed Aparté.app is not the one this version would build "
                    f"({installed or 'unreadable'} → {fingerprint}). Replacing it makes macOS "
                    "forget the microphone and Accessibility permissions — and the checkboxes "
                    "in System Settings stay ticked, so nothing will look wrong. "
                    "Re-run with --force to replace it and grant them again."
                )

            outcome = "replaced" if destination.exists() else "installed"
            if destination.exists():
                destination.rename(backup)
            try:
                fresh.rename(destination)
                _verify_signature(destination)
                if read_cdhash(destination) != fingerprint:
                    raise InstallError("Installed application fingerprint differs from the verified build")
            except (OSError, InstallError) as failure:
                try:
                    if destination.exists():
                        destination.rename(staging / "failed.app")
                    if backup.exists():
                        backup.rename(destination)
                except OSError as restore_error:
                    # Never let temporary-directory cleanup delete the only
                    # surviving old application when rollback itself fails.
                    raise InstallError(
                        f"Installation failed and could not restore the previous application. "
                        f"Its backup is kept at {backup}: {restore_error}"
                    ) from failure
                raise InstallError(f"Installation failed; previous application preserved: {failure}") from failure

            _remember(fingerprint)
            if backup.exists():
                # Publication and verification succeeded. Failure to retire the
                # backup must not invalidate a usable installed application.
                try:
                    shutil.rmtree(backup)
                except OSError:
                    pass
            return {"outcome": outcome, "bundle": destination, "cdhash": fingerprint}
        finally:
            if not backup.exists():
                shutil.rmtree(staging, ignore_errors=True)


def _remember(fingerprint: str) -> None:
    path = cdhash_reference_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(fingerprint + "\n", encoding="utf-8")
    except OSError:
        pass  # informational only: the bundle itself is the truth


def uninstall_app() -> bool:
    """Remove the bundle and forget its fingerprint. True when something was there.

    Needed because the bundle lives outside the Homebrew prefix — deliberately, so
    ``brew upgrade`` cannot rebuild it — which also means ``brew uninstall`` leaves
    it behind.
    """
    destination = macos_desktop.bundle_path()
    with _installation_lock(destination):
        if destination.is_symlink():
            raise InstallError("The installed application is a symbolic link; refusing to remove it")
        existed = destination.exists()
        if existed:
            shutil.rmtree(destination)
        reference = cdhash_reference_path()
        reference.unlink(missing_ok=True)
        return existed


def open_app() -> None:
    """Ask LaunchServices to start it — never the launcher directly.

    Running the executable by hand would make *this* process the responsible one,
    and the whole point of the bundle is that LaunchServices is.
    """
    _run(["/usr/bin/open", "-a", str(macos_desktop.bundle_path())])


def installed_state() -> dict:
    """What `doctor` reports: is a bundle there, and does it still match its record?

    A mismatch is worth naming even though nothing here can fix it — it is exactly
    the state where the permissions are gone while System Settings still shows them
    granted.
    """
    destination = macos_desktop.bundle_path()
    if not destination.exists():
        return {"installed": False, "matches_reference": None, "cdhash": None}
    fingerprint = read_cdhash(destination)
    reference = None
    try:
        reference = cdhash_reference_path().read_text(encoding="utf-8").strip() or None
    except OSError:
        pass
    matches = None if (fingerprint is None or reference is None) else fingerprint == reference
    return {"installed": True, "matches_reference": matches, "cdhash": fingerprint}
