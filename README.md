# Murmur

[![CI](https://github.com/collectifweb/murmur/actions/workflows/ci.yml/badge.svg)](https://github.com/collectifweb/murmur/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

Murmur is a local-first dictation app for Linux. It can run as a CLI, as a command bound to a global keyboard shortcut, or as a lightweight local desktop web app.

The first version focuses on the core Flow-like loop:

1. Capture speech or accept an audio file.
2. Transcribe with a local Whisper backend.
3. Polish the raw transcript with punctuation, capitalization, filler cleanup, lists, and optional local LLM formatting.
4. Copy or paste the result into the active Linux desktop session.

## Screenshots

![Murmur dictation screen](docs/screenshots/main.png)

The built-in setup diagnostics show, in the app, what is installed and the exact
command to fix anything that is missing — so any Linux user can get set up
without the terminal. The interface is available in English and French.

<img src="docs/screenshots/diagnostics.png" alt="Setup and diagnostics panel" width="360">

## Current status

This repo is a working MVP scaffold. It runs immediately for text polishing and desktop UI. Audio transcription activates when one of these local backends is available:

- `faster-whisper` Python package
- `openai-whisper` Python package
- `whisper.cpp` CLI via `MURMUR_WHISPER_CPP`

For best formatting quality, run Ollama locally and set `MURMUR_POLISH_BACKEND=ollama`.
For consistent spelling of names, products, acronyms, and repeated phrases, use the built-in config file.

## Install

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

Full local install with Whisper, recording extras, default config, and desktop launcher:

```bash
./scripts/install-linux.sh
```

To also install the system packages (recording, clipboard, paste) via apt:

```bash
./scripts/install-linux.sh --with-system-deps
```

Optional local Whisper backend:

```bash
python -m pip install -e ".[whisper]"
```

GPU acceleration (NVIDIA, optional). Installs the CUDA runtime libraries as pip
wheels — no system CUDA toolkit required. The app preloads them automatically,
so GPU transcription works without setting `LD_LIBRARY_PATH`, and falls back to
CPU when CUDA is unusable:

```bash
python -m pip install -e ".[whisper,cuda]"
```

Optional microphone recording:

```bash
python -m pip install -e ".[recording]"
```

System packages commonly needed on Linux:

```bash
sudo apt install alsa-utils ffmpeg wl-clipboard wtype xclip xdotool
```

Use Wayland tools (`wl-copy`, `wtype`) on Wayland, or X11 tools (`xclip`, `xdotool`) on X11.

## CLI examples

Polish raw text:

```bash
echo "hey sarah thanks for sending this euh i will review it tomorrow" | murmur polish
```

Transcribe an audio file and polish it:

```bash
murmur transcribe meeting.wav --polish
```

Record from the microphone, transcribe, polish, and copy:

```bash
murmur record --seconds 15 --polish --copy
```

Dictate directly into the active app:

```bash
murmur dictate --seconds 8
```

Use fixed-duration dictation as a global keyboard shortcut command in GNOME/KDE/XFCE:

```bash
murmur dictate --seconds 8 --target paste
```

For a more Flow-like shortcut, bind the same toggle command to one global hotkey. The first press starts recording; the second press stops, transcribes, polishes, and inserts:

```bash
murmur toggle --target paste
```

Check whether a toggle recording is already active:

```bash
murmur toggle --status
```

If direct paste is unavailable on your desktop, copy instead:

```bash
murmur toggle --target copy
```

Launch the Linux desktop app:

```bash
murmur desktop
```

Install a desktop launcher in `~/.local/share/applications`:

```bash
murmur install-desktop
```

Run the desktop server automatically at login (writes `~/.config/autostart`).
It starts in the background without opening a browser, so the editor and the
Settings tab are always available at `http://127.0.0.1:8765`:

```bash
murmur install-autostart
murmur install-autostart --remove   # undo
```

## Global hotkey (recommended for dictating into other apps)

The Flow-like flow is one global shortcut bound to `toggle`: press once to start,
press again to transcribe and insert into whatever app is focused (Slack, email,
…). The binding is stored by your desktop and survives reboots, so no background
process is required for it.

On Cinnamon: System Settings → Keyboard → Shortcuts → Custom Shortcuts → Add,
with this command (use the full path to the binary inside your venv):

```bash
/path/to/murmur/.venv/bin/murmur toggle --target paste
```

Then assign a key (e.g. a spare key or `Super+Space`). Direct paste needs
`xdotool` on X11 or `wtype` on Wayland; otherwise use `--target copy` and paste
with `Ctrl+V`. Desktop notifications show when recording starts and stops.

Create and edit your config:

```bash
murmur config init
murmur config path
murmur config show
```

## Configuration

Environment variables:

```bash
MURMUR_TRANSCRIBER=auto
MURMUR_RECORDER=auto
MURMUR_MODEL=small
MURMUR_DEVICE=auto
MURMUR_COMPUTE_TYPE=auto
MURMUR_LANGUAGE=
MURMUR_POLISH_BACKEND=heuristic
MURMUR_OLLAMA_URL=http://127.0.0.1:11434
MURMUR_OLLAMA_MODEL=llama3.1:8b
MURMUR_WHISPER_CPP=
MURMUR_CONFIG=
```

`MURMUR_DEVICE` controls the `faster-whisper` compute device (`auto`, `cpu`, or `cuda`).
When a GPU is detected but its CUDA runtime is missing or unusable
(`libcublas`/`libcudnn` not found), transcription automatically falls back to CPU
with `int8`, so it works out of the box on machines without a CUDA install.
Force CPU with `MURMUR_DEVICE=cpu` to skip the GPU probe entirely.

Polish backends:

- `heuristic`: fully local, no model required, good enough for punctuation and capitalization cleanup.
- `ollama`: local LLM rewrite through Ollama, much better for fillers, backtracking, tone, and context.

Recorder backends:

- `auto`: try Python `sounddevice`, then `arecord`.
- `sounddevice`: Python recording backend.
- `arecord`: ALSA command-line recorder from `alsa-utils`.

Persistent config lives at `${XDG_CONFIG_HOME}/murmur/config.json`, or `~/.config/murmur/config.json` when `XDG_CONFIG_HOME` is not set. Override it with `MURMUR_CONFIG=/path/to/config.json`.

Example:

```json
{
  "default_style": "neutral",
  "cleanup_level": "medium",
  "language": "en",
  "replacements": {
    "whisper flow": "Wispr Flow",
    "pipe wire": "PipeWire",
    "my project": "MyProject"
  },
  "snippets": {
    "signature": "Best,\nAlexandre"
  }
}
```

With that config, dictating `slash signature` expands the snippet, and dictated terms such as `pipe wire` are rewritten with the preferred spelling.

## Desktop app

`murmur desktop` starts a local server on `127.0.0.1` and opens the browser. The
interface is a focused, single-screen app:

- a large **Talk** button (browser microphone recording as WAV PCM, so no hard
  dependency on `ffmpeg`) that records, transcribes, and auto-polishes
- a transcript editor with **Polish**, **Copy**, **Paste**, and audio import
- a model toggle (`small` = accurate, `base` = fast); each model loads once and
  is cached, so switching is instant after first use
- a **Settings** panel (gear icon) grouped into Transcription (model, language,
  compute device), Formatting (style, cleanup, polish backend), and Vocabulary
  (replacements, snippets) — saved to the config file and applied immediately,
  including to the global-hotkey dictation flow
- a **Configuration & diagnostics** panel that shows, with green/red status, what
  is installed vs missing (Whisper backend, GPU, microphone, paste/clipboard,
  notifications) and the exact command to fix each gap — copy-paste onboarding
  for any Linux user

The interface is bilingual (English / French) with a language switch in the top
bar; it defaults to the browser language. The frontend lives in
`src/murmur/assets/` (`index.html`, `app.css`, `app.js`, `i18n.js`, `logo.svg`)
and is served as static files, so it is easy to contribute to.

## Desktop notifications

The hotkey dictation flow (`toggle` and `dictate`) shows native Linux
notifications via `notify-send` so you can tell when recording starts, when
transcription is running, and when text was inserted or copied — useful when the
command is bound to a global shortcut and no terminal is visible. Install it with
`sudo apt install libnotify-bin` if `notify-send` is missing; it is optional and
dictation works without it.

This approach avoids GTK/Qt packaging friction while staying Linux-compatible.

`murmur install-desktop` writes a user-level `.desktop` file so the app appears in Linux launchers. Use `murmur install-desktop --print` to inspect the generated entry before installing it.

## Contributing

Contributions are welcome — see [CONTRIBUTING.md](CONTRIBUTING.md) for the
development setup, how to run the tests, and the code layout. The desktop UI is
plain HTML/CSS/JS in `src/murmur/assets/` with no build step.

## License

Murmur is released under the [MIT License](LICENSE). It is an independent,
open-source project and is not affiliated with the commercial Wispr Flow product.
