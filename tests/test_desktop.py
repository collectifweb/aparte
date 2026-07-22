import json
import os
import tempfile
import unittest
from email.message import Message
from http import HTTPStatus
from io import BytesIO
from pathlib import Path
from unittest import mock

from aparte.config import Settings
from aparte.desktop import ASSETS_DIR, STATIC_FILES, handler_factory


def make_request(method, path, body=b"", headers=None):
    """Drive a handler instance directly and capture the response it writes."""
    Handler = handler_factory(Settings())
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
            with mock.patch.dict(os.environ, {"APARTE_RUNTIME_DIR": runtime}):
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


if __name__ == "__main__":
    unittest.main()
