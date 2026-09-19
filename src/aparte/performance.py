"""Best-effort timings without speech, paths, prompts or exception messages.

Stages describe elapsed wall time measured with a monotonic clock. The optional
load snapshot is the operating system's one-minute load average, not CPU usage.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
import math
import os
from pathlib import Path
import stat
import time
from typing import Iterator
import uuid
import wave

from . import technical_log


@dataclass(frozen=True)
class _Operation:
    identifier: str
    source: str


_current: ContextVar[_Operation | None] = ContextVar("aparte_performance", default=None)
_http_status: ContextVar[int | None] = ContextVar("aparte_performance_http_status", default=None)


def current_id() -> str | None:
    current = _current.get()
    return current.identifier if current is not None else None


def response_status(code: int) -> None:
    """Remember an HTTP response for this operation, including handled errors."""
    if _current.get() is not None and isinstance(code, int) and not isinstance(code, bool) and 100 <= code <= 599:
        _http_status.set(int(code))


def _now() -> float | None:
    try:
        value = time.monotonic()
        return value if math.isfinite(value) else None
    except Exception:
        return None


def _emit(kind: str, current: _Operation, **fields) -> None:
    try:
        technical_log.write_performance(kind, trace_id=current.identifier,
                                        source=current.source, **fields)
    except Exception:
        # Logging can be replaced, unavailable or broken; dictation comes first.
        pass


def _finish(kind: str, current: _Operation, started: float | None,
            error: BaseException | None, http_status: int | None = None, **fields) -> None:
    try:
        ended = _now()
        if started is None or ended is None:
            return
        duration = min(technical_log.MAX_DURATION_MS, max(0, round((ended - started) * 1000)))
        success = error is None and not (kind == "total" and http_status is not None and http_status >= 400)
        if kind == "total" and http_status is not None:
            fields["http_status"] = http_status
        _emit(kind, current, duration_ms=duration, success=success,
              error_type=type(error).__name__ if error is not None else None, **fields)
    except Exception:
        pass


@contextmanager
def operation(source: str, identifier: str | None = None) -> Iterator[str | None]:
    """Use one trace per context; only its outer operation emits a total.

    A supplied trace is accepted only as 32 lowercase hexadecimal characters.
    This permits correlation with another process without accepting log text.
    Threads start independent contexts; an explicitly copied context retains its
    trace. Nested operations retain the original source as well as identifier.
    """
    existing = _current.get()
    if existing is not None:
        yield existing.identifier
        return
    if type(source) is not str or source not in technical_log.PERFORMANCE_SOURCES:
        yield None
        return
    try:
        trace = identifier if technical_log.valid_trace_id(identifier) else uuid.uuid4().hex
    except Exception:
        yield None
        return
    current = _Operation(trace, source)
    token = _current.set(current)
    status_token = _http_status.set(None)
    started = _now()
    load1 = cpu_count = None
    try:
        load1 = os.getloadavg()[0]
    except Exception:
        pass
    try:
        cpu_count = os.cpu_count()
    except Exception:
        pass
    error = None
    try:
        yield trace
    except BaseException as exc:
        error = exc
        raise
    finally:
        http_status = _http_status.get()
        _http_status.reset(status_token)
        _current.reset(token)
        _finish("total", current, started, error, http_status=http_status,
                load1=load1, cpu_count=cpu_count)


@contextmanager
def stage(name: str) -> Iterator[None]:
    """Time a known stage, preserving the original success or raised exception."""
    current = _current.get()
    if current is None or type(name) is not str or name not in technical_log.PERFORMANCE_STAGES:
        yield
        return
    started = _now()
    error = None
    try:
        yield
    except BaseException as exc:
        error = exc
        raise
    finally:
        _finish("stage", current, started, error, stage=name)


def _enum(value: object, choices: frozenset[str]) -> str:
    return value if type(value) is str and value in choices else "unknown"


def execution(backend: str, device: str, compute_type: str, model: str | None = None) -> None:
    """Record effective enum values; custom names and model paths become unknown."""
    current = _current.get()
    if current is None:
        return
    _emit("execution", current,
          backend=_enum(backend, technical_log.PERFORMANCE_BACKENDS),
          device=_enum(device, technical_log.PERFORMANCE_DEVICES),
          compute_type=_enum(compute_type, technical_log.PERFORMANCE_COMPUTE_TYPES),
          model=_enum(model, technical_log.PERFORMANCE_MODELS))


def audio_duration(path: Path) -> float | None:
    """Read WAV metadata only; return seconds or None, never decode its samples.

    Non-WAV, inaccessible and incomplete placeholder headers are optional data.
    Refuse special files and symlinks so measurement cannot wait on a stream.
    """
    descriptor = None
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK)
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            return None
        with os.fdopen(descriptor, "rb") as source:
            descriptor = None
            with wave.open(source, "rb") as audio:
                frames = audio.getnframes()
                frame_bytes = audio.getsampwidth() * audio.getnchannels()
                rate = audio.getframerate()
                if rate <= 0 or frame_bytes <= 0 or frames * frame_bytes > info.st_size:
                    return None
                seconds = frames / rate
        if not math.isfinite(seconds) or not 0 <= seconds <= technical_log.MAX_DURATION_MS / 1000:
            return None
        current = _current.get()
        if current is not None:
            _emit("audio", current, audio_ms=round(seconds * 1000))
        return seconds
    except Exception:
        return None
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
