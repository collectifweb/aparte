"""Small, private diagnostics for the keyboard shortcut; never a stdout sink."""
from __future__ import annotations

from datetime import datetime, timezone
import fcntl
import json
import math
import os
from pathlib import Path
import re
import stat
import sys

MAX_BYTES = 128 * 1024  # one active file and one previous file
_EVENTS = {"invoked", "completed", "failed", "audio_start_failed"}
PERFORMANCE_SOURCES = frozenset({"shortcut", "cli", "http", "preview", "recovery"})
PERFORMANCE_STAGES = frozenset({"delegation", "queue", "model_load", "transcription", "polish", "delivery"})
PERFORMANCE_BACKENDS = frozenset({"faster-whisper", "openai-whisper", "whisper.cpp", "text", "unknown"})
PERFORMANCE_DEVICES = frozenset({"cpu", "cuda", "mps", "auto", "unknown"})
PERFORMANCE_COMPUTE_TYPES = frozenset({
    "auto", "default", "int8", "int8_float32", "int8_float16", "int8_bfloat16",
    "int16", "float16", "float32", "bfloat16", "unknown",
})
PERFORMANCE_MODELS = frozenset({
    "tiny", "tiny.en", "base", "base.en", "small", "small.en", "medium", "medium.en",
    "large", "large-v1", "large-v2", "large-v3", "large-v3-turbo", "turbo", "unknown",
})
MAX_DURATION_MS = 24 * 60 * 60 * 1000
_ERROR_TYPES = frozenset({
    "Exception", "BaseException", "RuntimeError", "ValueError", "TypeError", "OSError",
    "PermissionError", "FileNotFoundError", "FileExistsError", "BlockingIOError",
    "BrokenPipeError", "ConnectionError", "ConnectionResetError", "TimeoutError",
    "MemoryError", "ImportError", "ModuleNotFoundError", "KeyboardInterrupt", "SystemExit",
    "RecordingError", "RecordingStartError", "ToggleSessionError", "ShutdownError",
    "TranscriptionError", "ClipboardError", "RecoveryError", "RecoveryBusy", "RecoveryNotFound",
    "PolishError", "_PolishFailure", "HTTPError", "URLError", "CalledProcessError",
    "TimeoutExpired", "RequestException", "Timeout", "RequestBodyTimeout",
})


def valid_trace_id(value: object) -> bool:
    return type(value) is str and re.fullmatch(r"[0-9a-f]{32}", value) is not None


def _duration(value: object) -> bool:
    return type(value) is int and 0 <= value <= MAX_DURATION_MS


def write_performance(kind: str, *, trace_id: str, source: str,
                      duration_ms: int | None = None, success: bool | None = None,
                      stage: str | None = None, error_type: str | None = None,
                      backend: str | None = None, device: str | None = None,
                      compute_type: str | None = None, model: str | None = None,
                      audio_ms: int | None = None, load1: float | None = None,
                      cpu_count: int | None = None, http_status: int | None = None) -> None:
    """A closed schema sharing the private bounded log; never free-form data."""
    try:
        if not valid_trace_id(trace_id) or source not in PERFORMANCE_SOURCES:
            return
        data = {"event": f"performance_{kind}", "trace_id": trace_id, "source": source}
        if kind in {"total", "stage"}:
            if not _duration(duration_ms) or type(success) is not bool:
                return
            data.update(duration_ms=duration_ms, success=success)
            if not success and error_type is not None:
                data["error_type"] = error_type if error_type in _ERROR_TYPES else "Exception"
            if kind == "stage":
                if stage not in PERFORMANCE_STAGES:
                    return
                data["stage"] = stage
            else:
                if type(http_status) is int and 100 <= http_status <= 599:
                    data["http_status"] = http_status
                    if http_status >= 400:
                        data["success"] = False
                if type(load1) in {int, float} and math.isfinite(load1) and 0 <= load1 <= 65536:
                    data["load1"] = round(load1, 2)
                if type(cpu_count) is int and 1 <= cpu_count <= 65536:
                    data["cpu_count"] = cpu_count
        elif kind == "execution":
            if (backend not in PERFORMANCE_BACKENDS or device not in PERFORMANCE_DEVICES
                    or compute_type not in PERFORMANCE_COMPUTE_TYPES or model not in PERFORMANCE_MODELS):
                return
            data.update(backend=backend, device=device, compute_type=compute_type, model=model)
        elif kind == "audio":
            if not _duration(audio_ms):
                return
            data["audio_ms"] = audio_ms
        else:
            return
        _write(data)
    except Exception:
        # Even invalid instrumentation must not affect delivery or its error.
        pass


def _directory() -> int:
    base = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state")
    if not base.is_absolute():
        raise OSError("state directory must be absolute")
    # Walk with directory descriptors, refusing symlinks at every level. Only
    # directories belonging to this logger have their permissions tightened.
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        parts = (*base.parts[1:], "aparte", "logs")
        for index, part in enumerate(parts):
            if part in {".", ".."}:
                raise OSError("invalid state directory")
            try:
                os.mkdir(part, 0o700, dir_fd=fd)
            except FileExistsError:
                pass
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
            if index >= len(parts) - 2:
                if os.fstat(fd).st_uid != os.getuid():
                    raise OSError("diagnostic directory has another owner")
                os.fchmod(fd, 0o700)
        return fd
    except BaseException:
        os.close(fd)
        raise


def _file(directory: int, name: str) -> int:
    fd = os.open(name, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK,
                 0o600, dir_fd=directory)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1:
            raise OSError("unsafe diagnostic file")
        os.fchmod(fd, 0o600)
        return fd
    except BaseException:
        os.close(fd)
        raise


def write_event(event: str, *, error_type: str | None = None,
                audio_diagnostic: str | None = None) -> None:
    """Best effort. Only a recorder-start failure may carry an ALSA diagnostic.

    Never pass arbitrary exception messages here: they may contain dictated
    text, HTTP response bodies, or subprocess arguments used for insertion.
    """
    if event not in _EVENTS:
        return
    try:
        data = {"event": event}
        if error_type is not None:
            data["error_type"] = error_type[:80]
        if event == "audio_start_failed" and audio_diagnostic is not None:
            data["audio_diagnostic"] = audio_diagnostic[:6000]
        _write(data)
    except (OSError, ValueError):
        pass


def _write(data: dict) -> None:
    try:
        data = {"utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), **data}
        line = (json.dumps(data, ensure_ascii=False) + "\n").encode("utf-8")
        directory = _directory()
        try:
            # The directory inode is stable across rotations and shared by all
            # shortcut invocations. Do not remove it while the app is running.
            fcntl.flock(directory, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fd = _file(directory, "hotkey.jsonl")
            try:
                if os.fstat(fd).st_size > MAX_BYTES:
                    # Do not retain an unbounded pre-existing or corrupt file.
                    os.ftruncate(fd, 0)
                if os.fstat(fd).st_size + len(line) > MAX_BYTES:
                    os.close(fd)
                    fd = -1
                    backup = _file(directory, "hotkey.jsonl.1")
                    os.close(backup)
                    os.replace("hotkey.jsonl", "hotkey.jsonl.1", src_dir_fd=directory, dst_dir_fd=directory)
                    fd = _file(directory, "hotkey.jsonl")
                with os.fdopen(fd, "ab") as output:
                    fd = -1
                    output.write(line)
            finally:
                if fd != -1:
                    os.close(fd)
        finally:
            os.close(directory)
    except (OSError, ValueError):
        # An unavailable disk or a simultaneous diagnostic never blocks dictation.
        pass


def silence_process() -> None:
    """Permanently discard Python, native and child stdout/stderr.

    Only for the standalone --hotkey process, never the threaded server. Keeping
    the sink through interpreter shutdown also covers backend atexit handlers
    and native buffers flushed after main returns. Tests must use a subprocess.
    """
    sink = open(os.devnull, "w")
    try:
        for stream in (sys.stdout, sys.stderr):
            stream.flush()
        for number in (1, 2):
            os.dup2(sink.fileno(), number)
    except BaseException:
        sink.close()
        raise
    # These references intentionally keep the sink open until interpreter exit.
    sys.stdout = sys.stderr = sink
