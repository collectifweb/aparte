"""Execution metadata uses the engine actually selected, without real models."""
import contextlib
import json
import os
import tempfile
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from aparte import transcription


class TranscriptionPerformanceTest(unittest.TestCase):
    def install_faster(self, factory):
        module = types.ModuleType("faster_whisper")
        module.WhisperModel = factory
        self.patch = patch.dict(sys.modules, {"faster_whisper": module})
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def test_auto_reports_effective_engine_device_and_type_on_every_call(self):
        class FakeModel:
            def __init__(self, *args, **kwargs):
                self.model = types.SimpleNamespace(device="cuda", compute_type="float16")

            def transcribe(self, *args, **kwargs):
                return iter([types.SimpleNamespace(text="private words")]), None

        self.install_faster(FakeModel)
        with patch.object(transcription.performance, "execution") as execution:
            with patch.object(transcription.performance, "stage") as stage:
                model = transcription.FasterWhisperTranscriber("small")
                self.assertEqual(model.device, "auto")
                for _ in range(2):
                    self.assertEqual(model.transcribe(Path("/private/input.wav")).text, "private words")
                stage.assert_not_called()  # Initial loading is timed by the caller.
            self.assertEqual(execution.call_count, 2)
            execution.assert_called_with(backend="faster-whisper", device="cuda",
                                         compute_type="float16", model="small")
            self.assertNotIn("private", repr(execution.call_args_list))

    def test_lazy_generator_failure_times_reload_and_reports_cpu_retry(self):
        events = []

        class FakeModel:
            def __init__(self, name, device="auto", compute_type="auto"):
                self.model = types.SimpleNamespace(
                    device="cpu" if device == "cpu" else "cuda",
                    compute_type="int8_float32" if device == "cpu" else "float16",
                )
                events.append("constructed:" + self.model.device)

            def transcribe(self, *args, **kwargs):
                def segments():
                    events.append("iterated:" + self.model.device)
                    if self.model.device == "cuda":
                        yield types.SimpleNamespace(text="partial GPU result")
                        raise RuntimeError("CUDA unavailable")
                    yield types.SimpleNamespace(text="complete CPU result")
                return segments(), None

        @contextlib.contextmanager
        def stage(name):
            events.append("start:" + name)
            try:
                yield
            finally:
                events.append("end:" + name)

        self.install_faster(FakeModel)
        with patch.object(transcription.performance, "execution") as execution:
            with patch.object(transcription.performance, "stage", side_effect=stage):
                model = transcription.FasterWhisperTranscriber("small")
                result = model.transcribe(Path("/private/capture.wav"))
        self.assertEqual(result.text, "complete CPU result")
        self.assertEqual(events, ["constructed:cuda", "iterated:cuda", "start:model_load",
                                  "constructed:cpu", "end:model_load", "iterated:cpu"])
        self.assertEqual([call.kwargs["device"] for call in execution.call_args_list], ["cuda", "cpu"])
        self.assertEqual(execution.call_args.kwargs["compute_type"], "int8_float32")
        self.assertNotIn("private", repr(execution.call_args_list))

    def test_missing_or_broken_engine_properties_are_unknown(self):
        class BrokenEngine:
            @property
            def device(self):
                raise RuntimeError("private diagnostic detail")

            compute_type = "/private/not-a-type"

        class FakeModel:
            def __init__(self, *args, **kwargs):
                self.model = BrokenEngine()

            def transcribe(self, *args, **kwargs):
                return [], None

        self.install_faster(FakeModel)
        model = transcription.FasterWhisperTranscriber("small")
        with patch.object(transcription.performance, "execution") as execution:
            for engine in [BrokenEngine(), None, object()]:
                model.model.model = engine
                self.assertEqual(model.transcribe(Path("/private/input.wav")).text, "")
                self.assertEqual(execution.call_args.kwargs["device"], "unknown")
                self.assertEqual(execution.call_args.kwargs["compute_type"], "unknown")
            self.assertNotIn("private", repr(execution.call_args_list))

    def test_metadata_write_failure_cannot_prevent_transcription(self):
        class FakeModel:
            def __init__(self, *args, **kwargs):
                pass

            def transcribe(self, *args, **kwargs):
                return [types.SimpleNamespace(text="delivered")], None

        self.install_faster(FakeModel)
        with patch.object(transcription.performance, "execution", side_effect=OSError("disk full")):
            model = transcription.FasterWhisperTranscriber("small")
            self.assertEqual(model.transcribe(Path("x.wav")).text, "delivered")

    def test_openai_reports_device_without_claiming_parameter_dtype_is_compute_type(self):
        engine = types.SimpleNamespace(device=types.SimpleNamespace(type="cuda"))
        engine.transcribe = lambda *args, **kwargs: {"text": "dictation"}
        module = types.ModuleType("whisper")
        module.load_model = lambda model: engine
        with patch.dict(sys.modules, {"whisper": module}):
            model = transcription.OpenAIWhisperTranscriber("small")
        with patch.object(transcription.performance, "execution") as execution:
            model.transcribe(Path("/private/input.wav"))
        execution.assert_called_once_with(backend="openai-whisper", device="cuda",
                                          compute_type="unknown", model="small")

    def test_real_log_retains_execution_but_excludes_model_paths_audio_and_vocabulary(self):
        class FakeModel:
            def __init__(self, *args, **kwargs):
                self.model = types.SimpleNamespace(device="cuda", compute_type="float16")

            def transcribe(self, *args, **kwargs):
                return [types.SimpleNamespace(text="PRIVATE_DICTATION")], None

        self.install_faster(FakeModel)
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {"XDG_STATE_HOME": directory}):
                with transcription.performance.operation("cli"):
                    model = transcription.FasterWhisperTranscriber(
                        "/PRIVATE_MODEL/path", hotwords=("PRIVATE_VOCABULARY",))
                    model.transcribe(Path("/PRIVATE_AUDIO/path.wav"))
                log = (Path(directory) / "aparte/logs/hotkey.jsonl").read_text()
        self.assertNotIn("PRIVATE_", log)
        entries = [json.loads(line) for line in log.splitlines()]
        execution = next(entry for entry in entries if entry["event"] == "performance_execution")
        self.assertEqual(execution["device"], "cuda")
        self.assertEqual(execution["compute_type"], "float16")
        self.assertEqual(execution["model"], "unknown")

    def test_cpp_does_not_log_model_path_or_parse_output_for_metadata(self):
        model = transcription.WhisperCppTranscriber("/bin/whisper-cli", "/private/model.bin")
        result = types.SimpleNamespace(returncode=0, stdout="private dictation", stderr="private details")
        with patch.object(transcription.subprocess, "run", return_value=result):
            with patch.object(transcription.performance, "execution") as execution:
                self.assertEqual(model.transcribe(Path("/private/audio.wav")).text, "private dictation")
        execution.assert_called_once_with(backend="whisper.cpp", device="unknown",
                                          compute_type="unknown", model=None)


if __name__ == "__main__":
    unittest.main()
