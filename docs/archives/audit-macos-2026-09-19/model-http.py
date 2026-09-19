"""Read-only audit of handlers: mocks, temporary cache/config, no personal audio."""
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from aparte import desktop, diagnostics, model_download, macos_recording
from aparte.config import Settings
from test_desktop import make_request
from test_macos_recording import FakeSounddevice

with tempfile.TemporaryDirectory(prefix="aparte-mac-audit-") as root:
    env = {
        "APARTE_CONFIG": root + "/config.json",
        "XDG_CONFIG_HOME": root + "/config",
        "XDG_DATA_HOME": root + "/data",
        "XDG_STATE_HOME": root + "/state",
        "XDG_CACHE_HOME": root + "/cache",
        "XDG_RUNTIME_DIR": root + "/runtime",
        "HF_HUB_CACHE": root + "/hub",
    }
    with patch.dict(os.environ, env), patch.object(desktop, "is_macos", return_value=True):
        Handler = desktop.handler_factory(Settings())
        with patch.object(desktop.history, "entries", return_value=[{"text": "AUDIT-SYNTHETIC-ONLY"}]):
            got = make_request("GET", "/api/history", headers={"Host": "rebound.example:8765", "Origin": "http://rebound.example:8765"}, handler_class=Handler)
            print("GET_HISTORY_FOREIGN_HOST", got)
        got = make_request("POST", "/api/paste", b'{"text":"SYNTHETIC"}', handler_class=Handler)
        print("MAC_PASTE_STATUS", got["status"])
        with patch.object(desktop.tempfile, "NamedTemporaryFile", side_effect=OSError(28, "No space left on device")):
            got = make_request("POST", "/api/transcribe", b"SYNTHETIC", handler_class=Handler)
        print("DISK_FULL", got)
        got = make_request("POST", "/api/transcribe?preview=1", b"SYNTHETIC", handler_class=Handler)
        print("PREVIEW_AFTER_DISK_FAILURE", got)
        model_download.reset_for_tests()
        (Path(root) / "hub/models--Systran--faster-whisper-small/snapshots").mkdir(parents=True)
        with patch.object(model_download.threading, "Thread") as thread:
            model_download.start(Settings(model="small"))
            print("EMPTY_CACHE", model_download.snapshot(), "THREAD_STARTED", thread.called, "DOCTOR_READY", diagnostics._whisper_model_cached(Settings(model="small")))
        print("OPENAI_BACKEND_WITH_ONLY_EMPTY_HF_CACHE", diagnostics._whisper_model_cached(Settings(model="small", transcriber="openai-whisper")))
        print("EMPTY_LOCAL_DIRECTORY_READY", diagnostics._whisper_model_cached(Settings(model=root)))
        model_download.reset_for_tests()
    with tempfile.TemporaryDirectory() as wrong, patch.dict(os.environ, {"HF_HUB_CACHE": wrong}):
        (Path(wrong) / "models--Systran--faster-whisper-small.en").mkdir()
        print("ONLY_EMPTY_SMALL_EN_DIR: model=small READY=", diagnostics._whisper_model_cached(Settings(model="small")))

# A fake PortAudio stream only: no microphone, no callback feed, no real TCC.
model_download._set(state=model_download.DOWNLOADING, model="small")
fake_sd = FakeSounddevice()
controller = macos_recording.RecordingController(lambda path: "", lambda: Settings(beep=False))
with patch.object(macos_recording, "_sounddevice", return_value=fake_sd), patch.object(macos_recording, "ensure_microphone_access"), patch.object(macos_recording, "notify"), patch.object(macos_recording.threading, "Timer"):
    controller.toggle()
    print("NATIVE_WHILE_DOWNLOADING", model_download.snapshot(), "RECORDER_STATE", controller.state, "STREAM_STARTED", fake_sd.streams[0].started)
    controller.shutdown()
model_download.reset_for_tests()
