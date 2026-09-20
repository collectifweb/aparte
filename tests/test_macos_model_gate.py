"""Mac HTTP inference observes prepared weights; only native actions fetch them."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from aparte import desktop, model_download, recovery
from aparte.config import Settings
from test_desktop import make_request


class MacModelGateTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.settings = Settings(model="small", transcriber="faster-whisper")
        environment = mock.patch.dict(os.environ, {
            "APARTE_CONFIG": str(self.root / "config.json"),
            "APARTE_RUNTIME_DIR": str(self.root / "runtime"),
            "HF_HUB_CACHE": str(self.root / "hub"),
        })
        environment.start()
        self.addCleanup(environment.stop)
        for patch in (
            mock.patch.object(desktop, "is_macos", return_value=True),
            mock.patch.object(desktop.Settings, "from_env", side_effect=lambda: self.settings),
        ):
            patch.start()
            self.addCleanup(patch.stop)
        self.handler = desktop.handler_factory(self.settings)

    def populate(self, model="small", revision="abc"):
        repo = model_download.repo_dir(f"Systran/faster-whisper-{model}")
        (repo / "refs").mkdir(parents=True, exist_ok=True)
        (repo / "refs/main").write_text(revision)
        path = repo / "snapshots" / revision
        path.mkdir(parents=True, exist_ok=True)
        for name in ("model.bin", "config.json", "tokenizer.json", "vocabulary.json"):
            (path / name).write_bytes(b"synthetic model fixture")
        return path

    def request(self, query=""):
        return make_request("POST", "/api/transcribe" + query, b"synthetic audio",
                            {"Content-Type": "audio/wav"}, self.handler)

    def test_missing_weights_refuse_http_without_starting_a_download(self):
        with mock.patch.object(desktop, "build_transcriber") as build, \
             mock.patch.object(model_download, "start") as start:
            result = self.request("?recover=1")
        self.assertEqual(result["status"], 500)
        self.assertIn("Préparer le modèle", json.loads(result["body"])["error"])
        build.assert_not_called()
        start.assert_not_called()
        self.assertEqual(len(recovery.entries()), 1)

    def test_complete_weights_are_loaded_by_local_path_including_auto(self):
        path = self.populate()
        self.settings = Settings(model="small", transcriber="auto")
        with mock.patch.object(model_download, "_has_module", return_value=True), \
             mock.patch.object(desktop, "build_transcriber") as build:
            build.return_value.transcribe.return_value.text = "dictée"
            result = self.request()
        self.assertEqual(result["status"], 200)
        self.assertEqual(build.call_args.kwargs["model"], str(path))
        self.assertEqual(build.call_args.kwargs["backend"], "faster-whisper")

    def test_query_override_cannot_bypass_preparation(self):
        self.populate()
        with mock.patch.object(desktop, "build_transcriber") as build:
            result = self.request("?model=medium")
        self.assertEqual(result["status"], 500)
        build.assert_not_called()

    def test_complete_override_uses_its_own_snapshot(self):
        path = self.populate("medium")
        with mock.patch.object(desktop, "build_transcriber") as build:
            build.return_value.transcribe.return_value.text = "dictée"
            result = self.request("?model=medium")
        self.assertEqual(result["status"], 200)
        self.assertEqual(build.call_args.kwargs["model"], str(path))

    def test_partial_cache_is_not_used_even_if_snapshot_directory_exists(self):
        path = self.populate()
        (path / "tokenizer.json").unlink()
        with mock.patch.object(desktop, "build_transcriber") as build:
            result = self.request()
        self.assertEqual(result["status"], 500)
        build.assert_not_called()

    def test_new_default_revision_loads_a_new_transcriber(self):
        first = self.populate(revision="first")
        with mock.patch.object(desktop, "build_transcriber") as build:
            build.return_value.transcribe.return_value.text = "dictée"
            self.assertEqual(self.request()["status"], 200)
            second = self.populate(revision="second")
            self.assertEqual(self.request()["status"], 200)
        self.assertEqual([call.kwargs["model"] for call in build.call_args_list], [str(first), str(second)])

    def test_recovery_without_raw_text_obeys_the_same_gate_and_keeps_audio(self):
        audio = self.root / "input.wav"
        audio.write_bytes(b"synthetic capture")
        identifier = recovery.save_failure(audio)
        with mock.patch.object(desktop, "build_transcriber") as build:
            result = make_request("POST", "/api/recovery/retry",
                                  json.dumps({"id": identifier}).encode(), handler_class=self.handler)
        self.assertEqual(result["status"], 500)
        build.assert_not_called()
        self.assertEqual(recovery.entries()[0]["id"], identifier)

    def test_linux_and_other_explicit_engines_keep_their_existing_behavior(self):
        for macos, backend in ((False, "faster-whisper"), (True, "openai-whisper"),
                               (True, "whisper.cpp")):
            self.settings = Settings(model="small", transcriber=backend)
            handler = desktop.handler_factory(self.settings)
            with mock.patch.object(desktop, "is_macos", return_value=macos), \
                 mock.patch.object(desktop, "build_transcriber") as build:
                build.return_value.transcribe.return_value.text = "dictée"
                result = make_request("POST", "/api/transcribe", b"synthetic", handler_class=handler)
            self.assertEqual(result["status"], 200)
            self.assertEqual(build.call_args.kwargs["model"], "small")
            self.assertEqual(build.call_args.kwargs["backend"], backend)
