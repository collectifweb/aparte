from __future__ import annotations

import json
import socket
import tempfile
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .clipboard import copy_text, paste_text
from .config import Settings, load_config, update_config
from .diagnostics import collect_diagnostics
from .polish import PolishOptions, build_polisher
from .transcription import build_transcriber

ASSETS_DIR = Path(__file__).resolve().parent / "assets"

# Static files served from the assets directory, with their content types.
STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/app.css": ("app.css", "text/css; charset=utf-8"),
    "/app.js": ("app.js", "application/javascript; charset=utf-8"),
    "/i18n.js": ("i18n.js", "application/javascript; charset=utf-8"),
    "/logo.svg": ("logo.svg", "image/svg+xml"),
}

# Models the desktop UI is allowed to switch to. Restricting this prevents the
# browser from triggering an arbitrary (possibly huge) model download.
ALLOWED_MODELS = ("small", "base", "tiny", "medium", "small.en", "base.en")

# Settings fields editable from the browser Settings panel.
EDITABLE_FIELDS = (
    "model",
    "default_style",
    "cleanup_level",
    "language",
    "device",
    "polish_backend",
    "nonbreaking_spaces",
    "replacements",
    "snippets",
)


def run_desktop(host: str, port: int, settings: Settings, open_browser: bool = True) -> None:
    port = _available_port(host, port)
    server = ThreadingHTTPServer((host, port), handler_factory(settings))
    url = f"http://{host}:{server.server_port}"
    if open_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    print(f"Aparté desktop running at {url}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping desktop server.")
    finally:
        server.server_close()


def _available_port(host: str, preferred_port: int) -> int:
    for port in [preferred_port, 0]:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind((host, port))
                return sock.getsockname()[1]
            except OSError:
                continue
    return 0


def handler_factory(settings: Settings) -> type[BaseHTTPRequestHandler]:
    # The Whisper model is expensive to load, so build each transcriber once and
    # reuse it across requests instead of reloading the model every time. The
    # cache is keyed by model name so the UI can toggle between models (e.g.
    # small and base) without paying the load cost on every switch.
    transcriber_cache: dict[str, object] = {}
    transcriber_lock = threading.Lock()

    def current_settings() -> Settings:
        # Reload from disk/env each request so changes saved from the Settings
        # tab take effect immediately, without restarting the server.
        return Settings.from_env()

    def get_transcriber(active: Settings, model: str | None = None):
        model = model or active.model
        with transcriber_lock:
            transcriber = transcriber_cache.get(model)
            if transcriber is None:
                transcriber = build_transcriber(
                    backend=active.transcriber,
                    model=model,
                    language=active.language,
                    whisper_cpp=active.whisper_cpp,
                    device=active.device,
                    compute_type=active.compute_type,
                )
                transcriber_cache[model] = transcriber
            return transcriber

    class DesktopHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            route = self.path.split("?", 1)[0]
            if route == "/" or self.path.startswith("/?"):
                self._serve_static("/")
                return
            if route in STATIC_FILES:
                self._serve_static(route)
                return
            if route == "/api/config":
                self._send_json(self._read_config())
                return
            if route == "/api/doctor":
                self._send_json(collect_diagnostics(current_settings()))
                return
            self.send_error(HTTPStatus.NOT_FOUND)

        def do_POST(self) -> None:
            try:
                if self.path == "/api/config":
                    self._handle_save_config()
                    return
                if self.path == "/api/polish":
                    active = current_settings()
                    payload = self._read_json()
                    text = str(payload.get("text", ""))
                    style = str(payload.get("style", "")) or active.default_style
                    cleanup_level = str(payload.get("cleanupLevel", "")) or active.cleanup_level
                    polisher = build_polisher(active.polish_backend, active.ollama_url, active.ollama_model)
                    output = polisher.polish(
                        text,
                        PolishOptions(
                            style=style,
                            language=active.language,
                            cleanup_level=cleanup_level,
                            replacements=active.replacements or {},
                            snippets=active.snippets or {},
                            nonbreaking_spaces=active.nonbreaking_spaces,
                        ),
                    )
                    self._send_json({"text": output})
                    return
                if self.path.split("?", 1)[0] == "/api/transcribe":
                    self._handle_transcribe()
                    return
                if self.path == "/api/copy":
                    payload = self._read_json()
                    backend = copy_text(str(payload.get("text", "")))
                    self._send_json({"ok": True, "backend": backend})
                    return
                if self.path == "/api/paste":
                    payload = self._read_json()
                    backend = paste_text(str(payload.get("text", "")))
                    self._send_json({"ok": True, "backend": backend})
                    return
                self.send_error(HTTPStatus.NOT_FOUND)
            except Exception as exc:
                self._send_json({"ok": False, "error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)

        def log_message(self, format: str, *args: object) -> None:
            return

        def _read_json(self) -> dict[str, object]:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length).decode("utf-8") if length else "{}"
            return json.loads(raw)

        def _handle_transcribe(self) -> None:
            content_type = self.headers.get("Content-Type", "")
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length)
            suffix = ".webm"
            if "audio/wav" in content_type or "audio/wave" in content_type:
                suffix = ".wav"
            elif "audio/mpeg" in content_type:
                suffix = ".mp3"
            handle = tempfile.NamedTemporaryFile(prefix="aparte-upload-", suffix=suffix, delete=False)
            path = Path(handle.name)
            handle.write(body)
            handle.close()
            try:
                active = current_settings()
                transcript = get_transcriber(active, self._requested_model(active)).transcribe(path).text
                self._send_json({"text": transcript})
            finally:
                path.unlink(missing_ok=True)

        def _requested_model(self, active: Settings) -> str:
            query = parse_qs(urlsplit(self.path).query)
            requested = (query.get("model") or [""])[0]
            return requested if requested in ALLOWED_MODELS else active.model

        def _read_config(self) -> dict[str, object]:
            config = load_config()
            data = {key: config.get(key) for key in EDITABLE_FIELDS}
            data["allowed_models"] = list(ALLOWED_MODELS)
            return data

        def _handle_save_config(self) -> None:
            payload = self._read_json()
            updates: dict[str, object] = {}
            for key in EDITABLE_FIELDS:
                if key in payload:
                    value = payload[key]
                    if key in {"replacements", "snippets"}:
                        value = {str(k): str(v) for k, v in dict(value).items()} if value else {}
                    elif key == "language":
                        value = (str(value).strip() or None) if value is not None else None
                    elif key == "nonbreaking_spaces":
                        value = bool(value)
                    else:
                        value = str(value)
                    updates[key] = value
            merged = update_config(updates)
            transcriber_cache.clear()
            self._send_json({"ok": True, "config": {key: merged.get(key) for key in EDITABLE_FIELDS}})

        def _send_json(self, payload: dict[str, object], status: HTTPStatus = HTTPStatus.OK) -> None:
            data = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _serve_static(self, route: str) -> None:
            filename, content_type = STATIC_FILES[route]
            try:
                data = (ASSETS_DIR / filename).read_bytes()
            except OSError:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            # Assets are read from disk on every request and the server is local,
            # so never let the browser serve a stale UI after an update.
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

    return DesktopHandler
