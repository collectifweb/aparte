# Contributing to Aparté

Thanks for your interest in Aparté — a local-first dictation app for Linux,
with an experimental native macOS port.
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
- `.[whisper,recording,macos,dev]` — the macOS development environment; install
  PortAudio first with `brew install portaudio`. See the [prototype setup](README.md#running-on-macos-development-prototype).
- System tools for recording/insertion: `sudo apt install alsa-utils xclip xdotool`
  (X11) or `wl-clipboard wtype` (Wayland).

Run `aparte doctor` (or open the **Configuration** panel in `aparte desktop`) to
see what is set up.

## Running the tests

Use the isolated runner from the repository root:

```bash
python3 scripts/run-tests.py                      # complete suite; required on Linux
python3 scripts/run-tests.py --suite macos        # macOS-compatible selection
python3 scripts/run-tests.py test_config_persistence test_recovery
```

The runner creates private temporary configuration, data, state, runtime,
temporary-file and model-cache directories before importing the application. It
removes inherited `APARTE_*` and `MURMUR_*` overrides, sets `APARTE_CONFIG`, and
puts Hugging Face in offline mode. It deliberately does **not** set
`APARTE_RUNTIME_DIR`: some tests exercise the `XDG_RUNTIME_DIR` fallback. All
paths are removed after the test subprocess exits.

The underlying Linux command is `PYTHONPATH=src python3 -m unittest discover -s
tests -t tests`. Run it directly only with equivalent isolation. Both discovery
flags are required because `tests/` has no `__init__.py`.

Tests must not use personal dictation history, a real clipboard, a microphone,
login entries or a model download. A test that calls `current_settings()` must
set `APARTE_CONFIG` to a temporary file: a runtime override alone still reads
the user's persistence setting. Tests that install desktop entries must isolate
both `XDG_DATA_HOME` and `XDG_CONFIG_HOME`, since legacy cleanup reaches
autostart configuration. Keep tests safe when run individually as well as through
the runner. Synthetic files, fake audio devices and controlled concurrent
processes cover storage failures and lifecycle races without personal data.

The Linux suite remains dependency-light. Node is needed for the browser
controller tests; they exercise JavaScript with synthetic DOM/audio objects,
without opening a browser or microphone. A C compiler runs the launcher
compilation tests. Native macOS signing checks skip on other platforms.

### macOS validation

The [CI workflow](.github/workflows/ci.yml) defines a separate `macos-15` job with
Python 3.11, PortAudio and the real `whisper,recording,macos,dev` dependencies. It
checks the installed package and native imports, then runs the isolated macOS
selection. That includes actual `clang` compilation and `codesign` verification,
bundle stability across French/English locales, and signature rejection after a
synthetic resource modification. Linux continues to run the complete suite.

A workflow definition is not a successful CI run. Record the run URL and result
when GitHub executes it; local Linux tests and simulated Darwin branches do not
establish native success. CI also cannot prove microphone/Accessibility prompts,
Finder launch attribution, shortcut delivery, insertion into target apps or
permission continuity after upgrades. Those require the interactive
[M7-0 protocol](.claude/mac-validation/m7/README.md) and the matrix in the
[macOS reliability plan](tasks/fiabilisation-macos.md).

Do not change the installed app or switch branches in a Syncthing-shared working
tree to run these checks. Use an isolated checkout, preserve pre-existing work,
and distinguish executed checks from simulations and code inspection in reports.

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
  recovery.py       private, expiring audio/raw-text recovery and retry claims
  clipboard.py      copy / paste (wl-clipboard, xclip, wtype, xdotool)
  notify.py         desktop notifications (notify-send)
  diagnostics.py    structured setup checks, shared by CLI + /api/doctor
  desktop.py        local HTTP server + JSON API
  tray.py           system tray icon (PyGObject + AppIndicator, optional)
  update.py         git pull + reinstall, driven from the Setup panel
  linux_desktop.py  .desktop launcher, autostart, and icon install
  macos_recording.py native capture lifecycle and recovery before processing
  macos_runloop.py   AppKit loop, global shortcut and ordered shutdown
  macos_tray.py      native menu actions and status
  macos_install.py   signed bundle publication and rollback
  model_download.py shared model-cache checks and preparation state
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
