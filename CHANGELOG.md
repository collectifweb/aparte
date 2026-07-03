# Changelog

All notable changes to Murmur are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

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

- **One-command global hotkey setup**: `murmur install-hotkey` registers the
  dictation shortcut automatically through `gsettings` on Cinnamon and GNOME
  (default `Super+Space`, override with `--key`). It reuses the existing Murmur
  binding instead of creating duplicates, preserves an already-chosen accelerator
  unless `--key` is given, and supports `--print` and `--remove`. Other desktops
  get printable manual instructions.
- **In-app keyboard-shortcut guide**: the desktop **Setup & diagnostics** panel
  now shows the current shortcut status (bound key or "not set"), the exact
  command to bind, and the auto-bind command, each with a copy button. `murmur
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
- **Desktop app** (`murmur desktop`): a focused, single-screen interface with a
  large Talk button (browser WAV capture), a transcript editor, a small/base
  model toggle, a grouped Settings panel, and an in-app Setup & diagnostics panel
  that reports what is installed and the exact command to fix anything missing.
- **Bilingual UI** (English / French) with a language switch that defaults to the
  browser language.
- **Global-hotkey dictation**: `murmur toggle --target paste` records, then on the
  second press transcribes and inserts into the focused app (Slack, email, …),
  with native desktop notifications for start/stop.
- **CLI**: `polish`, `transcribe`, `record`, `dictate`, `toggle`, `desktop`,
  `doctor`, `config`, `install-desktop`, `install-autostart`.
- **Desktop integration**: `.desktop` launcher with an SVG app icon, and a
  login-autostart entry that runs the server in the background.
- **Configuration** via `~/.config/murmur/config.json` and `MURMUR_*` environment
  variables, editable live from the Settings panel.
- MIT license, contributing guide, and CI running the test suite on Python
  3.10–3.13.

[Unreleased]: https://github.com/collectifweb/murmur/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/collectifweb/murmur/releases/tag/v0.1.0
