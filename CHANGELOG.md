# Changelog

All notable changes to Aparté are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **French typography in the heuristic polisher**: a non-breaking space before
  `? ! ;` and `:` (skipping `https://` and `14:30`), `«  »` for paired straight
  quotes, and a typographic apostrophe. Standalone `i` is no longer upper-cased
  in French — that rule is the English pronoun. The rule set follows the
  dictation-language setting, and falls back to detecting the language from the
  text when the setting is `Auto`, so French formatting works out of the box.
  New `nonbreaking_spaces` config key (default `true`) swaps them for ordinary
  spaces, for apps that render them poorly.
- **French prompt for the Ollama polisher**, with the French typography rules
  spelled out, used when the dictation is in French.

### Changed

- **Renamed from Murmur to Aparté**, to avoid confusion with the unrelated
  [Murmure](https://github.com/Kieirra/murmure) project. The Python package,
  the CLI command, the config directory, the environment-variable prefix, and
  the desktop entry all follow. Existing installs are carried over on upgrade:
  `~/.config/murmur/config.json` is moved to `~/.config/aparte/config.json` on
  first run, `MURMUR_*` variables are still read as a fallback, the deprecated
  `murmur` command still works so an already-bound global shortcut keeps
  running, `install-hotkey` reuses and relabels that shortcut instead of adding
  a duplicate, and the old launcher, icon, and autostart entry are removed when
  the new ones are installed.
- **Dictation is now pasted, not typed out**: `--target paste` copies the text to
  the clipboard first (so it is never lost if the paste lands on a non-text area)
  and inserts it with a single Ctrl+V instead of simulating keystrokes one
  character at a time. A stray click or a key pressed mid-insertion can no longer
  interleave with the text or scatter it. In a terminal, paste with Ctrl+Shift+V.

### Fixed

- **Heuristic polisher no longer mangles words that contain a spoken-punctuation
  keyword**: "commande" stayed ", nde", "colonne" became ": ne", etc. Spoken
  marks (comma, colon, virgule, …) are now matched only as whole words.
- **Numbers dictated in a sentence are left inline** instead of being reformatted
  into a numbered list (e.g. "il y a 1 chien et 2 chats" no longer became a list).

### Added

- **One-command global hotkey setup**: `aparte install-hotkey` registers the
  dictation shortcut automatically through `gsettings` on Cinnamon and GNOME
  (default `Super+Space`, override with `--key`). It reuses the existing Aparté
  binding instead of creating duplicates, preserves an already-chosen accelerator
  unless `--key` is given, and supports `--print` and `--remove`. Other desktops
  get printable manual instructions.
- **In-app keyboard-shortcut guide**: the desktop **Setup & diagnostics** panel
  now shows the current shortcut status (bound key or "not set"), the exact
  command to bind, and the auto-bind command, each with a copy button. `aparte
  doctor` gained a matching `hotkey` line.

## [0.1.0] - 2026-06-01

First public release — a local-first dictation app for Linux.

### Added

- **Transcription** with local Whisper backends (`faster-whisper`,
  `openai-whisper`, or a `whisper.cpp` binary), fully offline.
- **NVIDIA GPU acceleration** via pip-provided CUDA wheels (`nvidia-cublas-cu12`,
  `nvidia-cudnn-cu12`), preloaded automatically so it works without
  `LD_LIBRARY_PATH`, with an automatic fall back to CPU when CUDA is unusable.
- **Text polishing**: a local heuristic cleaner (punctuation, capitalization,
  filler removal, spoken-punctuation, lists) and an optional Ollama LLM backend,
  plus per-user replacements and snippets.
- **Microphone recording** through `sounddevice`, `arecord`, `pw-record`, or
  `parec`.
- **Desktop app** (`aparte desktop`): a focused, single-screen interface with a
  large Talk button (browser WAV capture), a transcript editor, a small/base
  model toggle, a grouped Settings panel, and an in-app Setup & diagnostics panel
  that reports what is installed and the exact command to fix anything missing.
- **Bilingual UI** (English / French) with a language switch that defaults to the
  browser language.
- **Global-hotkey dictation**: `aparte toggle --target paste` records, then on the
  second press transcribes and inserts into the focused app (Slack, email, …),
  with native desktop notifications for start/stop.
- **CLI**: `polish`, `transcribe`, `record`, `dictate`, `toggle`, `desktop`,
  `doctor`, `config`, `install-desktop`, `install-autostart`.
- **Desktop integration**: `.desktop` launcher with an SVG app icon, and a
  login-autostart entry that runs the server in the background.
- **Configuration** via `~/.config/aparte/config.json` and `APARTE_*` environment
  variables, editable live from the Settings panel.
- MIT license, contributing guide, and CI running the test suite on Python
  3.10–3.13.

[Unreleased]: https://github.com/collectifweb/aparte/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/collectifweb/aparte/releases/tag/v0.1.0
