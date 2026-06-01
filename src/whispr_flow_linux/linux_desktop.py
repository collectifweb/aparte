from __future__ import annotations

import os
import shlex
import shutil
import sys
from pathlib import Path


DESKTOP_FILE_NAME = "whispr-flow-linux.desktop"
AUTOSTART_FILE_NAME = "whispr-flow-linux.desktop"


def user_applications_dir() -> Path:
    xdg_data_home = os.getenv("XDG_DATA_HOME")
    if xdg_data_home:
        return Path(xdg_data_home).expanduser() / "applications"
    return Path.home() / ".local" / "share" / "applications"


def autostart_dir() -> Path:
    xdg_config_home = os.getenv("XDG_CONFIG_HOME")
    if xdg_config_home:
        return Path(xdg_config_home).expanduser() / "autostart"
    return Path.home() / ".config" / "autostart"


def default_exec_command() -> list[str]:
    executable = shutil.which("whispr-flow")
    if executable:
        return [executable, "desktop"]
    return [sys.executable, "-m", "whispr_flow_linux", "desktop"]


def desktop_exec(command: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in command)


def build_desktop_entry(command: list[str] | None = None) -> str:
    command = command or default_exec_command()
    return "\n".join(
        [
            "[Desktop Entry]",
            "Type=Application",
            "Name=Whispr Flow Linux",
            "Comment=Local-first Linux dictation with Whisper and smart formatting",
            f"Exec={desktop_exec(command)}",
            "Terminal=false",
            "Categories=Utility;Audio;Accessibility;",
            "StartupNotify=true",
            "",
        ]
    )


def install_desktop_entry(command: list[str] | None = None, force: bool = False) -> Path:
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
            "Name=Whispr Flow Linux",
            "Comment=Start the Whispr Flow desktop server at login",
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

