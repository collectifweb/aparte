"""Exercise shutdown guards across the CLI and real HTTP handler entry points."""
import json
import http.client
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest import mock

from aparte import cli, desktop, lifecycle, session
from aparte.config import Settings
from test_desktop import make_request


class LifecycleIntegrationTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        env = {key: value for key, value in os.environ.items()
               if not key.startswith(("APARTE_", "MURMUR_"))}
        env.update(APARTE_CONFIG=str(self.root / "config.json"),
                   APARTE_RUNTIME_DIR=str(self.root / "runtime"))
        for key in ("XDG_RUNTIME_DIR", "XDG_CONFIG_HOME", "XDG_STATE_HOME",
                    "XDG_DATA_HOME", "XDG_CACHE_HOME"):
            env[key] = str(self.root / key)
        patcher = mock.patch.dict(os.environ, env, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.notifications = mock.patch.object(desktop, "notify")
        self.notifications.start()
        self.addCleanup(self.notifications.stop)

    def test_toggle_status_distinguishes_finished_audio_from_open_microphone(self):
        path = session.get_runtime_dir() / "synthetic.wav"
        path.write_bytes(b"0" * 32044)
        capture = session.RecordingSession(-1, path, 16000, time.time())
        session._claim_session(capture)
        args = cli.build_parser().parse_args(["toggle", "--status"])
        self.assertEqual(cli.toggle_dictation(args, Settings()), "recoverable")
        self.assertTrue(path.exists())

    def test_toggle_processing_is_registered_before_stop_and_until_delivery(self):
        path = session.get_runtime_dir() / "synthetic.wav"
        path.write_bytes(b"synthetic")
        capture = session.RecordingSession(-1, path, 16000, time.time())

        def stop():
            self.assertTrue(lifecycle.is_processing())
            return capture

        def transcribe(*_):
            self.assertEqual(lifecycle.get_dictation_state(), "processing")
            with self.assertRaises(lifecycle.ShutdownError):
                with lifecycle.prepare_shutdown():
                    self.fail("quit entered while dictation was processing")
            return "texte synthétique"

        args = cli.build_parser().parse_args(["toggle", "--target", "stdout"])
        with mock.patch.object(cli, "get_active_session", return_value=capture), \
                mock.patch.object(cli, "stop_toggle_recording", side_effect=stop), \
                mock.patch.object(cli, "transcribe_path", side_effect=transcribe), \
                mock.patch.object(cli, "notify"):
            self.assertEqual(cli.toggle_dictation(args, Settings()), "texte synthétique")
        self.assertFalse(lifecycle.is_processing())

    def test_http_processing_refuses_quit_and_cleans_marker_after_response(self):
        def transcribe(_):
            self.assertEqual(lifecycle.get_dictation_state(), "processing")
            with self.assertRaises(lifecycle.ShutdownError):
                with lifecycle.prepare_shutdown():
                    self.fail("quit entered")
            return SimpleNamespace(text="texte synthétique")

        engine = SimpleNamespace(transcribe=transcribe)
        with mock.patch.object(desktop, "build_transcriber", return_value=engine):
            result = make_request("POST", "/api/transcribe", b"synthetic")
        self.assertEqual(result["status"], 200)
        self.assertFalse(lifecycle.is_processing())

    def _serve(self, handler):
        server = desktop.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()

        def cleanup():
            server.shutdown()
            worker.join(timeout=2)
            server.server_close()

        self.addCleanup(cleanup)
        client = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
        self.addCleanup(client.close)
        return client

    def test_stalled_upload_times_out_releases_processing_and_allows_quit(self):
        reading = threading.Event()
        with mock.patch.object(desktop, "HTTP_IO_TIMEOUT", 0.5):
            base = desktop.handler_factory(Settings())

        class ObserveBody(base):
            def _read_body(self, length):
                reading.set()
                return super()._read_body(length)

        client = self._serve(ObserveBody)
        with mock.patch.object(desktop, "build_transcriber") as build:
            for route in ("/api/transcribe", "/api/config", "/api/recovery/retry"):
                with self.subTest(route=route):
                    reading.clear()
                    client.putrequest("POST", route)
                    client.putheader("Content-Length", "100")
                    client.endheaders(b"x")  # Keep the socket open without the other 99 bytes.
                    self.assertTrue(reading.wait(timeout=2))
                    self.assertTrue(lifecycle.is_processing())
                    response = client.getresponse()
                    self.assertEqual(response.status, 408)
                    self.assertFalse(json.loads(response.read())["ok"])
                    build.assert_not_called()
                    self.assertFalse(lifecycle.is_processing())
        stop = mock.Mock()
        desktop._quit_without_tray(stop, threading.Lock())
        stop.assert_called_once_with()

    def test_http_io_timeout_does_not_limit_model_execution(self):
        def transcribe(_):
            time.sleep(0.15)
            return SimpleNamespace(text="texte synthétique")

        with mock.patch.object(desktop, "HTTP_IO_TIMEOUT", 0.05):
            client = self._serve(desktop.handler_factory(Settings()))
        with mock.patch.object(desktop, "build_transcriber", return_value=SimpleNamespace(transcribe=transcribe)):
            client.request("POST", "/api/transcribe", body=b"synthetic")
            response = client.getresponse()
            self.assertEqual(response.status, 200)
            self.assertEqual(json.loads(response.read())["text"], "texte synthétique")
        self.assertFalse(lifecycle.is_processing())

    def test_closing_server_refuses_new_work(self):
        closing = threading.Event()
        closing.set()
        with mock.patch.object(desktop, "build_transcriber") as build:
            result = make_request("POST", "/api/transcribe", b"synthetic",
                                  handler_class=desktop.handler_factory(Settings(), closing=closing))
        self.assertEqual(result["status"], 503)
        build.assert_not_called()
        self.assertFalse(lifecycle.is_processing())

    def test_update_refuses_processing_before_streaming_or_installing(self):
        with lifecycle.processing_dictation(), \
                mock.patch.object(desktop, "apply_update") as install:
            result = make_request("POST", "/api/update/apply")
        self.assertEqual(result["status"], 409)
        self.assertFalse(json.loads(result["body"])["ok"])
        install.assert_not_called()

    def test_update_keeps_transition_exclusive_until_restart(self):
        observed = []

        def other_process_intent():
            try:
                with session.toggle_session_transition():
                    observed.append("entered")
            except session.ToggleSessionError:
                observed.append("excluded")

        def restart():
            worker = threading.Thread(target=other_process_intent)
            worker.start()
            worker.join(timeout=2)
            self.assertFalse(worker.is_alive())

        with mock.patch.object(desktop, "apply_update", return_value=iter([desktop.DONE_MARKER])), \
                mock.patch.object(desktop.time, "sleep"), \
                mock.patch.object(desktop, "restart", side_effect=restart):
            result = make_request("POST", "/api/update/apply")
        self.assertEqual(result["status"], 200)
        self.assertEqual(observed, ["excluded"])
        self.assertIn(desktop.DONE_MARKER.encode(), result["body"])

    def test_headless_quit_refuses_busy_then_can_succeed(self):
        quitting = threading.Lock()
        stop = mock.Mock()
        with lifecycle.processing_dictation():
            desktop._quit_without_tray(stop, quitting)
        stop.assert_not_called()
        self.assertFalse(quitting.locked())
        desktop._quit_without_tray(stop, quitting)
        stop.assert_called_once_with()

    def test_real_headless_http_stops_on_sigint_and_sigterm(self):
        # Run a real server in a child. The child schedules its own signal only
        # after HTTP answers, so no timing guess can signal before setup.
        source = '''
import os, signal, socket, threading, time, urllib.request
from unittest import mock
from aparte import desktop
from aparte.config import Settings
with socket.socket() as probe:
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
number = getattr(signal, os.environ["TEST_SIGNAL"])
previous = signal.getsignal(number)
def trigger():
    for _ in range(200):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=.1).close()
            os.kill(os.getpid(), number)
            return
        except OSError:
            time.sleep(.01)
    os._exit(3)
threading.Thread(target=trigger, daemon=True).start()
with mock.patch.object(desktop, "build_tray", return_value=None), \\
     mock.patch.object(desktop, "migrate_hotkey_logging"), \\
     mock.patch.object(desktop, "already_running", return_value=None), \\
     mock.patch.object(desktop, "reclaim_port", return_value=None), \\
     mock.patch.object(desktop, "notify"):
    desktop.run_desktop("127.0.0.1", port, Settings(), open_browser=False)
assert signal.getsignal(number) == previous
print("stopped cleanly")
'''
        for name in ("SIGINT", "SIGTERM"):
            with self.subTest(signal=name):
                env = dict(os.environ, TEST_SIGNAL=name)
                result = subprocess.run([sys.executable, "-c", source], env=env,
                                        capture_output=True, text=True, timeout=8)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("stopped cleanly", result.stdout)


if __name__ == "__main__":
    unittest.main()
