from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


APP_DIR_NAME = "aparte"
CONFIG_FILE_NAME = "config.json"

# The app was renamed from Murmur to Aparté. Existing installs still keep their
# config under the old directory and may still export the old variable names.
LEGACY_APP_DIR_NAME = "murmur"
LEGACY_ENV_PREFIX = "MURMUR_"


DEFAULT_CONFIG: dict[str, Any] = {
    "transcriber": "auto",
    "recorder": "auto",
    "model": "small",
    "device": "auto",
    "compute_type": "auto",
    # Français d'abord, et pas seulement par positionnement : sans langue
    # imposée, Whisper lance une détection qui se trompe sur un audio pauvre et
    # déroule la dictée dans une autre langue.
    "language": "fr",
    "polish_backend": "heuristic",
    "default_style": "neutral",
    "cleanup_level": "medium",
    "nonbreaking_spaces": True,
    "trailing_space": False,
    "numbers_from": 10,
    "short_text_words": 0,
    "paste_mode": "clipboard",
    "history_persist": False,
    "microphone": "",
    "beep": False,
    "live_preview": True,
    "max_recording_seconds": 300,
    "ollama_url": "http://127.0.0.1:11434",
    "ollama_model": "llama3.1:8b",
    "whisper_cpp": None,
    "hotwords": [],
    "replacements": {
        "whisper flow": "Wispr Flow",
        "wispr flow": "Wispr Flow",
        "pipe wire": "PipeWire",
        "way land": "Wayland",
    },
    "snippets": {
        "signature": "Best,\nAlexandre",
    },
}


@dataclass(frozen=True)
class Settings:
    transcriber: str = "auto"
    recorder: str = "auto"
    model: str = "small"
    device: str = "auto"
    compute_type: str = "auto"
    language: str | None = None
    polish_backend: str = "heuristic"
    default_style: str = "neutral"
    cleanup_level: str = "medium"
    nonbreaking_spaces: bool = True
    trailing_space: bool = False
    numbers_from: int = 10
    short_text_words: int = 0
    paste_mode: str = "clipboard"
    history_persist: bool = False
    microphone: str = ""
    beep: bool = False
    live_preview: bool = True
    max_recording_seconds: int = 300
    ollama_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "llama3.1:8b"
    whisper_cpp: str | None = None
    hotwords: tuple[str, ...] = ()
    replacements: dict[str, str] | None = None
    snippets: dict[str, str] | None = None
    config_path: Path | None = None

    @classmethod
    def from_env(cls) -> "Settings":
        migrate_legacy_config()
        config_path = get_config_path()
        config = load_config(config_path)
        language = get_env("LANGUAGE")
        whisper_cpp = get_env("WHISPER_CPP")
        replacements = _string_dict(config.get("replacements", DEFAULT_CONFIG["replacements"]))
        snippets = _string_dict(config.get("snippets", DEFAULT_CONFIG["snippets"]))
        return cls(
            transcriber=get_env("TRANSCRIBER") or str(config.get("transcriber", "auto")),
            recorder=get_env("RECORDER") or str(config.get("recorder", "auto")),
            model=get_env("MODEL") or str(config.get("model", "small")),
            device=get_env("DEVICE") or str(config.get("device", "auto")),
            compute_type=get_env("COMPUTE_TYPE") or str(config.get("compute_type", "auto")),
            language=language if language is not None else _optional_str(config.get("language")),
            polish_backend=get_env("POLISH_BACKEND") or str(config.get("polish_backend", "heuristic")),
            default_style=str(config.get("default_style", "neutral")),
            cleanup_level=str(config.get("cleanup_level", "medium")),
            nonbreaking_spaces=bool(config.get("nonbreaking_spaces", True)),
            trailing_space=bool(config.get("trailing_space", False)),
            numbers_from=positive_int(config.get("numbers_from", 10)),
            short_text_words=positive_int(config.get("short_text_words")),
            paste_mode=get_env("PASTE_MODE") or str(config.get("paste_mode", "clipboard")),
            history_persist=bool(config.get("history_persist", False)),
            microphone=get_env("MICROPHONE") or str(config.get("microphone", "") or ""),
            beep=bool(config.get("beep", False)),
            live_preview=bool(config.get("live_preview", True)),
            # Pas de « 0 = illimité » : `positive_int` rend 0 sur une valeur
            # illisible, et une faute de frappe rouvrirait le micro sans fin.
            # Qui veut deux heures écrit 7200.
            max_recording_seconds=positive_int(config.get("max_recording_seconds", 300)) or 300,
            ollama_url=get_env("OLLAMA_URL") or str(config.get("ollama_url", DEFAULT_CONFIG["ollama_url"])),
            ollama_model=get_env("OLLAMA_MODEL") or str(config.get("ollama_model", DEFAULT_CONFIG["ollama_model"])),
            whisper_cpp=whisper_cpp if whisper_cpp is not None else _optional_str(config.get("whisper_cpp")),
            hotwords=_string_list(config.get("hotwords", DEFAULT_CONFIG["hotwords"])),
            replacements=replacements,
            snippets=snippets,
            config_path=config_path,
        )


def get_env(name: str) -> str | None:
    """Read ``APARTE_<name>``, falling back to the pre-rename ``MURMUR_<name>``."""
    return os.getenv(f"APARTE_{name}") or os.getenv(f"{LEGACY_ENV_PREFIX}{name}") or None


def get_config_path() -> Path:
    override = get_env("CONFIG")
    if override:
        return Path(override).expanduser()
    return _config_home() / APP_DIR_NAME / CONFIG_FILE_NAME


def get_legacy_config_path() -> Path:
    return _config_home() / LEGACY_APP_DIR_NAME / CONFIG_FILE_NAME


def _config_home() -> Path:
    xdg_config_home = os.getenv("XDG_CONFIG_HOME")
    if xdg_config_home:
        return Path(xdg_config_home).expanduser()
    return Path.home() / ".config"


def migrate_legacy_config() -> Path | None:
    """Move a pre-rename ``murmur`` config over to the ``aparte`` location.

    Only acts on the default path, and only when nothing is there yet, so an
    explicit path (tests, ``APARTE_CONFIG``) is never a migration target.
    Returns the new path when a file was moved.
    """
    path = get_config_path()
    if path.exists() or path != _config_home() / APP_DIR_NAME / CONFIG_FILE_NAME:
        return None
    legacy = get_legacy_config_path()
    if not legacy.exists():
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    legacy.replace(path)
    return path


def load_config(path: Path | None = None) -> dict[str, Any]:
    if path is None:
        migrate_legacy_config()
        path = get_config_path()
    if not path.exists():
        return DEFAULT_CONFIG.copy()
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"Config file must contain a JSON object: {path}")
    merged = DEFAULT_CONFIG.copy()
    merged.update(data)
    return merged


def write_default_config(path: Path | None = None, force: bool = False) -> Path:
    path = path or get_config_path()
    if path.exists() and not force:
        raise FileExistsError(f"Config already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(DEFAULT_CONFIG, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    return path


def update_config(updates: dict[str, Any], path: Path | None = None) -> dict[str, Any]:
    """Merge ``updates`` into the existing config file and write it back.

    Returns the merged config that was written. Unknown keys are ignored so the
    settings form can only touch fields that the app understands.
    """
    path = path or get_config_path()
    data = DEFAULT_CONFIG.copy()
    if path.exists():
        with path.open("r", encoding="utf-8") as handle:
            existing = json.load(handle)
        if isinstance(existing, dict):
            data.update(existing)
    for key, value in updates.items():
        if key in DEFAULT_CONFIG:
            data[key] = value
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    return data


def _optional_str(value: object) -> str | None:
    if value in {None, ""}:
        return None
    return str(value)


def positive_int(value: object) -> int:
    """A count coming from a config file or a form; anything odd means "off"."""
    try:
        return max(0, int(value))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


def _string_list(value: object) -> tuple[str, ...]:
    """The user's own vocabulary, one entry per line in the settings drawer.

    Blank lines are dropped rather than passed on: an empty hotword would bias
    Whisper toward nothing in particular, and a trailing newline is the normal
    way a textarea ends.
    """
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(str(item).strip() for item in value if str(item).strip())


def _string_dict(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {str(key): str(item) for key, item in value.items()}
