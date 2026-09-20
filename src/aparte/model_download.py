"""Prepare speech models from native actions; HTTP only observes this state.

A directory is not a downloaded model. Diagnostics and the recorder share the
same conservative check of the exact repository and its default revision.
"""
from __future__ import annotations

import importlib.util
import os
import threading
from pathlib import Path

from .config import Settings

# Fallback for diagnostics without faster-whisper installed. Prefer its installed
# resolver so preparation and inference follow the same version's aliases.
_MODEL_REPOS = {
    **{size: f"Systran/faster-whisper-{size}" for size in (
        "tiny", "tiny.en", "base", "base.en", "small", "small.en", "medium",
        "medium.en", "large-v1", "large-v2", "large-v3",
    )},
    "large": "Systran/faster-whisper-large-v3",
    **{size: f"Systran/faster-{size.replace('distil-', 'distil-whisper-')}" for size in (
        "distil-large-v2", "distil-medium.en", "distil-small.en", "distil-large-v3",
    )},
    "distil-large-v3.5": "distil-whisper/distil-large-v3.5-ct2",
    "turbo": "mobiuslabsgmbh/faster-whisper-large-v3-turbo",
    "large-v3-turbo": "mobiuslabsgmbh/faster-whisper-large-v3-turbo",
}
_ALLOW_PATTERNS = ["config.json", "preprocessor_config.json", "model.bin", "tokenizer.json", "vocabulary.*"]
READY = "ready"
DOWNLOADING = "downloading"
ERROR = "error"
UNAVAILABLE = "unavailable"
_lock = threading.Lock()
_state: dict | None = None
_thread: threading.Thread | None = None


def _has_module(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def effective_backend(settings: Settings) -> str:
    """Match auto's first installed engine, without loading any weights."""
    if settings.transcriber != "auto":
        return settings.transcriber
    if _has_module("faster_whisper"):
        return "faster-whisper"
    if _has_module("whisper"):
        return "openai-whisper"
    return "whisper.cpp"


def _local_path(model: str) -> bool:
    return Path(model).expanduser().exists() or model.startswith(("/", "./", "../", "~"))


def repo_id(model: str) -> str | None:
    model = (model or "").strip()
    if not model or _local_path(model):
        return None
    if "/" in model:
        return model
    try:
        from faster_whisper.utils import _MODELS
        models = _MODELS
    except Exception:
        # Importing utils executes faster-whisper's package initializer, which
        # can fail in a native dependency (for example an incompatible
        # ctranslate2 dylib). Alias lookup must not prevent the desktop from
        # starting and showing diagnostics. Inference will report engine errors.
        models = _MODEL_REPOS
    return models.get(model)


def cache_root() -> Path:
    hub = os.getenv("HF_HUB_CACHE") or os.getenv("HUGGINGFACE_HUB_CACHE")
    if hub:
        return Path(os.path.expandvars(hub)).expanduser()
    home = os.getenv("HF_HOME")
    if home:
        return Path(os.path.expandvars(home)).expanduser() / "hub"
    return Path(os.getenv("XDG_CACHE_HOME") or Path.home() / ".cache").expanduser() / "huggingface" / "hub"


def repo_dir(repo: str) -> Path:
    return cache_root() / ("models--" + repo.replace("/", "--"))


def _nonempty(path: Path) -> bool:
    try:
        return path.is_file() and path.stat().st_size > 0
    except OSError:
        return False


def _complete_model(path: Path) -> bool:
    """Required files only; model loading still validates their contents.

    A dangling cache symlink and a zero-byte interrupted file both fail. Include
    the tokenizer so an otherwise cached model cannot fetch it during dictation.
    """
    return all(_nonempty(path / name) for name in ("config.json", "model.bin", "tokenizer.json")) and any(
        _nonempty(path / name) for name in ("vocabulary.json", "vocabulary.txt")
    )


def _cached_repo_path(repo: str) -> Path | None:
    root = repo_dir(repo)
    try:
        revision = (root / "refs" / "main").read_text().strip()
    except OSError:
        return None
    if not revision or Path(revision).name != revision or revision in (".", ".."):
        return None
    path = root / "snapshots" / revision
    return path.absolute() if _complete_model(path) else None


def _cached_repo(repo: str) -> bool:
    return _cached_repo_path(repo) is not None


def cached_model_path(model: str) -> Path | None:
    """Resolve a complete faster-whisper model locally, without any Hub call.

    Inference receives this directory instead of a Hub alias, preventing its
    constructor from starting another model download through an HTTP request.
    """
    model = (model or "").strip()
    if not model:
        return None
    if _local_path(model):
        path = Path(model).expanduser()
        return path.absolute() if _complete_model(path) else None
    repo = repo_id(model)
    return _cached_repo_path(repo) if repo else None


def model_cached(settings: Settings) -> bool:
    """Offline, backend-specific evidence. Never inspect a similarly named repo."""
    model = (settings.model or "").strip()
    if not model:
        return False
    backend = effective_backend(settings)
    path = Path(model).expanduser()
    if backend == "faster-whisper":
        return cached_model_path(model) is not None
    if backend == "whisper.cpp":
        return _nonempty(path)
    if backend == "openai-whisper":
        # Whisper writes a named .pt directly, including partial downloads. Only
        # its checksum proves completeness; do not hash gigabytes on a doctor
        # HTTP request. Leave named checkpoints unconfirmed until engine loading.
        return _local_path(model) and _nonempty(path)
    return backend == "text"


def bytes_on_disk(repo: str) -> int:
    try:
        return sum(f.stat().st_size for f in (repo_dir(repo) / "blobs").iterdir() if f.is_file())
    except OSError:
        return 0


def expected_bytes(repo: str) -> int | None:
    # Several revisions can coexist in blobs. A repository total cannot safely
    # be compared with their sum; retain honest byte progress without a percent.
    return None


def _set(**fields) -> None:
    global _state
    with _lock:
        _state = {**(_state or {}), **fields}


def snapshot() -> dict | None:
    with _lock:
        return dict(_state) if _state is not None else None


def _download(repo: str) -> None:
    try:
        from huggingface_hub import snapshot_download
    except ImportError:
        _set(state=ERROR, reason="huggingface_hub", error="huggingface_hub is unavailable")
        return
    try:
        snapshot_download(repo, cache_dir=str(cache_root()), allow_patterns=_ALLOW_PATTERNS)
        if not _cached_repo(repo):
            raise RuntimeError("Downloaded model is incomplete")
    except Exception as exc:
        _set(state=ERROR, error=f"{type(exc).__name__}: {exc}")
        return
    _set(state=READY, downloaded_bytes=bytes_on_disk(repo), error=None)


def start(settings: Settings) -> None:
    """Native-only start/retry; reserve and launch the worker under one lock.

    A second gesture cannot create a second download, including in the interval
    before Thread.start(). A changed model waits for the current download to end.
    """
    global _thread, _state
    backend = effective_backend(settings)
    model = settings.model
    with _lock:
        if _thread is not None and _thread.is_alive():
            return
        base = {"model": model, "backend": backend, "error": None, "total_bytes": None}
        if model_cached(settings):
            _state = {**base, "state": READY}
            return
        if backend != "faster-whisper":
            _state = {**base, "state": UNAVAILABLE, "reason": "backend"}
            return
        repo = repo_id(model)
        if repo is None:
            _state = {**base, "state": ERROR, "reason": "local-model" if _local_path(model) else "unknown-model",
                      "error": "The selected model is missing or incomplete"}
            return
        _state = {**base, "state": DOWNLOADING, "repo": repo}
        _thread = threading.Thread(target=_download, args=(repo,), daemon=True)
        try:
            _thread.start()
        except Exception as exc:
            _thread = None
            _state = {**_state, "state": ERROR, "error": f"{type(exc).__name__}: {exc}"}


def progress(settings: Settings | None = None) -> dict | None:
    """Read-only, including when settings changed: never fetch from HTTP."""
    state = snapshot()
    if state is None:
        return None
    if settings is not None:
        backend = effective_backend(settings)
        if state.get("model") != settings.model or state.get("backend") != backend:
            ready = model_cached(settings)
            return {"state": READY if ready else UNAVAILABLE, "model": settings.model,
                    "backend": backend, "reason": "configuration-changed", "total_bytes": None}
    if state and state.get("repo") and state.get("state") == DOWNLOADING:
        state["downloaded_bytes"] = bytes_on_disk(state["repo"])
    return state


def ensure_ready(settings: Settings) -> bool:
    """A native gesture may retry; callers must leave the microphone closed."""
    start(settings)
    state = progress(settings)
    return bool(state and (state["state"] == READY or (
        state["state"] == UNAVAILABLE and effective_backend(settings) != "faster-whisper"
    )))


def reset_for_tests() -> None:
    global _state, _thread
    with _lock:
        _state = None
        _thread = None
