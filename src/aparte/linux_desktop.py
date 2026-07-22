from __future__ import annotations

import os
import shlex
import shutil
import sys
from pathlib import Path


DESKTOP_FILE_NAME = "aparte.desktop"
AUTOSTART_FILE_NAME = "aparte.desktop"
ICON_NAME = "aparte"
ASSETS_DIR = Path(__file__).resolve().parent / "assets"

# Files written before the app was renamed from Murmur to Aparté. They are
# removed on install, otherwise the menu shows two entries and — worse — two
# autostart entries race for the same port at login.
LEGACY_DESKTOP_FILE_NAME = "murmur.desktop"
LEGACY_ICON_NAME = "murmur"


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
    executable = shutil.which("aparte")
    if executable:
        return [executable, "desktop"]
    return [sys.executable, "-m", "aparte", "desktop"]


def desktop_exec(command: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in command)


def build_desktop_entry(command: list[str] | None = None) -> str:
    command = command or default_exec_command()
    return "\n".join(
        [
            "[Desktop Entry]",
            "Type=Application",
            "Name=Aparté",
            "Comment=Local-first Linux dictation with Whisper and smart formatting",
            f"Exec={desktop_exec(command)}",
            f"Icon={ICON_NAME}",
            "Terminal=false",
            "Categories=Utility;Audio;Accessibility;",
            "StartupNotify=true",
            "",
        ]
    )


def remove_legacy_entries() -> list[Path]:
    """Delete the pre-rename launcher, icon, and autostart entry. Best-effort."""
    removed = []
    candidates = [
        user_applications_dir() / LEGACY_DESKTOP_FILE_NAME,
        autostart_dir() / LEGACY_DESKTOP_FILE_NAME,
        user_icon_path().with_name(f"{LEGACY_ICON_NAME}.svg"),
    ]
    for path in candidates:
        try:
            if path.exists():
                path.unlink()
                removed.append(path)
        except OSError:
            pass
    return removed


def install_desktop_entry(command: list[str] | None = None, force: bool = False) -> Path:
    install_icon()
    remove_legacy_entries()
    destination = user_applications_dir() / DESKTOP_FILE_NAME
    if destination.exists() and not force:
        raise FileExistsError(f"Desktop entry already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(build_desktop_entry(command), encoding="utf-8")
    destination.chmod(0o644)
    return destination


def default_autostart_command() -> list[str]:
    return default_exec_command() + ["--no-browser"]


def build_autostart_entry(command: list[str] | None = None) -> str:
    command = command or default_autostart_command()
    return "\n".join(
        [
            "[Desktop Entry]",
            "Type=Application",
            "Name=Aparté",
            "Comment=Start the Aparté desktop server at login",
            f"Exec={desktop_exec(command)}",
            "Terminal=false",
            "Categories=Utility;Audio;Accessibility;",
            "X-GNOME-Autostart-enabled=true",
            "StartupNotify=false",
            "",
        ]
    )


def install_autostart_entry(command: list[str] | None = None, force: bool = False) -> Path:
    remove_legacy_entries()
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

