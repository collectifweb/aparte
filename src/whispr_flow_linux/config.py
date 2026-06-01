from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


APP_DIR_NAME = "whispr-flow"
CONFIG_FILE_NAME = "config.json"


DEFAULT_CONFIG: dict[str, Any] = {
    "transcriber": "auto",
    "recorder": "auto",
    "model": "small",
    "device": "auto",
    "compute_type": "auto",
    "language": None,
    "polish_backend": "heuristic",
    "default_style": "neutral",
    "cleanup_level": "medium",
    "ollama_url": "http://127.0.0.1:11434",
    "ollama_model": "llama3.1:8b",
    "whisper_cpp": None,
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
    ollama_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "llama3.1:8b"
    whisper_cpp: str | None = None
    replacements: dict[str, str] | None = None
    snippets: dict[str, str] | None = None
    config_path: Path | None = None

    @classmethod
    def from_env(cls) -> "Settings":
        config_path = get_config_path()
        config = load_config(config_path)
        language = os.getenv("WHISPR_LANGUAGE") or None
        whisper_cpp = os.getenv("WHISPR_WHISPER_CPP") or None
        replacements = _string_dict(config.get("replacements", DEFAULT_CONFIG["replacements"]))
        snippets = _string_dict(config.get("snippets", DEFAULT_CONFIG["snippets"]))
        return cls(
            transcriber=os.getenv("WHISPR_TRANSCRIBER", str(config.get("transcriber", "auto"))),
            recorder=os.getenv("WHISPR_RECORDER", str(config.get("recorder", "auto"))),
            model=os.getenv("WHISPR_MODEL", str(config.get("model", "small"))),
            device=os.getenv("WHISPR_DEVICE", str(config.get("device", "auto"))),
            compute_type=os.getenv("WHISPR_COMPUTE_TYPE", str(config.get("compute_type", "auto"))),
            language=language if language is not None else _optional_str(config.get("language")),
            polish_backend=os.getenv("WHISPR_POLISH_BACKEND", str(config.get("polish_backend", "heuristic"))),
            default_style=str(config.get("default_style", "neutral")),
            cleanup_level=str(config.get("cleanup_level", "medium")),
            ollama_url=os.getenv("WHISPR_OLLAMA_URL", str(config.get("ollama_url", DEFAULT_CONFIG["ollama_url"]))),
            ollama_model=os.getenv("WHISPR_OLLAMA_MODEL", str(config.get("ollama_model", DEFAULT_CONFIG["ollama_model"]))),
            whisper_cpp=whisper_cpp if whisper_cpp is not None else _optional_str(config.get("whisper_cpp")),
            replacements=replacements,
            snippets=snippets,
            config_path=config_path,
        )


def get_config_path() -> Path:
    override = os.getenv("WHISPR_CONFIG")
    if override:
        return Path(override).expanduser()
    xdg_config_home = os.getenv("XDG_CONFIG_HOME")
    if xdg_config_home:
        return Path(xdg_config_home).expanduser() / APP_DIR_NAME / CONFIG_FILE_NAME
    return Path.home() / ".config" / APP_DIR_NAME / CONFIG_FILE_NAME


def load_config(path: Path | None = None) -> dict[str, Any]:
    path = path or get_config_path()
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


def _string_dict(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {str(key): str(item) for key, item in value.items()}
