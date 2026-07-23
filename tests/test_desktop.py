import json
import os
import socket
import tempfile
import threading
import unittest
from email.message import Message
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from aparte.config import Settings
from aparte.desktop import ASSETS_DIR, STATIC_FILES, already_running, handler_factory


def make_request(method, path, body=b"", headers=None, handler_class=None):
    """Drive a handler instance directly and capture the response it writes.

    ``handler_class`` lets several requests share one handler class, and with it
    the state the factory closes over — the transcription lock, in particular.
    """
    Handler = handler_class or handler_factory(Settings())
    handler = Handler.__new__(Handler)

    msg = Message()
    for key, value in (headers or {}).items():
        msg[key] = value
    if "Host" not in msg:
        msg["Host"] = "127.0.0.1:8765"  # every real client sends one
    if body:
        msg["Content-Length"] = str(len(body))

    handler.headers = msg
    handler.path = path
    handler.command = method
    handler.rfile = BytesIO(body)
    handler.wfile = BytesIO()
    captured = {"status": None, "headers": {}}
    handler.send_response = lambda code, *a: captured.__setitem__("status", int(code))
    handler.send_header = lambda k, v: captured["headers"].__setitem__(k, v)
    handler.end_headers = lambda: None
    handler.send_error = lambda code, *a, **k: captured.__setitem__("status", int(code))

    handler.do_GET() if method == "GET" else handler.do_POST()
    captured["body"] = handler.wfile.getvalue()
    return captured


class AlreadyRunningTest(unittest.TestCase):
    """Clicking the menu entry while the session's server runs must not start a
    second one: it would take a random port and add a second tray icon."""

    def _serve(self, handler):
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return server.server_port

    def test_finds_an_aparte_server(self):
        port = self._serve(handler_factory(Settings()))
        self.assertEqual(already_running("127.0.0.1", port), f"http://127.0.0.1:{port}")

    def test_ignores_a_port_nobody_is_listening_on(self):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            free_port = probe.getsockname()[1]
        self.assertIsNone(already_running("127.0.0.1", free_port, timeout=0.5))

    def test_ignores_another_application_holding_the_port(self):
        class Stranger(BaseHTTPRequestHandler):
            def do_GET(self):
                body = b'{"hello": "not aparte"}'
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                return

        port = self._serve(Stranger)
        self.assertIsNone(already_running("127.0.0.1", port))


class StaticAssetsTest(unittest.TestCase):
    def test_all_static_files_exist_on_disk(self):
        for filename, _ctype in STATIC_FILES.values():
            self.assertTrue((ASSETS_DIR / filename).exists(), filename)

    def test_index_served_at_root(self):
        res = make_request("GET", "/")
        self.assertEqual(res["status"], int(HTTPStatus.OK))
        self.assertIn("<title>Aparté</title>".encode("utf-8"), res["body"])
        self.assertEqual(res["headers"]["Content-Type"], "text/html; charset=utf-8")

    def test_app_js_uses_browser_wav_recording(self):
        res = make_request("GET", "/app.js")
        self.assertEqual(res["status"], int(HTTPStatus.OK))
        self.assertIn(b"startWavRecording", res["body"])
        self.assertNotIn(b"new MediaRecorder", res["body"])


class DoctorEndpointTest(unittest.TestCase):
    def test_doctor_returns_structured_summary(self):
        res = make_request("GET", "/api/doctor")
        self.assertEqual(res["status"], int(HTTPStatus.OK))
        data = json.loads(res["body"])
        self.assertIn("summary", data)
        self.assertIn("checks", data)
        self.assertIn("ready", data["summary"])


class OriginCheckTest(unittest.TestCase):
    """A page served from anywhere else must not be able to drive the server."""

    def _post_config(self, headers):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            with mock.patch.dict(os.environ, {"APARTE_CONFIG": str(path), "MURMUR_CONFIG": ""}):
                body = json.dumps({"default_style": "formal"}).encode("utf-8")
                return make_request("POST", "/api/config", body, headers)

    def test_a_foreign_origin_is_refused(self):
        res = make_request(
            "POST",
            "/api/paste",
            b'{"text": "coucou"}',
            {"Host": "127.0.0.1:8765", "Origin": "https://exemple.invalid"},
        )
        self.assertEqual(res["status"], int(HTTPStatus.FORBIDDEN))

    def test_a_rebound_hostname_is_refused(self):
        """A domain rebound to 127.0.0.1 reaches us with a Host and Origin that
        agree with each other — but name the attacker, not us."""
        res = make_request(
            "POST",
            "/api/paste",
            b'{"text": "coucou"}',
            {"Host": "exemple.invalid:8765", "Origin": "http://exemple.invalid:8765"},
        )
        self.assertEqual(res["status"], int(HTTPStatus.FORBIDDEN))

    def test_our_own_page_is_accepted(self):
        res = self._post_config({"Host": "127.0.0.1:8765", "Origin": "http://127.0.0.1:8765"})
        self.assertEqual(res["status"], int(HTTPStatus.OK))

    def test_a_request_without_origin_is_accepted(self):
        """curl and the CLI send no Origin header at all."""
        res = self._post_config({"Host": "127.0.0.1:8765"})
        self.assertEqual(res["status"], int(HTTPStatus.OK))


class HistoryEndpointTest(unittest.TestCase):
    def test_a_dictation_posted_by_the_browser_comes_back_in_the_list(self):
        with tempfile.TemporaryDirectory() as runtime:
            # Le APARTE_CONFIG est indispensable : sans lui le serveur lit la
            # vraie config, et si history_persist y est vrai, le test écrit dans
            # l'historique réel de l'utilisateur au lieu du dossier temporaire.
            environment = {
                "APARTE_RUNTIME_DIR": runtime,
                "APARTE_CONFIG": str(Path(runtime) / "config.json"),
                "MURMUR_CONFIG": "",
            }
            with mock.patch.dict(os.environ, environment):
                body = json.dumps({"text": "une dictée"}).encode("utf-8")
                posted = make_request("POST", "/api/history", body)

                self.assertEqual(posted["status"], int(HTTPStatus.OK))
                self.assertEqual(json.loads(posted["body"])["entries"][0]["text"], "une dictée")

                listed = json.loads(make_request("GET", "/api/history")["body"])["entries"]
                self.assertEqual([item["text"] for item in listed], ["une dictée"])

    def test_a_foreign_page_cannot_write_to_the_history(self):
        res = make_request(
            "POST",
            "/api/history",
            b'{"text": "injecte"}',
            {"Host": "127.0.0.1:8765", "Origin": "https://exemple.invalid"},
        )
        self.assertEqual(res["status"], int(HTTPStatus.FORBIDDEN))


class MicrophoneEndpointTest(unittest.TestCase):
    def test_the_settings_panel_gets_name_and_label_pairs(self):
        devices = [{"name": "plughw:CARD=Mini,DEV=0", "label": "Razer Seiren Mini, USB Audio"}]
        with mock.patch("aparte.desktop.list_microphones", return_value=devices):
            res = make_request("GET", "/api/microphones")
        self.assertEqual(res["status"], int(HTTPStatus.OK))
        self.assertEqual(json.loads(res["body"])["devices"], devices)


class ConfigEndpointTest(unittest.TestCase):
    def test_paste_mode_round_trips(self):
        """A field missing from EDITABLE_FIELDS is dropped in silence, both ways."""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            with mock.patch.dict(os.environ, {"APARTE_CONFIG": str(path), "MURMUR_CONFIG": ""}):
                body = json.dumps({"paste_mode": "terminal"}).encode("utf-8")
                res = make_request("POST", "/api/config", body)

                self.assertEqual(res["status"], int(HTTPStatus.OK))
                self.assertEqual(json.loads(make_request("GET", "/api/config")["body"])["paste_mode"], "terminal")

    def test_short_text_words_lands_as_a_number(self):
        """A <select> posts strings; the polisher compares it to a word count."""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            with mock.patch.dict(os.environ, {"APARTE_CONFIG": str(path), "MURMUR_CONFIG": ""}):
                body = json.dumps({"short_text_words": "5", "microphone": "plughw:CARD=Mini,DEV=0"})
                res = make_request("POST", "/api/config", body.encode("utf-8"))

                self.assertEqual(res["status"], int(HTTPStatus.OK))
                saved = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(saved["short_text_words"], 5)
                self.assertEqual(saved["microphone"], "plughw:CARD=Mini,DEV=0")

    def test_nonbreaking_spaces_round_trips_as_a_boolean(self):
        """The settings form posts a checkbox; it must not land as the string "False"."""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            with mock.patch.dict(os.environ, {"APARTE_CONFIG": str(path), "MURMUR_CONFIG": ""}):
                body = json.dumps({"nonbreaking_spaces": False}).encode("utf-8")
                res = make_request("POST", "/api/config", body)

                self.assertEqual(res["status"], int(HTTPStatus.OK))
                self.assertIs(json.loads(res["body"])["config"]["nonbreaking_spaces"], False)
                self.assertIs(json.loads(path.read_text(encoding="utf-8"))["nonbreaking_spaces"], False)
                self.assertIs(json.loads(make_request("GET", "/api/config")["body"])["nonbreaking_spaces"], False)


class LivePreviewTest(unittest.TestCase):
    """L'aperçu au fil de la parole re-transcrit l'enregistrement en cours toutes
    les secondes environ. Le serveur est multi-fils et le modèle Whisper est un
    seul objet partagé : au moment où l'utilisateur arrête de parler, un aperçu
    et la transcription finale se croisent forcément. L'aperçu doit céder son
    tour ; la finale, elle, doit attendre le sien et rendre son texte."""

    def setUp(self):
        self.started = threading.Event()
        self.release = threading.Event()
        test = self

        class BlockingTranscriber:
            def transcribe(self, path):
                test.started.set()
                test.release.wait(5)
                return SimpleNamespace(text="la dictée")

        self.transcriber = BlockingTranscriber()
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        # Sans APARTE_CONFIG, current_settings() lit la vraie configuration de
        # l'utilisateur au lieu d'un fichier jetable.
        environment = {
            "APARTE_CONFIG": str(Path(self.directory.name) / "config.json"),
            "MURMUR_CONFIG": "",
        }
        patcher = mock.patch.dict(os.environ, environment)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_preview_gives_up_its_turn_while_a_transcription_runs(self):
        Handler = handler_factory(Settings())
        with mock.patch("aparte.desktop.build_transcriber", return_value=self.transcriber):
            final = {}
            thread = threading.Thread(
                target=lambda: final.update(
                    res=make_request("POST", "/api/transcribe", b"RIFF", handler_class=Handler)
                )
            )
            thread.start()
            self.addCleanup(thread.join, 5)
            self.addCleanup(self.release.set)
            self.assertTrue(self.started.wait(5), "la transcription finale n'a jamais démarré")

            preview = make_request("POST", "/api/transcribe?preview=1", b"RIFF", handler_class=Handler)
            self.assertEqual(preview["status"], int(HTTPStatus.OK))
            payload = json.loads(preview["body"])
            self.assertIsNone(payload["text"])
            self.assertTrue(payload["busy"])

            self.release.set()
            thread.join(5)
            self.assertEqual(json.loads(final["res"]["body"])["text"], "la dictée")

    def test_a_preview_transcribes_when_nothing_else_is_running(self):
        self.release.set()
        Handler = handler_factory(Settings())
        with mock.patch("aparte.desktop.build_transcriber", return_value=self.transcriber):
            preview = make_request("POST", "/api/transcribe?preview=1", b"RIFF", handler_class=Handler)
        self.assertEqual(preview["status"], int(HTTPStatus.OK))
        self.assertEqual(json.loads(preview["body"])["text"], "la dictée")

    def test_the_setting_round_trips(self):
        """Un réglage absent d'EDITABLE_FIELDS est ignoré en silence, des deux côtés."""
        path = Path(self.directory.name) / "config.json"
        body = json.dumps({"live_preview": False}).encode("utf-8")
        res = make_request("POST", "/api/config", body)

        self.assertEqual(res["status"], int(HTTPStatus.OK))
        self.assertIs(json.loads(path.read_text(encoding="utf-8"))["live_preview"], False)
        self.assertIs(json.loads(make_request("GET", "/api/config")["body"])["live_preview"], False)


if __name__ == "__main__":
    unittest.main()
