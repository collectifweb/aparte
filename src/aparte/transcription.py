from __future__ import annotations

import ctypes
import glob
import os
import shutil
import subprocess
import sysconfig
from dataclasses import dataclass
from pathlib import Path

from . import hallucinations


class TranscriptionError(RuntimeError):
    pass


_cuda_preloaded = False


def _preload_cuda_libraries() -> None:
    """Load pip-provided CUDA runtime libs (``nvidia-*-cu12``) into the process.

    ctranslate2 dlopens ``libcublas``/``libcudnn`` by soname but does not look in
    pip's ``site-packages/nvidia/*/lib`` directories. Preloading them globally
    with their absolute path lets the later soname lookup resolve to the already
    loaded library, so GPU transcription works without the user exporting
    ``LD_LIBRARY_PATH``. Best-effort and idempotent; missing libs are ignored so
    the caller can fall back to CPU.
    """
    global _cuda_preloaded
    if _cuda_preloaded:
        return
    _cuda_preloaded = True
    nvidia_root = os.path.join(sysconfig.get_paths()["purelib"], "nvidia")
    if not os.path.isdir(nvidia_root):
        return
    # Order matters: dependencies (cublas, nvrtc) before cudnn aggregates.
    patterns = (
        "cublas/lib/libcublas*.so*",
        "cuda_nvrtc/lib/libnvrtc*.so*",
        "cudnn/lib/libcudnn*.so*",
    )
    for pattern in patterns:
        for path in sorted(glob.glob(os.path.join(nvidia_root, pattern))):
            try:
                ctypes.CDLL(path, mode=ctypes.RTLD_GLOBAL)
            except OSError:
                pass


@dataclass(frozen=True)
class Transcript:
    text: str
    backend: str


class Transcriber:
    def transcribe(self, audio_path: Path) -> Transcript:
        raise NotImplementedError


class TextFileTranscriber(Transcriber):
    def transcribe(self, audio_path: Path) -> Transcript:
        return Transcript(audio_path.read_text(encoding="utf-8"), "text")


class FasterWhisperTranscriber(Transcriber):
    # Substrings that signal a GPU is present but the CUDA runtime is unusable
    # (missing libcublas/libcudnn). Such failures can surface either when the
    # model is constructed or lazily on the first inference call.
    _CUDA_ERROR_HINTS = ("cublas", "cudnn", "cuda", "libcu", "gpu")

    def __init__(
        self,
        model: str,
        language: str | None = None,
        device: str = "auto",
        compute_type: str = "auto",
    ) -> None:
        self.model_name = model
        self.language = language
        self.device = device
        self.compute_type = compute_type
        self.model = self._load_model(device, compute_type)

    def _load_model(self, device: str, compute_type: str):
        from faster_whisper import WhisperModel

        if device != "cpu":
            _preload_cuda_libraries()
        try:
            return WhisperModel(self.model_name, device=device, compute_type=compute_type)
        except Exception as exc:
            if device == "cpu" or not self._is_cuda_error(exc):
                raise TranscriptionError(
                    f"Could not load faster-whisper model '{self.model_name}': {exc}"
                ) from exc
            return self._load_cpu_model()

    def _load_cpu_model(self):
        from faster_whisper import WhisperModel

        try:
            model = WhisperModel(self.model_name, device="cpu", compute_type="int8")
        except Exception as cpu_exc:
            raise TranscriptionError(
                f"Could not load faster-whisper model '{self.model_name}' on CPU: {cpu_exc}"
            ) from cpu_exc
        self.device = "cpu"
        self.compute_type = "int8"
        return model

    @classmethod
    def _is_cuda_error(cls, exc: Exception) -> bool:
        message = str(exc).lower()
        return any(hint in message for hint in cls._CUDA_ERROR_HINTS)

    def transcribe(self, audio_path: Path) -> Transcript:
        try:
            segments, _info = self.model.transcribe(str(audio_path), language=self.language)
            text = " ".join(segment.text.strip() for segment in segments if segment.text.strip())
        except Exception as exc:
            # CUDA can fail lazily on the first real inference; retry once on CPU.
            if self.device == "cpu" or not self._is_cuda_error(exc):
                raise TranscriptionError(str(exc)) from exc
            self.model = self._load_cpu_model()
            segments, _info = self.model.transcribe(str(audio_path), language=self.language)
            text = " ".join(segment.text.strip() for segment in segments if segment.text.strip())
        # Le filtre est ici, et pas dans polish.py, pour couvrir aussi les
        # chemins qui ne polissent pas : `--no-polish`, le raccourci global,
        # l'aperçu au fil de la parole.
        return Transcript(hallucinations.strip(text), "faster-whisper")


class OpenAIWhisperTranscriber(Transcriber):
    def __init__(self, model: str, language: str | None = None) -> None:
        import whisper

        self.whisper = whisper
        self.language = language
        self.model = whisper.load_model(model)

    def transcribe(self, audio_path: Path) -> Transcript:
        result = self.model.transcribe(str(audio_path), language=self.language)
        return Transcript(hallucinations.strip(str(result.get("text", "")).strip()), "openai-whisper")


class WhisperCppTranscriber(Transcriber):
    def __init__(self, executable: str, model: str, language: str | None = None) -> None:
        self.executable = executable
        self.model = model
        self.language = language

    def transcribe(self, audio_path: Path) -> Transcript:
        command = [self.executable, "-m", self.model, "-f", str(audio_path), "-nt"]
        if self.language:
            command.extend(["-l", self.language])
        completed = subprocess.run(command, check=False, text=True, capture_output=True)
        if completed.returncode != 0:
            raise TranscriptionError(completed.stderr.strip() or "whisper.cpp failed")
        return Transcript(hallucinations.strip(completed.stdout.strip()), "whisper.cpp")


def build_transcriber(
    backend: str = "auto",
    model: str = "small",
    language: str | None = None,
    whisper_cpp: str | None = None,
    device: str = "auto",
    compute_type: str = "auto",
) -> Transcriber:
    if backend == "text":
        return TextFileTranscriber()
    if backend == "faster-whisper":
        return FasterWhisperTranscriber(model, language, device, compute_type)
    if backend == "openai-whisper":
        return OpenAIWhisperTranscriber(model, language)
    if backend == "whisper.cpp":
        executable = whisper_cpp or shutil.which("whisper-cli") or shutil.which("main")
        if not executable:
            raise TranscriptionError("whisper.cpp executable not found")
        return WhisperCppTranscriber(executable, model, language)
    if backend != "auto":
        raise TranscriptionError(f"Unknown transcriber backend: {backend}")

    try:
        return FasterWhisperTranscriber(model, language, device, compute_type)
    except Exception:
        pass
    try:
        return OpenAIWhisperTranscriber(model, language)
    except Exception:
        pass
    executable = whisper_cpp or shutil.which("whisper-cli") or shutil.which("main")
    if executable:
        return WhisperCppTranscriber(executable, model, language)

    raise TranscriptionError(
        "No local Whisper backend found. Install faster-whisper, openai-whisper, "
        "or set APARTE_WHISPER_CPP to a whisper.cpp executable."
    )

