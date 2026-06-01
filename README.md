# Whispr Flow Linux

Whispr Flow Linux is a local-first dictation app for Linux. It can run as a CLI, as a command bound to a global keyboard shortcut, or as a lightweight local desktop web app.

The first version focuses on the core Flow-like loop:

1. Capture speech or accept an audio file.
2. Transcribe with a local Whisper backend.
3. Polish the raw transcript with punctuation, capitalization, filler cleanup, lists, and optional local LLM formatting.
4. Copy or paste the result into the active Linux desktop session.

## Current status

This repo is a working MVP scaffold. It runs immediately for text polishing and desktop UI. Audio transcription activates when one of these local backends is available:

- `faster-whisper` Python package
- `openai-whisper` Python package
- `whisper.cpp` CLI via `WHISPR_WHISPER_CPP`

For best formatting quality, run Ollama locally and set `WHISPR_POLISH_BACKEND=ollama`.
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
echo "hey sarah thanks for sending this euh i will review it tomorrow" | whispr-flow polish
```

Transcribe an audio file and polish it:

```bash
whispr-flow transcribe meeting.wav --polish
```

Record from the microphone, transcribe, polish, and copy:

```bash
whispr-flow record --seconds 15 --polish --copy
```

Dictate directly into the active app:

```bash
whispr-flow dictate --seconds 8
```

Use fixed-duration dictation as a global keyboard shortcut command in GNOME/KDE/XFCE:

```bash
whispr-flow dictate --seconds 8 --target paste
```

For a more Flow-like shortcut, bind the same toggle command to one global hotkey. The first press starts recording; the second press stops, transcribes, polishes, and inserts:

```bash
whispr-flow toggle --target paste
```

Check whether a toggle recording is already active:

```bash
whispr-flow toggle --status
```

If direct paste is unavailable on your desktop, copy instead:

```bash
whispr-flow toggle --target copy
```

Launch the Linux desktop app:

```bash
whispr-flow desktop
```

Install a desktop launcher in `~/.local/share/applications`:

```bash
whispr-flow install-desktop
```

Create and edit your config:

```bash
whispr-flow config init
whispr-flow config path
whispr-flow config show
```

## Configuration

Environment variables:

```bash
WHISPR_TRANSCRIBER=auto
WHISPR_RECORDER=auto
WHISPR_MODEL=small
WHISPR_DEVICE=auto
WHISPR_COMPUTE_TYPE=auto
WHISPR_LANGUAGE=
WHISPR_POLISH_BACKEND=heuristic
WHISPR_OLLAMA_URL=http://127.0.0.1:11434
WHISPR_OLLAMA_MODEL=llama3.1:8b
WHISPR_WHISPER_CPP=
WHISPR_CONFIG=
```

`WHISPR_DEVICE` controls the `faster-whisper` compute device (`auto`, `cpu`, or `cuda`).
When a GPU is detected but its CUDA runtime is missing or unusable
(`libcublas`/`libcudnn` not found), transcription automatically falls back to CPU
with `int8`, so it works out of the box on machines without a CUDA install.
Force CPU with `WHISPR_DEVICE=cpu` to skip the GPU probe entirely.

Polish backends:

- `heuristic`: fully local, no model required, good enough for punctuation and capitalization cleanup.
- `ollama`: local LLM rewrite through Ollama, much better for fillers, backtracking, tone, and context.

Recorder backends:

- `auto`: try Python `sounddevice`, then `arecord`.
- `sounddevice`: Python recording backend.
- `arecord`: ALSA command-line recorder from `alsa-utils`.

Persistent config lives at `${XDG_CONFIG_HOME}/whispr-flow/config.json`, or `~/.config/whispr-flow/config.json` when `XDG_CONFIG_HOME` is not set. Override it with `WHISPR_CONFIG=/path/to/config.json`.

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

`whispr-flow desktop` starts a local server on `127.0.0.1` and opens the browser. It provides:

- a transcript editor
- a polish button
- audio upload transcription
- browser microphone recording as WAV PCM, avoiding a hard dependency on `ffmpeg` for desktop recording
- a model selector to toggle between `small` (more accurate) and `base` (faster)
- automatic polish after transcription
- copy and paste actions

Each model loads once and is cached, so toggling back and forth is instant after
the first use.

## Desktop notifications

The hotkey dictation flow (`toggle` and `dictate`) shows native Linux
notifications via `notify-send` so you can tell when recording starts, when
transcription is running, and when text was inserted or copied — useful when the
command is bound to a global shortcut and no terminal is visible. Install it with
`sudo apt install libnotify-bin` if `notify-send` is missing; it is optional and
dictation works without it.

This approach avoids GTK/Qt packaging friction while staying Linux-compatible.

`whispr-flow install-desktop` writes a user-level `.desktop` file so the app appears in Linux launchers. Use `whispr-flow install-desktop --print` to inspect the generated entry before installing it.
