from __future__ import annotations

import json
import socket
import tempfile
import threading
import urllib.request
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from . import history
from .clipboard import copy_text, paste_text
from .config import Settings, load_config, update_config
from .diagnostics import collect_diagnostics
from .polish import PolishOptions, build_polisher
from .transcription import build_transcriber
from .tray import build_tray
from .update import DONE_MARKER, apply_update, check_update, restart

ASSETS_DIR = Path(__file__).resolve().parent / "assets"

# Static files served from the assets directory, with their content types.
STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/app.css": ("app.css", "text/css; charset=utf-8"),
    "/app.js": ("app.js", "application/javascript; charset=utf-8"),
    "/i18n.js": ("i18n.js", "application/javascript; charset=utf-8"),
    "/logo.svg": ("logo.svg", "image/svg+xml"),
}

# Names a browser can legitimately reach us under. A request arriving under any
# other name was aimed at someone else's address that now resolves here — the
# shape of a DNS rebinding attack — even when its Origin agrees with its Host.
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})

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
    "paste_mode",
    "history_persist",
    "replacements",
    "snippets",
)


def run_desktop(host: str, port: int, settings: Settings, open_browser: bool = True) -> None:
    # The menu launcher and the autostart entry run the same command, and the
    # server is already up from login. Starting a second one would take a random
    # port and put a second icon in the tray, so hand over to the running one.
    running = already_running(host, port)
    if running:
        print(f"Aparté is already running at {running}")
        if open_browser:
            webbrowser.open(running)
        return

    port = _available_port(host, port)
    server = ThreadingHTTPServer((host, port), handler_factory(settings))
    url = f"http://{host}:{server.server_port}"
    if open_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    print(f"Aparté desktop running at {url}")
    # The tray icon needs GTK on the main thread, so the server moves off it.
    # Without the system bindings there is no tray, and nothing changes.
    tray = build_tray(url, settings, server.shutdown)
    try:
        if tray is None:
            server.serve_forever()
        else:
            threading.Thread(target=server.serve_forever, daemon=True).start()
            tray.run()
    except KeyboardInterrupt:
        print("\nStopping desktop server.")
    finally:
        server.server_close()


def already_running(host: str, port: int, timeout: float = 2.0) -> str | None:
    """The address of an Aparté server already listening here, if there is one.

    Anything else holding the port — another application, a stale service — is
    not us, and the caller falls back to its usual free-port search.
    """
    url = f"http://{host}:{port}"
    try:
        with urllib.request.urlopen(f"{url}/api/config", timeout=timeout) as response:
            payload = json.loads(response.read())
    except (OSError, ValueError):
        return None
    return url if isinstance(payload, dict) and "allowed_models" in payload else None


def _available_port(host: str, preferred_port: int) -> int:
    for port in [preferred_port, 0]:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                # Same option the real server binds with. Without it, the probe
                # fails on connections still in TIME_WAIT and the app comes back
                # from an update on a different port than the browser watches.
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
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
            if route == "/api/history":
                active = current_settings()
                self._send_json({"entries": history.entries(active.history_persist)})
                return
            if route == "/api/update/check":
                # Only reach the network when the user asks for it: opening the
                # panel must not phone home on its own.
                fetch = (parse_qs(urlsplit(self.path).query).get("fetch") or [""])[0] == "1"
                self._send_json(check_update(fetch=fetch))
                return
            self.send_error(HTTPStatus.NOT_FOUND)

        def do_POST(self) -> None:
            if not self._origin_is_ours():
                self.send_error(HTTPStatus.FORBIDDEN)
                return
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
                    backend = paste_text(str(payload.get("text", "")), current_settings().paste_mode)
                    self._send_json({"ok": True, "backend": backend})
                    return
                if self.path == "/api/history":
                    active = current_settings()
                    payload = self._read_json()
                    history.record(str(payload.get("text", "")), active.history_persist)
                    self._send_json({"entries": history.entries(active.history_persist)})
                    return
                if self.path == "/api/update/apply":
                    self._handle_update_apply()
                    return
                self.send_error(HTTPStatus.NOT_FOUND)
            except Exception as exc:
                self._send_json({"ok": False, "error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)

        def log_message(self, format: str, *args: object) -> None:
            return

        def _origin_is_ours(self) -> bool:
            """Reject POSTs sent by a page that isn't the one we serve.

            The server only listens on the loopback address, so nothing on the
            network can reach it — but any web page open in the browser can post
            here blindly, and /api/paste types text into the focused window.
            Browsers send Origin on every POST, and the page we serve always
            names our own address; command-line clients send none at all.

            Origin alone is not enough: a page whose domain has been rebound to
            127.0.0.1 arrives with a matching Host and Origin, both its own. So
            the address we were reached under has to be one of ours too.
            """
            host = self.headers.get("Host", "")
            try:
                hostname = urlsplit(f"//{host}").hostname
            except ValueError:
                return False
            server = getattr(self, "server", None)
            bound = server.server_address[0] if server else ""
            # `--host 0.0.0.0` serves every interface, so every name is ours and
            # there is nothing left to compare against.
            if bound not in {"0.0.0.0", "::"} and hostname not in LOOPBACK_HOSTS and hostname != bound:
                return False
            origin = self.headers.get("Origin")
            return origin is None or origin == f"http://{host}"

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

        def _handle_update_apply(self) -> None:
            """Stream the update log line by line, then restart if it worked.

            Sent without a Content-Length so the browser can read the log as it
            arrives: `git pull` plus `pip install` can take a minute, and a
            frozen panel looks like a crash.
            """
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            updated = False
            for line in apply_update():
                updated = updated or line == DONE_MARKER
                self.wfile.write(f"{line}\n".encode("utf-8"))
                self.wfile.flush()
            if updated:
                # This process still has the old modules loaded, so it cannot
                # serve what it just installed. Leave the response time to reach
                # the browser before replacing ourselves.
                threading.Timer(1.0, restart).start()

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
                    elif key in {"nonbreaking_spaces", "history_persist"}:
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
