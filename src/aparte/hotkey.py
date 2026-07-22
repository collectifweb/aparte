"""Register a global keyboard shortcut that toggles Aparté dictation.

The Flow-like flow is one shortcut bound to ``aparte toggle``: press once to
start recording, press again to transcribe and insert into the focused app. The
binding itself lives in the desktop environment, not in a Aparté process, so it
survives reboots without a background daemon.

Cinnamon and GNOME expose custom keybindings through ``gsettings``, so this
module can register the shortcut automatically. The two desktops differ only in
schema names and in how the binding is typed (Cinnamon stores ``binding`` as an
array of strings, GNOME as a single string), which the provider table below
captures. Unsupported desktops get printable manual instructions instead.
"""

from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass

DEFAULT_KEY = "<Super>space"
DEFAULT_NAME = "Aparté dictation"
# Shortcut installed before the app was renamed from Murmur to Aparté. Matched so
# an existing binding is reused and relabelled instead of being duplicated.
LEGACY_NAME = "Murmur dictation"


def aparte_command(*args: str) -> list[str]:
    """Absolute command to invoke the Aparté CLI from a shortcut or launcher.

    Prefer the resolved ``aparte`` entry point so the shortcut keeps working
    outside the virtualenv; fall back to ``python -m aparte`` when it is not on
    PATH (e.g. an editable install that was never activated).
    """
    executable = shutil.which("aparte")
    if executable:
        return [executable, *args]
    return [sys.executable, "-m", "aparte", *args]


def command_string(command: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in command)


def toggle_command(target: str = "paste") -> str:
    return command_string(aparte_command("toggle", "--target", target))


def install_command() -> str:
    return command_string(aparte_command("install-hotkey"))


def detect_desktop() -> str:
    """Return a normalized desktop key: 'cinnamon', 'gnome', 'mate', or ''."""
    raw = (os.getenv("XDG_CURRENT_DESKTOP") or os.getenv("DESKTOP_SESSION") or "").lower()
    if "cinnamon" in raw:
        return "cinnamon"
    if "mate" in raw:
        return "mate"
    if "gnome" in raw or "unity" in raw:
        return "gnome"
    return ""


def key_label(key: str) -> str:
    """Turn a gsettings accelerator like ``<Super>space`` into ``Super+Space``."""
    mods = re.findall(r"<([^>]+)>", key)
    rest = re.sub(r"<[^>]+>", "", key).strip()
    pretty = {"primary": "Ctrl", "control": "Ctrl", "ctrl": "Ctrl", "super": "Super", "alt": "Alt", "shift": "Shift"}
    parts = [pretty.get(m.lower(), m.capitalize()) for m in mods]
    if rest:
        parts.append(rest.capitalize() if len(rest) > 1 else rest.upper())
    return "+".join(parts)


@dataclass(frozen=True)
class GsettingsProvider:
    """How a desktop stores custom keybindings in gsettings."""

    desktop: str
    parent_schema: str
    list_key: str  # holds the registered custom shortcuts
    child_schema: str  # relocatable schema for a single shortcut
    path_prefix: str  # dconf path the relocatable schema is bound to
    list_uses_paths: bool  # GNOME lists full dconf paths; Cinnamon lists slot names
    binding_is_array: bool  # Cinnamon: 'as'; GNOME: 's'


PROVIDERS = {
    "cinnamon": GsettingsProvider(
        desktop="cinnamon",
        parent_schema="org.cinnamon.desktop.keybindings",
        list_key="custom-list",
        child_schema="org.cinnamon.desktop.keybindings.custom-keybinding",
        path_prefix="/org/cinnamon/desktop/keybindings/custom-keybindings/",
        list_uses_paths=False,
        binding_is_array=True,
    ),
    "gnome": GsettingsProvider(
        desktop="gnome",
        parent_schema="org.gnome.settings-daemon.plugins.media-keys",
        list_key="custom-keybindings",
        child_schema="org.gnome.settings-daemon.plugins.media-keys.custom-keybinding",
        path_prefix="/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/",
        list_uses_paths=True,
        binding_is_array=False,
    ),
}


@dataclass(frozen=True)
class HotkeyResult:
    desktop: str
    slot: str
    command: str
    key: str


class HotkeyUnsupported(Exception):
    """Raised when no automatic backend is available for the current desktop."""

    def __init__(self, desktop: str, command: str, key: str) -> None:
        self.desktop = desktop
        self.command = command
        self.key = key
        super().__init__(f"automatic shortcut binding is not supported on {desktop or 'this desktop'}")

    def instructions(self) -> str:
        return manual_instructions(self.command, self.key, self.desktop)


def manual_instructions(command: str, key: str, desktop: str = "") -> str:
    where = {
        "cinnamon": "System Settings → Keyboard → Shortcuts → Custom Shortcuts",
        "gnome": "Settings → Keyboard → View and Customize Shortcuts → Custom Shortcuts",
        "mate": "Control Center → Keyboard Shortcuts",
    }.get(desktop, "your desktop's Keyboard → Shortcuts settings")
    return (
        "Bind the dictation shortcut manually:\n"
        f"  1. Open {where} and add a custom shortcut.\n"
        f"  2. Command: {command}\n"
        f"  3. Assign the key: {key_label(key)}\n"
        "Press it once to start dictating, again to transcribe and insert."
    )


def _provider() -> GsettingsProvider | None:
    if shutil.which("gsettings") is None:
        return None
    return PROVIDERS.get(detect_desktop())


def _gsettings(*args: str) -> str:
    result = subprocess.run(["gsettings", *args], check=True, capture_output=True, text=True)
    return result.stdout.strip()


def _parse_string_list(raw: str) -> list[str]:
    """Extract quoted strings from a gsettings array, dropping the empty sentinel."""
    return [s for s in re.findall(r"'([^']*)'", raw) if s and s != "__dummy__"]


def _format_list(entries: list[str]) -> str:
    if not entries:
        return "@as []"
    return "[" + ", ".join(_quote(e) for e in entries) + "]"


def _quote(value: str) -> str:
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


def _slot_path(provider: GsettingsProvider, slot: str) -> str:
    return f"{provider.path_prefix}{slot}/"


def _list_entry(provider: GsettingsProvider, slot: str) -> str:
    return _slot_path(provider, slot) if provider.list_uses_paths else slot


def _slot_of(provider: GsettingsProvider, entry: str) -> str:
    return entry.strip("/").rsplit("/", 1)[-1] if provider.list_uses_paths else entry


def _child(provider: GsettingsProvider, slot: str) -> str:
    return f"{provider.child_schema}:{_slot_path(provider, slot)}"


def _child_get(provider: GsettingsProvider, slot: str, key: str) -> str:
    return _gsettings("get", _child(provider, slot), key)


def _child_set(provider: GsettingsProvider, slot: str, key: str, value: str) -> None:
    _gsettings("set", _child(provider, slot), key, value)


def _binding_value(provider: GsettingsProvider, key: str) -> str:
    return _format_list([key]) if provider.binding_is_array else _quote(key)


def _next_free_slot(slots: list[str]) -> str:
    used = {int(m.group(1)) for s in slots if (m := re.fullmatch(r"custom(\d+)", s))}
    index = 0
    while index in used:
        index += 1
    return f"custom{index}"


def _is_aparte_slot(provider: GsettingsProvider, slot: str, name: str) -> bool:
    try:
        command = _child_get(provider, slot, "command")
        label = _child_get(provider, slot, "name")
    except subprocess.CalledProcessError:
        return False
    if "toggle" in command and ("aparte" in command or "murmur" in command):
        return True
    return _strip(label) in {name, LEGACY_NAME}


def _strip(raw: str) -> str:
    return raw.strip().strip("'\"")


def _current_slots(provider: GsettingsProvider) -> tuple[list[str], list[str]]:
    """Return (raw list entries, slot names) currently registered."""
    raw = _gsettings("get", provider.parent_schema, provider.list_key)
    entries = re.findall(r"'([^']*)'", raw)
    entries = [e for e in entries if e and e != "__dummy__"]
    return entries, [_slot_of(provider, e) for e in entries]


def install_hotkey(key: str | None = None, target: str = "paste", name: str = DEFAULT_NAME) -> HotkeyResult:
    """Register (or update) the global dictation shortcut for the current desktop.

    Re-runs reuse the existing Aparté slot instead of piling up duplicates. When
    ``key`` is None, an already-bound Aparté shortcut keeps its current
    accelerator (so a bare ``install-hotkey`` is non-destructive); only an
    explicit ``--key`` moves it. A reused slot also keeps whatever name the user
    gave it, unless it still carries the pre-rename default label.
    """
    command = toggle_command(target)
    provider = _provider()
    if provider is None:
        raise HotkeyUnsupported(detect_desktop(), command, key or DEFAULT_KEY)

    entries, slots = _current_slots(provider)
    slot = next((s for s in slots if _is_aparte_slot(provider, s, name)), None)
    is_new = slot is None
    if slot is None:
        slot = _next_free_slot(slots)
        resolved_key = key or DEFAULT_KEY
    else:
        resolved_key = key or _slot_binding(provider, slot) or DEFAULT_KEY

    if is_new or _strip(_child_get(provider, slot, "name")) == LEGACY_NAME:
        _child_set(provider, slot, "name", _quote(name))
    _child_set(provider, slot, "command", _quote(command))
    _child_set(provider, slot, "binding", _binding_value(provider, resolved_key))
    if is_new:
        _gsettings("set", provider.parent_schema, provider.list_key, _format_list(entries + [_list_entry(provider, slot)]))

    return HotkeyResult(desktop=provider.desktop, slot=slot, command=command, key=resolved_key)


def _slot_binding(provider: GsettingsProvider, slot: str) -> str | None:
    raw = _child_get(provider, slot, "binding")
    keys = _parse_string_list(raw) if provider.binding_is_array else [_strip(raw)]
    return keys[0] if keys and keys[0] else None


def remove_hotkey(name: str = DEFAULT_NAME) -> list[str]:
    """Remove any Aparté dictation shortcut. Returns the removed slot names."""
    provider = _provider()
    if provider is None:
        return []
    entries, slots = _current_slots(provider)
    removed = [s for s in slots if _is_aparte_slot(provider, s, name)]
    if not removed:
        return []
    kept = [entry for entry, slot in zip(entries, slots) if slot not in removed]
    _gsettings("set", provider.parent_schema, provider.list_key, _format_list(kept))
    for slot in removed:
        _gsettings("reset-recursively", _child(provider, slot))
    return removed


def current_binding(name: str = DEFAULT_NAME) -> str | None:
    """Return the key currently bound to Aparté, or None. Never raises."""
    try:
        provider = _provider()
        if provider is None:
            return None
        _, slots = _current_slots(provider)
        slot = next((s for s in slots if _is_aparte_slot(provider, s, name)), None)
        return _slot_binding(provider, slot) if slot is not None else None
    except Exception:
        return None


def hotkey_info() -> dict:
    """Shortcut status for the desktop diagnostics panel and `aparte doctor`."""
    desktop = detect_desktop()
    bound = current_binding()
    return {
        "desktop": desktop,
        "supported": _provider() is not None,
        "command": toggle_command("paste"),
        "install_command": install_command(),
        "default_key": DEFAULT_KEY,
        "default_key_label": key_label(DEFAULT_KEY),
        "bound_key": bound,
        "bound_key_label": key_label(bound) if bound else None,
    }
