from __future__ import annotations

import os
import shlex
import shutil
import sys
from pathlib import Path


DESKTOP_FILE_NAME = "murmur.desktop"
AUTOSTART_FILE_NAME = "murmur.desktop"
ICON_NAME = "murmur"
ASSETS_DIR = Path(__file__).resolve().parent / "assets"


def user_applications_dir() -> Path:
    xdg_data_home = os.getenv("XDG_DATA_HOME")
    if xdg_data_home:
        return Path(xdg_data_home).expanduser() / "applications"
    return Path.home() / ".local" / "share" / "applications"


def user_icon_path() -> Path:
    xdg_data_home = os.getenv("XDG_DATA_HOME")
    base = Path(xdg_data_home).expanduser() if xdg_data_home else Path.home() / ".local" / "share"
    return base / "icons" / "hicolor" / "scalable" / "apps" / f"{ICON_NAME}.svg"


def install_icon() -> Path | None:
    """Copy the app icon into the user hicolor theme so launchers can show it."""
    source = ASSETS_DIR / "logo.svg"
    if not source.exists():
        return None
    destination = user_icon_path()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(source.read_bytes())
    destination.chmod(0o644)
    return destination


def autostart_dir() -> Path:
    xdg_config_home = os.getenv("XDG_CONFIG_HOME")
    if xdg_config_home:
        return Path(xdg_config_home).expanduser() / "autostart"
    return Path.home() / ".config" / "autostart"


def default_exec_command() -> list[str]:
    executable = shutil.which("murmur")
    if executable:
        return [executable, "desktop"]
    return [sys.executable, "-m", "murmur", "desktop"]


def desktop_exec(command: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in command)


def build_desktop_entry(command: list[str] | None = None) -> str:
    command = command or default_exec_command()
    return "\n".join(
        [
            "[Desktop Entry]",
            "Type=Application",
            "Name=Murmur",
            "Comment=Local-first Linux dictation with Whisper and smart formatting",
            f"Exec={desktop_exec(command)}",
            f"Icon={ICON_NAME}",
            "Terminal=false",
            "Categories=Utility;Audio;Accessibility;",
            "StartupNotify=true",
            "",
        ]
    )


def install_desktop_entry(command: list[str] | None = None, force: bool = False) -> Path:
    install_icon()
    destination = user_applications_dir() / DESKTOP_FILE_NAME
    if destination.exists() and not force:
        raise FileExistsError(f"Desktop entry already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(build_desktop_entry(command), encoding="utf-8")
    destination.chmod(0o644)
    return destination


# XDG_CURRENT_DESKTOP tokens mapped to the keys the desktop UI has tailored
# shortcut-setup steps for. Matched case-insensitively as a substring, so
# "X-Cinnamon" → cinnamon and "ubuntu:GNOME" → gnome.
_DESKTOP_ENVIRONMENTS = {
    "cinnamon": "cinnamon",
    "gnome": "gnome",
    "plasma": "kde",
    "kde": "kde",
    "xfce": "xfce",
    "mate": "mate",
}


def detect_desktop_environment() -> str:
    """Best-effort normalized desktop-environment key, or "generic" if unknown."""
    raw = (os.getenv("XDG_CURRENT_DESKTOP") or os.getenv("DESKTOP_SESSION") or "").lower()
    for token, key in _DESKTOP_ENVIRONMENTS.items():
        if token in raw:
            return key
    return "generic"


def toggle_command(target: str = "paste") -> list[str]:
    """Command to bind to a global shortcut: first press records, second inserts."""
    executable = shutil.which("murmur")
    base = [executable] if executable else [sys.executable, "-m", "murmur"]
    return base + ["toggle", "--target", target]


def hotkey_guidance() -> dict:
    """Data for the desktop UI's global-shortcut setup card: the exact command to
    bind, the detected desktop environment, and which insertion target works."""
    is_wayland = bool(os.getenv("WAYLAND_DISPLAY"))
    is_x11 = bool(os.getenv("DISPLAY"))
    paste_ok = (shutil.which("wtype") is not None and is_wayland) or (
        shutil.which("xdotool") is not None and is_x11
    )
    target = "paste" if paste_ok else "copy"
    return {
        "command": desktop_exec(toggle_command(target)),
        "target": target,
        "paste_ok": paste_ok,
        "desktop_env": detect_desktop_environment(),
        "session_type": "wayland" if is_wayland else ("x11" if is_x11 else "unknown"),
    }


def default_autostart_command() -> list[str]:
    return default_exec_command() + ["--no-browser"]


def build_autostart_entry(command: list[str] | None = None) -> str:
    command = command or default_autostart_command()
    return "\n".join(
        [
            "[Desktop Entry]",
            "Type=Application",
            "Name=Murmur",
            "Comment=Start the Murmur desktop server at login",
            f"Exec={desktop_exec(command)}",
            "Terminal=false",
            "Categories=Utility;Audio;Accessibility;",
            "X-GNOME-Autostart-enabled=true",
            "StartupNotify=false",
            "",
        ]
    )


def install_autostart_entry(command: list[str] | None = None, force: bool = False) -> Path:
    destination = autostart_dir() / AUTOSTART_FILE_NAME
    if destination.exists() and not force:
        raise FileExistsError(f"Autostart entry already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(build_autostart_entry(command), encoding="utf-8")
    destination.chmod(0o644)
    return destination


def uninstall_autostart_entry() -> Path | None:
    destination = autostart_dir() / AUTOSTART_FILE_NAME
    if destination.exists():
        destination.unlink()
        return destination
    return None

