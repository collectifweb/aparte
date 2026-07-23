# Contributing to Aparté

Thanks for your interest in Aparté — a local-first dictation app for Linux.
Contributions of all kinds are welcome: bug reports, fixes, features, docs, and
testing on different desktop environments.

## Project goals

- **Local-first and private.** Audio and text never leave the machine. No
  account, no cloud.
- **Works out of the box, degrades gracefully.** Missing optional dependencies
  should never crash the app — the in-app diagnostics tell users what to install.
- **Linux-native.** First-class support for both X11 and Wayland, and for the
  common desktop environments (GNOME, KDE, Cinnamon, XFCE).

## Development setup

Requires Python 3.10+.

```bash
git clone git@github.com:collectifweb/aparte.git
cd aparte
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[whisper,recording,dev]"
```

If your Python was built without `ensurepip` (some minimal distros), create the
venv with `python3 -m venv --without-pip .venv` and bootstrap pip with
`python3 -m pip --python .venv/bin/python install --upgrade pip`.

Optional extras:

- `.[cuda]` — NVIDIA GPU acceleration (CUDA runtime wheels, no system toolkit).
- System tools for recording/insertion: `sudo apt install alsa-utils xclip xdotool`
  (X11) or `wl-clipboard wtype` (Wayland).

Run `aparte doctor` (or open the **Configuration** panel in `aparte desktop`) to
see what is set up.

## Running the tests

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -t tests
```

Both flags are required. `-t tests` sets the top-level directory: `tests/` has no
`__init__.py`, and without it discovery fails with *"Start directory is not
importable"*. `PYTHONPATH=src` is what lets the tests import `aparte` when you
have not installed the package in editable mode.

The suite is dependency-light and runs without a Whisper backend, a microphone,
or a display. Please keep it that way: mock external tools and never require a
real model download or audio device in a test.

A test that goes through `current_settings()` must point `APARTE_CONFIG` at a
temporary file, not just `APARTE_RUNTIME_DIR` — otherwise the server reads the
real user config, and if `history_persist` is on there, the test writes into
somebody's actual dictation history.

## Code layout

```
src/aparte/
  cli.py            argparse entry point and command handlers
  config.py         Settings, config file load/update
  transcription.py  Whisper backends + automatic CUDA→CPU fallback
  hallucinations.py strips the subtitle credits Whisper invents on silence
  audio.py          microphone recording (sounddevice / arecord) + start/stop beeps
  session.py        toggle-recording state for the global hotkey
  hotkey.py         register the global dictation shortcut (Cinnamon/GNOME gsettings)
  polish.py         heuristic + Ollama text cleanup
  numbers.py        French numbers dictated in words → digits
  history.py        the last five dictations, shared by every Aparté process
  clipboard.py      copy / paste (wl-clipboard, xclip, wtype, xdotool)
  notify.py         desktop notifications (notify-send)
  diagnostics.py    structured setup checks, shared by CLI + /api/doctor
  desktop.py        local HTTP server + JSON API
  tray.py           system tray icon (PyGObject + AppIndicator, optional)
  update.py         git pull + reinstall, driven from the Setup panel
  linux_desktop.py  .desktop launcher, autostart, and icon install
  assets/           frontend: index.html, app.css, app.js, i18n.js, SVG icons
```

`tray.py` and `update.py` are optional by construction: without PyGObject,
`build_tray()` returns `None` and the server starts exactly as before. New
integrations should follow that shape.

The desktop UI is plain HTML/CSS/JS served as static files from
`src/aparte/assets/` — no build step, no framework. Edit those files directly
and reload the page. UI strings are bilingual: add a key to both `fr` and `en`
in `assets/i18n.js` and reference it with `data-i18n="key"` in HTML or `t("key")`
in `app.js`. Diagnostic check labels are translated by their `key`, so adding a
new check in `diagnostics.py` means adding `check.<key>.label`/`.detail` to
`i18n.js`.

## Conventions

- Match the surrounding style; type-annotate new functions.
- New optional integrations must be **best-effort**: guard imports and external
  tools, and surface a fix through `diagnostics.py` rather than raising.
- Add or update tests for behaviour changes.
- Keep commits focused. Messages follow Conventional Commits, lower-case, with a
  scope when one is obvious: `feat(transcription): …`, `fix(ui): …`, `docs: …`.
  Say *why* in the body, not just what — the existing `git log` is the reference.

## Submitting changes

1. Fork and branch from `main`.
2. Make your change with tests and run the suite.
3. Open a pull request describing the motivation and any platform you tested on
   (desktop environment, X11/Wayland, GPU/CPU).

By contributing, you agree that your contributions are licensed under the
project's [MIT License](LICENSE).
