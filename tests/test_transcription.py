import sys
import tempfile
import types
import unittest
from pathlib import Path

from aparte.cli import transcribe_path
from aparte.config import Settings
from aparte.transcription import (
    FasterWhisperTranscriber,
    TranscriptionError,
    build_transcriber,
)


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

            def transcribe(self, path, language=None, hotwords=None):
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

            def transcribe(self, path, language=None, hotwords=None):
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

            def transcribe(self, path, language=None, hotwords=None):
                raise RuntimeError("audio file is corrupt")

        self._install_fake_faster_whisper(FakeModel)
        transcriber = FasterWhisperTranscriber("small", device="cpu")
        with self.assertRaises(TranscriptionError):
            transcriber.transcribe(Path("x.wav"))


class HotwordsTest(unittest.TestCase):
    """« Mes mots » : le vocabulaire de l'utilisateur, donné à Whisper en amont."""

    def _fake_model(self, seen):
        class FakeModel:
            def __init__(self, name, device="auto", compute_type="auto"):
                pass

            def transcribe(self, path, language=None, hotwords=None):
                seen.append(hotwords)
                return [_Segment("ok")], None

        module = types.ModuleType("faster_whisper")
        module.WhisperModel = FakeModel
        self.addCleanup(lambda: sys.modules.pop("faster_whisper", None))
        sys.modules["faster_whisper"] = module

    def test_the_word_list_reaches_whisper_as_one_string(self):
        seen = []
        self._fake_model(seen)
        transcriber = FasterWhisperTranscriber("small", device="cpu", hotwords=("Playwright", "Wayland"))
        transcriber.transcribe(Path("x.wav"))
        self.assertEqual(seen, ["Playwright, Wayland"])

    def test_no_words_means_none_not_an_empty_string(self):
        # Une chaîne vide entre quand même dans l'amorce du décodeur ; None est
        # la seule façon de dire « aucun penchant ».
        seen = []
        self._fake_model(seen)
        FasterWhisperTranscriber("small", device="cpu").transcribe(Path("x.wav"))
        self.assertEqual(seen, [None])

    def test_backends_without_hotwords_still_build(self):
        # openai-whisper et whisper.cpp n'ont pas d'équivalent : le réglage doit
        # s'effacer, pas faire échouer la construction.
        transcriber = build_transcriber(
            backend="whisper.cpp",
            model="small",
            whisper_cpp="/bin/true",
            hotwords=("Playwright",),
        )
        self.assertEqual(transcriber.model, "small")


if __name__ == "__main__":
    unittest.main()
