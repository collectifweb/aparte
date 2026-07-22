import sys
import tempfile
import types
import unittest
from pathlib import Path

from aparte.cli import transcribe_path
from aparte.config import Settings
from aparte.transcription import FasterWhisperTranscriber, TranscriptionError


class TextTranscriptionTest(unittest.TestCase):
    def test_text_files_can_exercise_transcribe_pipeline(self):
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as handle:
            handle.write("hello from text")
            path = Path(handle.name)

        class Args:
            polish = False

        try:
            self.assertEqual(transcribe_path(path, Args(), Settings()), "hello from text")
        finally:
            path.unlink(missing_ok=True)


class _Segment:
    def __init__(self, text):
        self.text = text


class FasterWhisperFallbackTest(unittest.TestCase):
    """A GPU may be present without a usable CUDA runtime; we must fall back to CPU."""

    def _install_fake_faster_whisper(self, model_factory):
        module = types.ModuleType("faster_whisper")
        module.WhisperModel = model_factory
        self.addCleanup(lambda: sys.modules.pop("faster_whisper", None))
        sys.modules["faster_whisper"] = module

    def test_falls_back_to_cpu_when_cuda_fails_at_construction(self):
        constructed = []

        class FakeModel:
            def __init__(self, name, device="auto", compute_type="auto"):
                constructed.append(device)
                if device != "cpu":
                    raise RuntimeError("Library libcublas.so.12 is not found or cannot be loaded")

            def transcribe(self, path, language=None):
                return [_Segment("hello from cpu")], None

        self._install_fake_faster_whisper(FakeModel)
        transcriber = FasterWhisperTranscriber("small", device="auto")
        self.assertEqual(transcriber.device, "cpu")
        self.assertEqual(transcriber.transcribe(Path("x.wav")).text, "hello from cpu")
        self.assertIn("cpu", constructed)

    def test_falls_back_to_cpu_when_cuda_fails_lazily_on_transcribe(self):
        class FakeModel:
            def __init__(self, name, device="auto", compute_type="auto"):
                self.device = device

            def transcribe(self, path, language=None):
                if self.device != "cpu":
                    raise RuntimeError("Library libcublas.so.12 cannot be loaded")
                return [_Segment("recovered on cpu")], None

        self._install_fake_faster_whisper(FakeModel)
        transcriber = FasterWhisperTranscriber("small", device="auto")
        self.assertEqual(transcriber.transcribe(Path("x.wav")).text, "recovered on cpu")
        self.assertEqual(transcriber.device, "cpu")

    def test_non_cuda_error_on_cpu_is_not_retried(self):
        class FakeModel:
            def __init__(self, name, device="auto", compute_type="auto"):
                pass

            def transcribe(self, path, language=None):
                raise RuntimeError("audio file is corrupt")

        self._install_fake_faster_whisper(FakeModel)
        transcriber = FasterWhisperTranscriber("small", device="cpu")
        with self.assertRaises(TranscriptionError):
            transcriber.transcribe(Path("x.wav"))


if __name__ == "__main__":
    unittest.main()
