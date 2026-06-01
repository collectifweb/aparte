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
from .config import Settings
from .polish import PolishOptions, build_polisher
from .transcription import build_transcriber

# Models the desktop UI is allowed to switch to. Restricting this prevents the
# browser from triggering an arbitrary (possibly huge) model download.
ALLOWED_MODELS = ("small", "base", "tiny", "medium", "small.en", "base.en")


def run_desktop(host: str, port: int, settings: Settings) -> None:
    port = _available_port(host, port)
    server = ThreadingHTTPServer((host, port), handler_factory(settings))
    url = f"http://{host}:{server.server_port}"
    threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    print(f"Whispr Flow Linux desktop running at {url}")
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

    def get_transcriber(model: str | None = None):
        model = model or settings.model
        with transcriber_lock:
            transcriber = transcriber_cache.get(model)
            if transcriber is None:
                transcriber = build_transcriber(
                    backend=settings.transcriber,
                    model=model,
                    language=settings.language,
                    whisper_cpp=settings.whisper_cpp,
                    device=settings.device,
                    compute_type=settings.compute_type,
                )
                transcriber_cache[model] = transcriber
            return transcriber

    class DesktopHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path == "/" or self.path.startswith("/?"):
                self._send_html()
                return
            self.send_error(HTTPStatus.NOT_FOUND)

        def do_POST(self) -> None:
            try:
                if self.path == "/api/polish":
                    payload = self._read_json()
                    text = str(payload.get("text", ""))
                    style = str(payload.get("style", "neutral"))
                    cleanup_level = str(payload.get("cleanupLevel", "medium"))
                    polisher = build_polisher(settings.polish_backend, settings.ollama_url, settings.ollama_model)
                    output = polisher.polish(
                        text,
                        PolishOptions(
                            style=style or settings.default_style,
                            language=settings.language,
                            cleanup_level=cleanup_level or settings.cleanup_level,
                            replacements=settings.replacements or {},
                            snippets=settings.snippets or {},
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
            handle = tempfile.NamedTemporaryFile(prefix="whispr-flow-upload-", suffix=suffix, delete=False)
            path = Path(handle.name)
            handle.write(body)
            handle.close()
            try:
                transcript = get_transcriber(self._requested_model()).transcribe(path).text
                self._send_json({"text": transcript})
            finally:
                path.unlink(missing_ok=True)

        def _requested_model(self) -> str:
            query = parse_qs(urlsplit(self.path).query)
            requested = (query.get("model") or [""])[0]
            return requested if requested in ALLOWED_MODELS else settings.model

        def _send_json(self, payload: dict[str, object], status: HTTPStatus = HTTPStatus.OK) -> None:
            data = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _send_html(self) -> None:
            data = DESKTOP_HTML.encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    return DesktopHandler


DESKTOP_HTML = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Whispr Flow Linux</title>
  <style>
    :root {
      color-scheme: light dark;
      --bg: #f7f5f0;
      --panel: #fffefa;
      --text: #171717;
      --muted: #66645f;
      --border: #d9d4ca;
      --accent: #12664f;
      --accent-2: #1f7a8c;
      --danger: #9d2a2a;
    }
    @media (prefers-color-scheme: dark) {
      :root {
        --bg: #151614;
        --panel: #20221f;
        --text: #f1f0ea;
        --muted: #b6b2a8;
        --border: #383b35;
        --accent: #65c3a5;
        --accent-2: #75b8c8;
        --danger: #ff8f8f;
      }
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: var(--bg);
      color: var(--text);
    }
    main {
      width: min(1100px, calc(100vw - 32px));
      margin: 24px auto;
      display: grid;
      gap: 16px;
    }
    header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
    }
    h1 {
      margin: 0;
      font-size: 24px;
      letter-spacing: 0;
    }
    .status {
      color: var(--muted);
      min-height: 24px;
      font-size: 14px;
    }
    .toolbar, .options {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      align-items: center;
    }
    button, select, input[type="file"]::file-selector-button {
      border: 1px solid var(--border);
      background: var(--panel);
      color: var(--text);
      border-radius: 8px;
      min-height: 38px;
      padding: 0 12px;
      font: inherit;
    }
    button.primary {
      background: var(--accent);
      border-color: var(--accent);
      color: white;
    }
    button.secondary {
      border-color: var(--accent-2);
    }
    button.recording {
      border-color: var(--danger);
      color: var(--danger);
    }
    label {
      display: inline-flex;
      gap: 6px;
      align-items: center;
      color: var(--muted);
      font-size: 14px;
    }
    textarea {
      width: 100%;
      min-height: min(62vh, 620px);
      resize: vertical;
      border: 1px solid var(--border);
      background: var(--panel);
      color: var(--text);
      border-radius: 8px;
      padding: 16px;
      font: 17px/1.55 ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    input[type="file"] {
      max-width: 260px;
      color: var(--muted);
    }
    @media (max-width: 720px) {
      header { align-items: flex-start; flex-direction: column; }
      button, select { flex: 1 1 auto; }
      textarea { min-height: 56vh; }
    }
  </style>
</head>
<body>
  <main>
    <header>
      <h1>Whispr Flow Linux</h1>
      <div class="status" id="status"></div>
    </header>
    <div class="toolbar">
      <button class="primary" id="record">Record</button>
      <input id="file" type="file" accept="audio/*,.wav,.mp3,.m4a,.webm,.ogg">
      <button class="secondary" id="transcribe">Transcribe file</button>
      <button id="polish">Polish</button>
      <button id="copy">Copy</button>
      <button id="paste">Paste</button>
    </div>
    <div class="options">
      <label>Model
        <select id="model">
          <option value="small" selected>small (précis)</option>
          <option value="base">base (rapide)</option>
        </select>
      </label>
      <label>Style
        <select id="style">
          <option value="neutral">Neutral</option>
          <option value="formal">Formal</option>
          <option value="casual">Casual</option>
          <option value="very-casual">Very casual</option>
        </select>
      </label>
      <label>Cleanup
        <select id="cleanup">
          <option value="light">Light</option>
          <option value="medium" selected>Medium</option>
          <option value="high">High</option>
        </select>
      </label>
      <label><input id="autoPolish" type="checkbox" checked> Polish after transcription</label>
    </div>
    <textarea id="editor" spellcheck="true" autofocus placeholder="Dictate, upload audio, or paste raw transcript here."></textarea>
  </main>
  <script>
    const editor = document.querySelector("#editor");
    const statusEl = document.querySelector("#status");
    const fileInput = document.querySelector("#file");
    const recordButton = document.querySelector("#record");
    let recordingSession = null;

    function status(message) {
      statusEl.textContent = message;
    }

    async function postJson(path, payload) {
      const res = await fetch(path, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(payload)
      });
      if (!res.ok) throw new Error(await res.text());
      return res.json();
    }

    async function transcribeBlob(blob) {
      const model = document.querySelector("#model").value;
      status(`Transcribing (${model})...`);
      const res = await fetch("/api/transcribe?model=" + encodeURIComponent(model), {
        method: "POST",
        headers: {"Content-Type": blob.type || "application/octet-stream"},
        body: blob
      });
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      editor.value = data.text;
      if (document.querySelector("#autoPolish").checked) {
        await polishEditor();
      } else {
        status("Transcript ready.");
      }
    }

    async function polishEditor() {
      status("Polishing...");
      const data = await postJson("/api/polish", {
        text: editor.value,
        style: document.querySelector("#style").value,
        cleanupLevel: document.querySelector("#cleanup").value
      });
      editor.value = data.text;
      status("Polished.");
    }

    document.querySelector("#polish").addEventListener("click", async () => {
      try { await polishEditor(); } catch (err) { status(String(err)); }
    });

    document.querySelector("#transcribe").addEventListener("click", async () => {
      const file = fileInput.files[0];
      if (!file) {
        status("Choose an audio file first.");
        return;
      }
      try { await transcribeBlob(file); } catch (err) { status(String(err)); }
    });

    document.querySelector("#copy").addEventListener("click", async () => {
      status("Copying...");
      try {
        await postJson("/api/copy", {text: editor.value});
        status("Copied.");
      } catch (err) {
        try {
          await navigator.clipboard.writeText(editor.value);
          status("Copied in browser.");
        } catch (_) {
          status(String(err));
        }
      }
    });

    document.querySelector("#paste").addEventListener("click", async () => {
      status("Pasting...");
      try {
        await postJson("/api/paste", {text: editor.value});
        status("Pasted.");
      } catch (err) {
        status(String(err));
      }
    });

    recordButton.addEventListener("click", async () => {
      if (recordingSession) {
        const session = recordingSession;
        recordingSession = null;
        recordButton.classList.remove("recording");
        recordButton.textContent = "Record";
        const blob = await session.stop();
        try { await transcribeBlob(blob); } catch (err) { status(String(err)); }
        return;
      }
      try {
        recordingSession = await startWavRecording();
        recordButton.classList.add("recording");
        recordButton.textContent = "Stop";
        status("Recording...");
      } catch (err) {
        recordingSession = null;
        status(String(err));
      }
    });

    async function startWavRecording() {
      const stream = await navigator.mediaDevices.getUserMedia({audio: true});
      const audioContext = new AudioContext();
      const source = audioContext.createMediaStreamSource(stream);
      const processor = audioContext.createScriptProcessor(4096, 1, 1);
      const chunks = [];
      processor.onaudioprocess = event => {
        chunks.push(new Float32Array(event.inputBuffer.getChannelData(0)));
      };
      source.connect(processor);
      processor.connect(audioContext.destination);
      return {
        async stop() {
          processor.disconnect();
          source.disconnect();
          stream.getTracks().forEach(track => track.stop());
          await audioContext.close();
          return encodeWav(chunks, audioContext.sampleRate);
        }
      };
    }

    function encodeWav(chunks, sampleRate) {
      const totalLength = chunks.reduce((sum, chunk) => sum + chunk.length, 0);
      const pcm = new Int16Array(totalLength);
      let offset = 0;
      for (const chunk of chunks) {
        for (let i = 0; i < chunk.length; i++) {
          const sample = Math.max(-1, Math.min(1, chunk[i]));
          pcm[offset++] = sample < 0 ? sample * 0x8000 : sample * 0x7fff;
        }
      }
      const buffer = new ArrayBuffer(44 + pcm.length * 2);
      const view = new DataView(buffer);
      writeAscii(view, 0, "RIFF");
      view.setUint32(4, 36 + pcm.length * 2, true);
      writeAscii(view, 8, "WAVE");
      writeAscii(view, 12, "fmt ");
      view.setUint32(16, 16, true);
      view.setUint16(20, 1, true);
      view.setUint16(22, 1, true);
      view.setUint32(24, sampleRate, true);
      view.setUint32(28, sampleRate * 2, true);
      view.setUint16(32, 2, true);
      view.setUint16(34, 16, true);
      writeAscii(view, 36, "data");
      view.setUint32(40, pcm.length * 2, true);
      let byteOffset = 44;
      for (let i = 0; i < pcm.length; i++, byteOffset += 2) {
        view.setInt16(byteOffset, pcm[i], true);
      }
      return new Blob([view], {type: "audio/wav"});
    }

    function writeAscii(view, offset, text) {
      for (let i = 0; i < text.length; i++) {
        view.setUint8(offset + i, text.charCodeAt(i));
      }
    }
  </script>
</body>
</html>
"""
