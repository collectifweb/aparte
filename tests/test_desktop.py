import argparse
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

from aparte import cli, desktop, macos_tray, model_download
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


class DelegationTest(unittest.TestCase):
    """Une dictée au raccourci démarre un processus neuf qui recharge Whisper —
    1,3 s à chaque fois, mesurées le 22/07 — pendant que l'application de bureau,
    à côté, garde le modèle en mémoire. Elle lui passe donc l'audio quand elle
    répond, et charge le sien quand elle ne répond pas."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.audio = Path(self.directory.name) / "dictee.wav"
        self.audio.write_bytes(b"RIFF....WAVEfake")
        environment = {
            "APARTE_CONFIG": str(Path(self.directory.name) / "config.json"),
            "MURMUR_CONFIG": "",
        }
        # Les surcharges d'environnement doivent partir : plusieurs d'entre elles
        # désactivent volontairement la délégation, et celles de la vraie session
        # feraient échouer les tests pour la mauvaise raison.
        environment.update({f"APARTE_{name}": "" for name in desktop._ENV_OVERRIDES})
        environment.update({f"MURMUR_{name}": "" for name in desktop._ENV_OVERRIDES})
        patcher = mock.patch.dict(os.environ, environment)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _serve(self, text):
        transcriber = SimpleNamespace(transcribe=lambda path: SimpleNamespace(text=text))
        patcher = mock.patch("aparte.desktop.build_transcriber", return_value=transcriber)
        patcher.start()
        self.addCleanup(patcher.stop)
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler_factory(Settings()))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return server.server_port

    def test_the_running_app_does_the_work(self):
        port = self._serve("la dictée transcrite ailleurs")
        got = desktop.transcribe_via_running_app(self.audio, "small", port=port)
        self.assertEqual(got, "la dictée transcrite ailleurs")

    def test_silence_comes_back_as_an_empty_string_not_as_a_failure(self):
        """Sans cette distinction, une dictée muette serait refaite en local pour
        rien — le modèle rechargé pour reproduire le même vide."""
        port = self._serve("")
        got = desktop.transcribe_via_running_app(self.audio, "small", port=port)
        self.assertEqual(got, "")
        self.assertIsNotNone(got)

    def test_nothing_listening_means_the_caller_loads_its_own(self):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            free_port = probe.getsockname()[1]
        self.assertIsNone(desktop.transcribe_via_running_app(self.audio, "small", port=free_port))

    def test_an_environment_override_keeps_the_work_local(self):
        """APARTE_LANGUAGE n'existe que dans ce processus ; l'application lancée
        relit le fichier de configuration et ignorerait la surcharge."""
        port = self._serve("ne devrait pas servir")
        with mock.patch.dict(os.environ, {"APARTE_LANGUAGE": "en"}):
            self.assertIsNone(desktop.transcribe_via_running_app(self.audio, "small", port=port))

    def test_a_missing_audio_file_is_not_a_crash(self):
        port = self._serve("peu importe")
        missing = Path(self.directory.name) / "disparu.wav"
        self.assertIsNone(desktop.transcribe_via_running_app(missing, "small", port=port))


class DelegationFallbackTest(unittest.TestCase):
    """Le chemin de secours ne sert presque jamais, donc personne ne le verrait
    se casser. C'est exactement pour ça qu'il est testé."""

    def _transcribe(self, delegated):
        settings = Settings()
        local = SimpleNamespace(transcribe=lambda path: SimpleNamespace(text="transcrit en local"))
        with mock.patch("aparte.cli.transcribe_via_running_app", return_value=delegated):
            with mock.patch("aparte.cli.build_transcriber", return_value=local) as build:
                got = cli.transcribe_path(Path("dictee.wav"), argparse.Namespace(polish=False), settings)
        return got, build

    def test_it_falls_back_when_the_app_is_not_running(self):
        got, build = self._transcribe(None)
        self.assertEqual(got, "transcrit en local")
        build.assert_called_once()

    def test_it_does_not_load_a_second_model_when_the_app_answered(self):
        got, build = self._transcribe("transcrit par l'application")
        self.assertEqual(got, "transcrit par l'application")
        build.assert_not_called()

    def test_a_text_file_never_goes_through_the_app(self):
        """Importer un .txt n'est pas une transcription : rien à déléguer."""
        local = SimpleNamespace(transcribe=lambda path: SimpleNamespace(text="collé depuis un fichier"))
        with mock.patch("aparte.cli.transcribe_via_running_app") as delegate:
            with mock.patch("aparte.cli.build_transcriber", return_value=local):
                got = cli.transcribe_path(Path("notes.txt"), argparse.Namespace(polish=False), Settings())
        self.assertEqual(got, "collé depuis un fichier")
        delegate.assert_not_called()


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

    def test_my_words_round_trip_and_blank_lines_are_dropped(self):
        """« Mes mots » arrive du navigateur en lignes de zone de texte : une
        ligne vide y est normale, elle ne doit pas devenir un mot vide."""
        path = Path(self.directory.name) / "config.json"
        body = json.dumps({"hotwords": ["Playwright", "  ", "", " Wayland "]}).encode("utf-8")
        res = make_request("POST", "/api/config", body)

        self.assertEqual(res["status"], int(HTTPStatus.OK))
        self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["hotwords"], ["Playwright", "Wayland"])
        self.assertEqual(
            json.loads(make_request("GET", "/api/config")["body"])["hotwords"],
            ["Playwright", "Wayland"],
        )
        self.assertEqual(Settings.from_env().hotwords, ("Playwright", "Wayland"))


class DarwinRouteGuardTest(unittest.TestCase):
    """On Darwin the resident server holds TCC permissions a browser lacks, so no
    HTTP route may trigger a system effect: paste, copy and update/apply are 404.
    The machine here is Linux, so the platform is mocked. The requests are valid
    for the Origin check — we prove the route guard, not the Origin guard."""

    _OURS = {"Host": "127.0.0.1:8765", "Origin": "http://127.0.0.1:8765"}

    def test_the_three_system_routes_are_404_on_darwin(self):
        for route in ("/api/paste", "/api/copy", "/api/update/apply"):
            with mock.patch.object(desktop, "is_macos", return_value=True):
                res = make_request("POST", route, b'{"text": "coucou"}', dict(self._OURS))
            self.assertEqual(res["status"], int(HTTPStatus.NOT_FOUND), route)

    def test_the_clipboard_routes_reach_their_handler_off_darwin(self):
        # Guard absent on Linux: the handler is reached (backends mocked so the
        # 200 doesn't depend on wl-copy/xclip being installed on the test host).
        with mock.patch.object(desktop, "is_macos", return_value=False):
            with mock.patch.object(desktop, "copy_text", return_value="pbcopy") as copy:
                res = make_request("POST", "/api/copy", b'{"text": "x"}', dict(self._OURS))
            self.assertEqual(res["status"], int(HTTPStatus.OK))
            copy.assert_called_once()

            with tempfile.TemporaryDirectory() as directory:
                env = {"APARTE_CONFIG": str(Path(directory) / "config.json"), "MURMUR_CONFIG": ""}
                with mock.patch.dict(os.environ, env):
                    with mock.patch.object(desktop, "paste_text", return_value="xdotool") as paste:
                        res = make_request("POST", "/api/paste", b'{"text": "x"}', dict(self._OURS))
            self.assertEqual(res["status"], int(HTTPStatus.OK))
            paste.assert_called_once()


class UpdateCheckRouteTest(unittest.TestCase):
    """The panel must not offer a button the server refuses. /api/update/apply is
    404 on Darwin (the guard above), so the check says so and the browser points at
    the menu-bar icon instead — where the update actually runs, in-process."""

    def _check(self, macos):
        with mock.patch.object(desktop, "is_macos", return_value=macos):
            with mock.patch.object(desktop, "check_update", return_value={"state": "available"}):
                res = make_request("GET", "/api/update/check")
        self.assertEqual(res["status"], int(HTTPStatus.OK))
        return json.loads(res["body"])

    def test_the_apply_button_is_offered_off_darwin(self):
        self.assertTrue(self._check(False)["can_apply"])

    def test_the_apply_button_is_withheld_on_darwin(self):
        self.assertFalse(self._check(True)["can_apply"])

    def test_both_languages_carry_the_strings_that_replace_it(self):
        # A string written in one language only would be announced in English to a
        # French screen reader — and these two are macOS-only, so nobody here sees them.
        i18n = (Path(desktop.__file__).resolve().parent / "assets" / "i18n.js").read_text(
            encoding="utf-8"
        )
        for key in ('"update.restart_required"', '"update.use_tray"', '"update.brew"'):
            self.assertEqual(i18n.count(key), 2, key)


class TrayStateRouteTest(unittest.TestCase):
    """Read-only, so it is allowed on Darwin: the CLI doctor cannot see the server's
    memory, and answering "start Aparté" under a live icon was the defect the first
    native run of M6 turned up. Absent off macOS, where there is no icon."""

    def _get(self, macos, outcome):
        with mock.patch.object(desktop, "is_macos", return_value=macos):
            with mock.patch.object(macos_tray, "_BUILD_OUTCOME", outcome):
                return make_request("GET", "/api/tray-state")

    def test_it_reports_what_the_server_built(self):
        res = self._get(True, "ok")
        self.assertEqual(res["status"], int(HTTPStatus.OK))
        self.assertEqual(json.loads(res["body"]), {"outcome": "ok"})

    def test_nothing_built_answers_null_rather_than_guessing(self):
        self.assertEqual(json.loads(self._get(True, None)["body"]), {"outcome": None})

    def test_the_route_is_absent_off_darwin(self):
        self.assertEqual(self._get(False, "ok")["status"], int(HTTPStatus.NOT_FOUND))


class ModelStateRouteTest(unittest.TestCase):
    """Read-only, so it is allowed on Darwin. The download is started by the
    application, never from here: a route that pulled 500 MB would be a system
    effect a browser could trigger, which is exactly what the Darwin guard exists
    to prevent. Absent while no download was ever started."""

    def setUp(self):
        model_download.reset_for_tests()
        self.addCleanup(model_download.reset_for_tests)

    def test_the_route_is_absent_while_nothing_was_started(self):
        res = make_request("GET", "/api/model-state")
        self.assertEqual(res["status"], int(HTTPStatus.NOT_FOUND))

    def test_it_reports_what_the_download_knows(self):
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.dict(os.environ, {"HF_HUB_CACHE": directory}):
                with mock.patch.object(model_download, "_has_module", return_value=True):
                    with mock.patch.object(model_download.threading, "Thread"):
                        model_download.start(Settings(model="small", transcriber="auto"))
                    res = make_request("GET", "/api/model-state")
        self.assertEqual(res["status"], int(HTTPStatus.OK))
        body = json.loads(res["body"])
        self.assertEqual(body["state"], "downloading")
        self.assertEqual(body["model"], "small")

    def test_the_route_is_a_get_so_the_darwin_guard_never_applies(self):
        # The guard only covers POST. Keeping this observation read-only is what
        # makes it allowed on a Mac at all.
        self.assertNotIn("/api/model-state", desktop._DARWIN_DISABLED_POST_ROUTES)


class RecordingStateRouteTest(unittest.TestCase):
    """On macOS the resident server records in memory (M4). Its state is observable
    through a read-only GET — allowed on Darwin — for the tray and doctor. Off
    Darwin there is no controller, so the route is absent. The dev host is Linux,
    so the platform is mocked; the controller is built at handler_factory time."""

    def _mac_handler(self):
        with mock.patch.object(desktop, "is_macos", return_value=True):
            return handler_factory(Settings())

    def test_the_state_is_idle_at_rest_on_darwin(self):
        res = make_request("GET", "/api/recording-state", handler_class=self._mac_handler())
        self.assertEqual(res["status"], int(HTTPStatus.OK))
        self.assertEqual(json.loads(res["body"]), {"state": "idle"})

    def test_the_route_is_absent_off_darwin(self):
        # Default factory (is_macos False here): no controller, route 404s.
        res = make_request("GET", "/api/recording-state")
        self.assertEqual(res["status"], int(HTTPStatus.NOT_FOUND))

    def test_the_controller_is_wired_only_on_darwin(self):
        self.assertIsNotNone(self._mac_handler()._recording_controller)
        self.assertIsNone(handler_factory(Settings())._recording_controller)

    def test_the_capture_transcriber_flows_through_the_server_model(self):
        # The controller's transcribe_fn reuses the server's cached transcriber (and
        # the same inference_lock, by construction) — never a self-HTTP call.
        fake = mock.Mock()
        fake.transcribe.return_value = SimpleNamespace(text="coucou")
        with tempfile.TemporaryDirectory() as directory:
            env = {"APARTE_CONFIG": str(Path(directory) / "config.json"), "MURMUR_CONFIG": ""}
            with mock.patch.dict(os.environ, env):
                with mock.patch.object(desktop, "build_transcriber", return_value=fake) as build:
                    controller = self._mac_handler()._recording_controller
                    self.assertEqual(controller._transcribe_fn(Path("/tmp/x.wav")), "coucou")
        build.assert_called_once()
        fake.transcribe.assert_called_once_with(Path("/tmp/x.wav"))


class HotkeyStateRouteTest(unittest.TestCase):
    """The global shortcut's registration is observable through a read-only GET
    (allowed on Darwin) for doctor and the tray (M6). serve_macos publishes the
    state on the handler class; without it — off macOS, or before the resident
    server runs — the route 404s. The route only reads a snapshot, no native code."""

    def test_it_returns_the_published_state(self):
        from aparte.macos_hotkey import HotkeyState

        Handler = handler_factory(Settings())
        Handler.hotkey_state = HotkeyState(registered=True, configured_key="ctrl+opt+d")
        res = make_request("GET", "/api/hotkey-state", handler_class=Handler)
        self.assertEqual(res["status"], int(HTTPStatus.OK))
        self.assertEqual(
            json.loads(res["body"]),
            {"registered": True, "configured_key": "ctrl+opt+d", "status": None, "error": None},
        )

    def test_a_registration_failure_surfaces_its_status(self):
        from aparte.macos_hotkey import HotkeyState

        Handler = handler_factory(Settings())
        Handler.hotkey_state = HotkeyState(configured_key="ctrl+opt+d", status=-9878, error="taken")
        res = make_request("GET", "/api/hotkey-state", handler_class=Handler)
        self.assertEqual(res["status"], int(HTTPStatus.OK))
        self.assertEqual(
            json.loads(res["body"]),
            {"registered": False, "configured_key": "ctrl+opt+d", "status": -9878, "error": "taken"},
        )

    def test_the_route_is_absent_until_a_state_is_published(self):
        # Default handler (no serve_macos): hotkey_state is None → 404, as off macOS.
        res = make_request("GET", "/api/hotkey-state")
        self.assertEqual(res["status"], int(HTTPStatus.NOT_FOUND))


class HandlerFactoryControllerTest(unittest.TestCase):
    """run_desktop needs the controller explicitly (M5b): it owns its lifecycle,
    the handler only observes it. return_controller gives (class, controller) —
    the controller on Darwin, None elsewhere, with no native import off macOS."""

    def test_the_flag_returns_none_off_darwin(self):
        with mock.patch.object(desktop, "is_macos", return_value=False):
            handler, controller = handler_factory(Settings(), return_controller=True)
        self.assertIsNone(controller)
        self.assertTrue(isinstance(handler, type))

    def test_the_flag_returns_the_wired_controller_on_darwin(self):
        with mock.patch.object(desktop, "is_macos", return_value=True):
            handler, controller = handler_factory(Settings(), return_controller=True)
        self.assertIsNotNone(controller)
        self.assertIs(handler._recording_controller, controller)

    def test_without_the_flag_the_call_is_unchanged(self):
        # Every existing caller passes only settings and gets the class back.
        self.assertTrue(isinstance(handler_factory(Settings()), type))


class _FakeRunServer:
    def __init__(self):
        self.server_port = 8765
        self.serve_forever_called = False
        self.closed = False

    def serve_forever(self):
        self.serve_forever_called = True

    def shutdown(self):
        pass

    def server_close(self):
        self.closed = True


class RunDesktopPlatformTest(unittest.TestCase):
    """run_desktop hands macOS off to the AppKit runner (serve_macos) and keeps the
    Linux path — serve directly, no runner. The native pieces are patched away."""

    def _patches(self, server, is_mac, controller):
        return (
            mock.patch.object(desktop, "already_running", return_value=None),
            mock.patch.object(desktop, "_available_port", side_effect=lambda h, p: p),
            mock.patch.object(desktop, "handler_factory", return_value=("H", controller)),
            mock.patch.object(desktop, "ThreadingHTTPServer", return_value=server),
            mock.patch.object(desktop, "is_macos", return_value=is_mac),
        )

    def test_macos_hands_off_to_the_runner_with_the_controller(self):
        server = _FakeRunServer()
        controller = object()
        patches = self._patches(server, is_mac=True, controller=controller)
        with patches[0], patches[1], patches[2], patches[3], patches[4], \
                mock.patch.object(desktop, "build_tray") as build_tray, \
                mock.patch("aparte.macos_runloop.serve_macos") as serve_macos:
            desktop.run_desktop("127.0.0.1", 8765, Settings(), open_browser=False)
        serve_macos.assert_called_once()
        args = serve_macos.call_args.args
        self.assertIs(args[0], server)
        self.assertIs(args[1], controller)
        build_tray.assert_not_called()          # macOS returns before the tray path
        self.assertFalse(server.serve_forever_called)

    def test_linux_serves_directly_without_the_runner(self):
        server = _FakeRunServer()
        patches = self._patches(server, is_mac=False, controller=None)
        with patches[0], patches[1], patches[2], patches[3], patches[4], \
                mock.patch.object(desktop, "build_tray", return_value=None), \
                mock.patch("aparte.macos_runloop.serve_macos") as serve_macos:
            desktop.run_desktop("127.0.0.1", 8765, Settings(), open_browser=False)
        serve_macos.assert_not_called()
        self.assertTrue(server.serve_forever_called)   # main-thread serve, unchanged
        self.assertTrue(server.closed)                 # finally: server_close


if __name__ == "__main__":
    unittest.main()
