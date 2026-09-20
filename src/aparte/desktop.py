from __future__ import annotations

import argparse
import json
import socket
import tempfile
import threading
import urllib.request
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlsplit

from . import history, model_download, recovery
from .audio import list_microphones, sweep_orphan_recordings
from .clipboard import copy_text, paste_text
from .config import Settings, get_env, load_config, positive_int, update_config
from .diagnostics import collect_diagnostics
from .macos_recording import RecordingController
from .platform_dispatch import is_macos
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

# On macOS the resident server holds TCC permissions (Microphone, Accessibility)
# that a browser or a stray local process does not. A route that used them from
# HTTP would become a privilege proxy, so on Darwin every system-effect POST is
# refused — insertion, clipboard and update happen through the shortcut, the tray
# or the CLI instead (see docs/plan-portage-macos-m3.md). The criterion is
# "system effect triggered over HTTP", not "needs TCC": /api/update/apply runs
# git/pip and restarts, and stays forbidden too.
_DARWIN_DISABLED_POST_ROUTES = frozenset({"/api/paste", "/api/copy", "/api/update/apply"})

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
    "trailing_space",
    "numbers_from",
    "short_text_words",
    "paste_mode",
    "history_persist",
    "microphone",
    "beep",
    "live_preview",
    "hotwords",
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

    # Past the hand-over above, this process is the one Aparté: a good moment to
    # drop any capture an earlier run was killed before it could delete.
    sweep_orphan_recordings()

    port = _available_port(host, port)
    handler, controller = handler_factory(settings, return_controller=True)
    server = ThreadingHTTPServer((host, port), handler)
    url = f"http://{host}:{server.server_port}"
    if open_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    print(f"Aparté desktop running at {url}")
    cleanup_stop = threading.Event()
    threading.Thread(target=_maintain_recovery, args=(cleanup_stop,), daemon=True,
                     name="aparte-recovery-cleanup").start()
    if is_macos():
        # A Mac install is meant to be "open it, grant two permissions". Waiting
        # in silence for 500 MB on the first dictation is not that, so fetch the
        # model now and let the page watch it. Darwin only: on Linux the install
        # is a checkout whose README already explains the one-time fetch, and
        # spending someone's bandwidth at launch would be a change of behaviour.
        model_download.start(settings)
        # The global shortcut only works while a live AppKit run loop pumps its
        # events, and that loop must own the main thread — so the server moves to a
        # daemon thread (as it does under the GTK tray on Linux). macos_runloop owns
        # the shortcut, the run loop and the ordered teardown; imported here so no
        # AppKit/Carbon piece loads off macOS.
        from .macos_runloop import serve_macos

        try:
            serve_macos(server, controller, settings, url=url)
        finally:
            cleanup_stop.set()
        return
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
        cleanup_stop.set()
        server.server_close()


def _maintain_recovery(stop: threading.Event, interval: float = 60.0) -> None:
    while not stop.is_set():
        try:
            recovery.sweep()
            sweep_orphan_recordings(failed_uploads_only=True)
        except (OSError, RuntimeError, ValueError):
            pass
        stop.wait(interval)


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


# Réglages qui, posés dans l'environnement, n'existent que dans le processus qui
# les a reçus. L'application déjà lancée, elle, relit le fichier de configuration :
# lui confier l'audio ferait passer ces surcharges à la trappe, en silence.
_ENV_OVERRIDES = ("TRANSCRIBER", "MODEL", "LANGUAGE", "DEVICE", "COMPUTE_TYPE", "WHISPER_CPP")

# Une longue dictée peut prendre du temps ; attendre reste préférable à repartir
# de zéro, puisque le repli rechargerait le modèle pour refaire le même travail.
DELEGATE_TIMEOUT = 300.0


def transcribe_via_running_app(
    audio_path: Path,
    model: str,
    host: str = "127.0.0.1",
    port: int = 8765,
) -> str | None:
    """Faire transcrire par l'application déjà lancée. None si c'est impossible.

    Une dictée au raccourci démarre sinon un processus neuf qui recharge Whisper
    depuis le disque à chaque fois — environ 1,3 s mesurées à chaud — alors que
    le serveur de bureau, juste à côté, garde le modèle en mémoire. Quand il n'est
    pas là, l'appelant charge le sien comme avant.

    Une chaîne vide est une réponse valide : elle veut dire « aucune parole ». Le
    None est réservé à « je n'ai pas pu demander ».
    """
    if any(get_env(name) for name in _ENV_OVERRIDES):
        return None
    url = already_running(host, port)
    if url is None:
        return None
    try:
        body = audio_path.read_bytes()
    except OSError:
        return None
    request = urllib.request.Request(
        f"{url}/api/transcribe?model={quote(model)}",
        data=body,
        method="POST",
        headers={"Content-Type": "audio/wav"},
    )
    try:
        with urllib.request.urlopen(request, timeout=DELEGATE_TIMEOUT) as response:
            payload = json.loads(response.read())
    except (OSError, ValueError):
        return None
    text = payload.get("text") if isinstance(payload, dict) else None
    return text if isinstance(text, str) else None


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


def handler_factory(
    settings: Settings, *, return_controller: bool = False
) -> type[BaseHTTPRequestHandler] | tuple[type[BaseHTTPRequestHandler], RecordingController | None]:
    # The Whisper model is expensive to load, so build each transcriber once and
    # reuse it across requests instead of reloading the model every time. The
    # cache is keyed by model name so the UI can toggle between models (e.g.
    # small and base) without paying the load cost on every switch.
    transcriber_cache: dict[tuple, object] = {}
    transcriber_lock = threading.Lock()
    # A Whisper model is one object shared by every request, and this server is
    # threaded: the live preview and the final transcription of the same
    # recording overlap by design at the moment the user stops talking. Run one
    # inference at a time. A preview takes this lock without waiting and gives
    # up its turn when it is busy, so previews can never queue up behind each
    # other or delay the transcription that actually matters.
    inference_lock = threading.Lock()

    def current_settings() -> Settings:
        # Reload from disk/env each request so changes saved from the Settings
        # tab take effect immediately, without restarting the server.
        return Settings.from_env()

    def get_transcriber(active: Settings, model: str | None = None):
        model = model or active.model
        backend = active.transcriber
        if is_macos() and model_download.effective_backend(active) == "faster-whisper":
            local_model = model_download.cached_model_path(model)
            if local_model is None:
                raise RuntimeError(
                    "Le modèle n’est pas prêt. Dans le menu Aparté, choisis "
                    "« Préparer le modèle… », puis réessaie."
                )
            # A repository name lets WhisperModel fetch missing files itself.
            # Pass the verified directory and pin this engine even for 'auto':
            # its OpenAI fallback could otherwise start another download.
            model = str(local_model)
            backend = "faster-whisper"
        # La clé porte tout ce qui construit le transcripteur, pas seulement le
        # modèle. `_handle_save_config` vide bien le cache, mais une config
        # modifiée ailleurs — édition à la main, appel externe à
        # `update_config()`, synchronisation par un tiers — rendrait sinon un
        # transcripteur périmé sans que rien ne le signale.
        key = (
            backend,
            model,
            active.language,
            active.device,
            active.compute_type,
            active.whisper_cpp,
            active.hotwords,
        )
        with transcriber_lock:
            transcriber = transcriber_cache.get(key)
            if transcriber is None:
                transcriber = build_transcriber(
                    backend=backend,
                    model=model,
                    language=active.language,
                    whisper_cpp=active.whisper_cpp,
                    device=active.device,
                    compute_type=active.compute_type,
                    hotwords=active.hotwords,
                )
                transcriber_cache[key] = transcriber
            return transcriber

    class DesktopHandler(BaseHTTPRequestHandler):
        # The in-process macOS recorder, wired below on Darwin only. None on Linux,
        # where the global shortcut drives detached CLI recorders instead.
        _recording_controller = None
        # The macOS global-shortcut registration, published here by serve_macos
        # (M5b/M5d). None on Linux and until serve_macos runs, which makes the
        # read-only /api/hotkey-state route 404 off the resident macOS server.
        hotkey_state = None

        def do_GET(self) -> None:
            if not self._host_is_ours():
                self.send_error(HTTPStatus.FORBIDDEN)
                return
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
                # Pass the shortcut state this server already owns, so the macOS
                # hotkey check reads it in-process instead of self-requesting.
                self._send_json(
                    collect_diagnostics(current_settings(), hotkey_state=self.hotkey_state)
                )
                return
            if route == "/api/recovery":
                try:
                    self._send_json({"entries": recovery.entries()})
                except (OSError, RuntimeError):
                    self._send_json({"error": "Recovery unavailable"}, HTTPStatus.SERVICE_UNAVAILABLE)
                return
            if route == "/api/history":
                active = current_settings()
                self._send_json({"entries": history.entries(active.history_persist)})
                return
            if route == "/api/microphones":
                self._send_json({"devices": list_microphones()})
                return
            if route == "/api/update/check":
                # Only reach the network when the user asks for it: opening the
                # panel must not phone home on its own.
                fetch = (parse_qs(urlsplit(self.path).query).get("fetch") or [""])[0] == "1"
                payload = check_update(fetch=fetch)
                # Où la route d'application est refusée (invariant Darwin), le
                # panneau ne doit pas proposer un bouton qui rendra 404 : sur Mac
                # la mise à jour part de l'icône de barre de menus.
                payload["can_apply"] = not (
                    is_macos() and "/api/update/apply" in _DARWIN_DISABLED_POST_ROUTES
                )
                self._send_json(payload)
                return
            if route == "/api/recording-state":
                # Read-only, so it stays allowed on Darwin: the tray (M6) and
                # doctor observe the in-process controller's state here. Absent
                # (404) off macOS, where there is no controller.
                controller = self._recording_controller
                if controller is None:
                    self.send_error(HTTPStatus.NOT_FOUND)
                    return
                self._send_json({"state": controller.state})
                return
            if route == "/api/hotkey-state":
                # Read-only, so it stays allowed on Darwin: doctor and the tray
                # (M6) observe whether the global shortcut registered. serve_macos
                # owns and publishes this state; absent (404) off macOS and until
                # the resident server sets it, where there is no shortcut.
                state = self.hotkey_state
                if state is None:
                    self.send_error(HTTPStatus.NOT_FOUND)
                    return
                self._send_json(
                    {
                        "registered": state.registered,
                        "configured_key": state.configured_key,
                        "status": state.status,
                        "error": state.error,
                    }
                )
                return
            if route == "/api/model-state":
                # Read-only, so it stays allowed on Darwin: the download is
                # started by the application (run_desktop), never from here — a
                # route that pulled 500 MB would be a system effect reachable
                # from a browser. 404 while no download was ever started, which
                # is every Linux run and any Mac whose model is already there.
                state = model_download.progress(current_settings())
                if state is None:
                    self.send_error(HTTPStatus.NOT_FOUND)
                    return
                self._send_json(state)
                return
            if route == "/api/tray-state":
                # Read-only, so it stays allowed on Darwin: `aparte doctor` runs in
                # its own process and cannot see whether the *server* built its
                # menu-bar icon. Without this it answered "start Aparté to show the
                # icon" while the icon was in the bar — the M8 defect on the hotkey
                # check, in its own words. Absent (404) off macOS.
                if not is_macos():
                    self.send_error(HTTPStatus.NOT_FOUND)
                    return
                from .macos_tray import tray_build_outcome

                self._send_json({"outcome": tray_build_outcome()})
                return
            self.send_error(HTTPStatus.NOT_FOUND)

        def do_POST(self) -> None:
            if not self._origin_is_ours():
                self.send_error(HTTPStatus.FORBIDDEN)
                return
            # Deliberate route guard, placed after the Origin check (foreign
            # origin → 403) and before dispatch (forbidden route on Darwin → 404).
            if is_macos() and self.path.split("?", 1)[0] in _DARWIN_DISABLED_POST_ROUTES:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            try:
                if self.path in {"/api/recovery/retry", "/api/recovery/delete"}:
                    self._handle_recovery()
                    return
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
                            trailing_space=active.trailing_space,
                            numbers_from=active.numbers_from,
                            short_text_words=active.short_text_words,
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
            if not self._host_is_ours():
                return False
            host = self.headers.get("Host", "")
            origin = self.headers.get("Origin")
            return origin is None or origin == f"http://{host}"

        def _host_is_ours(self) -> bool:
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
            return bool(hostname)

        def _handle_recovery(self) -> None:
            payload = self._read_json()
            if not isinstance(payload, dict) or not isinstance(payload.get("id"), str):
                self._send_json({"error": "A capture identifier is required."}, HTTPStatus.BAD_REQUEST)
                return
            identifier = payload["id"]
            try:
                if self.path == "/api/recovery/delete":
                    recovery.discard(identifier)
                    self._send_json({"ok": True})
                    return
                with recovery.claim(identifier) as item:
                    active = current_settings()
                    raw = item.raw_text
                    if raw is None:
                        # Never delegate back to our own HTTP server: this is
                        # its cached model, shared with regular transcriptions.
                        inference_lock.acquire()
                        try:
                            transcriber = get_transcriber(active)
                            raw = transcriber.transcribe(item.audio_path).text
                        finally:
                            inference_lock.release()
                        recovery.update_raw(item, raw)
                    if payload.get("raw") is True or not raw.strip():
                        output = raw
                    else:
                        from .cli import polish_text

                        output = polish_text(raw, argparse.Namespace(), active)
                    if output.strip():
                        history.record(output, active.history_persist)
                    # Keep the capture until explicit deletion/expiry. A lost
                    # response must not destroy the only recoverable dictation.
                    self._send_json({"text": output})
            except recovery.RecoveryBusy:
                self._send_json({"error": "This capture is already being recovered."}, HTTPStatus.CONFLICT)
            except recovery.RecoveryNotFound:
                self._send_json({"error": "This capture has expired or was deleted."}, HTTPStatus.GONE)
            except ValueError:
                self._send_json({"error": "Invalid capture identifier."}, HTTPStatus.BAD_REQUEST)

        def _read_json(self) -> dict[str, object]:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length).decode("utf-8") if length else "{}"
            return json.loads(raw)

        def _handle_transcribe(self) -> None:
            content_type = self.headers.get("Content-Type", "")
            length = int(self.headers.get("Content-Length", "0"))
            # Always drain the body, even for a preview we are about to drop:
            # leaving it unread would desynchronise the connection.
            body = self.rfile.read(length)
            preview = self._flag("preview")
            acquired = inference_lock.acquire(blocking=not preview)
            if not acquired:
                self._send_json({"text": None, "busy": True})
                return
            suffix = ".webm"
            if "audio/wav" in content_type or "audio/wave" in content_type:
                suffix = ".wav"
            elif "audio/mpeg" in content_type:
                suffix = ".mp3"
            path = None
            uploaded = False
            transcript = None
            try:
                with tempfile.NamedTemporaryFile(prefix="aparte-upload-", suffix=suffix, delete=False) as handle:
                    path = Path(handle.name)
                    handle.write(body)
                uploaded = True
                active = current_settings()
                transcriber = get_transcriber(active, self._requested_model(active))
                transcript = transcriber.transcribe(path).text
                self._send_json({"text": transcript})
            except Exception:
                # Only final browser captures opt in. CLI delegation retains its
                # original itself, and previews are disposable snapshots.
                if uploaded and not preview and self._flag("recover"):
                    try:
                        recovery.save_failure(path, raw_text=transcript)
                    except (OSError, RuntimeError) as storage_error:
                        # Keep the existing private upload when a second copy cannot
                        # be written. Mark only this FAILED upload for expiry; active
                        # uploads must never be swept during a long inference.
                        retained = path
                        failed = path.with_name(path.name.replace("aparte-upload-", "aparte-failed-upload-", 1))
                        try:
                            path.rename(failed)
                            retained = failed
                        except OSError:
                            pass
                        path = None
                        raise RuntimeError(
                            f"Recovery storage unavailable. Audio retained at {retained}; "
                            "import it again after freeing disk space."
                        ) from storage_error
                raise
            finally:
                try:
                    if path is not None:
                        path.unlink(missing_ok=True)
                finally:
                    inference_lock.release()

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

        def _flag(self, name: str) -> bool:
            return (parse_qs(urlsplit(self.path).query).get(name) or [""])[0] == "1"

        def _read_config(self) -> dict[str, object]:
            config = load_config()
            data = {key: config.get(key) for key in EDITABLE_FIELDS}
            data["allowed_models"] = list(ALLOWED_MODELS)
            data["platform"] = "macos" if is_macos() else "linux"
            data["capabilities"] = {"paste": not is_macos(), "system_clipboard": not is_macos()}
            return data

        def _handle_save_config(self) -> None:
            payload = self._read_json()
            updates: dict[str, object] = {}
            for key in EDITABLE_FIELDS:
                if key in payload:
                    value = payload[key]
                    if key in {"replacements", "snippets"}:
                        value = {str(k): str(v) for k, v in dict(value).items()} if value else {}
                    elif key == "hotwords":
                        value = [str(item).strip() for item in (value or []) if str(item).strip()]
                    elif key == "language":
                        value = (str(value).strip() or None) if value is not None else None
                    elif key in {"nonbreaking_spaces", "history_persist", "trailing_space", "beep", "live_preview"}:
                        value = bool(value)
                    elif key in {"short_text_words", "numbers_from"}:
                        value = positive_int(value)
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
            self.send_header("Cache-Control", "no-store")
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

    controller: RecordingController | None = None
    if is_macos():
        # macOS records in the resident server's memory (M4). The controller shares
        # the single inference_lock and the one cached Whisper model — never a
        # self-HTTP call — and is reached in-process by the M5 shortcut and the M6
        # tray. The shortcut wiring lands in M5b via run_desktop.
        def _transcribe_capture(wav: Path) -> str:
            with inference_lock:
                return get_transcriber(current_settings()).transcribe(wav).text

        controller = RecordingController(_transcribe_capture, current_settings,
                                         recording_allowed=model_download.ensure_ready)
        DesktopHandler._recording_controller = controller

    # run_desktop() owns the controller (it wires the shortcut and calls shutdown);
    # the handler keeps _recording_controller only to observe it (read-only route).
    # Off macOS the controller is None and no native piece is imported.
    if return_controller:
        return DesktopHandler, controller
    return DesktopHandler
