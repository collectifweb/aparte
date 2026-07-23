# Changelog

All notable changes to Aparté are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Teach Whisper your own words, before it transcribes.** New **My words**
  setting (`hotwords`): one name per line — clients, tools, colleagues. Aparté
  hands the list to Whisper up front, so it leans toward those spellings when
  the audio is ambiguous. Unlike **Corrections**, you do not need to have seen
  the mistake first. Measured on real speech: without the list, `PipeWire` and
  `Mailpoet` came out as `pipe wire` and `mail poète`; with it, both were
  spelled correctly, casing included. Only `faster-whisper` supports it — with
  the other backends the setting is quietly ignored rather than promising what
  they cannot deliver.

- **The transcript appears while you speak.** Roughly once a second the
  recording so far is transcribed again from the start and shown in the editor,
  so a long dictation is no longer spoken into the void — and the text corrects
  itself as it goes, because Whisper revises its own guesses once it has heard
  the end of the sentence. Preview text sits in lighter ink and the action
  buttons stay off: it is not the final version yet. Auto-polish still runs only
  at the end. Never more than one pass in flight, and the next is scheduled only
  when the previous one returns, so a slow machine gets fewer previews rather
  than a growing queue. New **Preview while dictating** setting (`live_preview`,
  on by default) — without a GPU it keeps one core busy for as long as you
  speak. Side effect worth having: the first preview loads the Whisper model
  while you are still talking, which shortens the wait after you stop.

- **The action buttons explain themselves, and switch off when they have
  nothing to work on.** Polish, Copy and Insert are disabled while the editor
  is empty; each button, the model picker and Auto-polish carry a translated
  tooltip. When no microphone is detected, Settings says so instead of quietly
  falling back to "system default". A diagnostics panel that fails to load now
  says so in plain language rather than showing a raw JavaScript error.

- **Numbers dictated in words come out as digits, in French** (`numbers_from`,
  threshold 10 by default — the French rule keeps everything below ten in
  words). Whisper already writes digits about half the time; this makes the
  result the same twice in a row. "vingt-deux personnes" → "22 personnes",
  "quatre-vingt-dix-sept" → "97", "l'an deux mille vingt-six" → "l'an 2026" —
  a year keeps its four digits together, the thousands separator only starts at
  five. Times and percentages ignore the threshold and always become digits:
  "quatorze heures trente" → "14 h 30", "vingt pour cent" → "20 %". "deux
  millions" keeps its word rather than becoming "2000000", and septante,
  huitante, octante and nonante are understood. The rule throughout is that a
  doubtful case is left exactly as dictated: an article ("un chien"), an idiom
  ("des mille et des cents"), a hyphenated word that only looks like a number
  ("porte-parole"), or a sequence that isn't valid French ("vingt douze").

- **Pick which microphone to dictate into.** Settings lists the ALSA capture
  devices with their real names, and a **Refresh** button rebuilds the list
  without closing the panel. The choice reaches the global shortcut and the
  terminal commands; a device unplugged since then stays in the list, marked, so
  it is never silently swapped for another. The **Talk** button records through
  the browser and keeps following the browser's own microphone.
- **A beep when the microphone opens and closes** (`beep`, off by default): a
  high tone to start, a lower one to stop, generated locally — no sound file
  shipped, no library. The opening tone plays through before recording starts, so
  it does not end up in the dictation. For dictating with the global shortcut
  without watching the screen.
- **Two settings for how far the formatting goes.** **Short text**
  (`short_text_words`, off by default) leaves a dictation of fewer than N words
  exactly as spoken — no leading capital, no final period, because a search field
  is not a sentence. **Trailing space** (`trailing_space`, off by default) ends
  each dictation with a space, so a second one does not land glued to the first.

- **A system tray icon**, grafted onto the desktop server: two states that differ
  by shape rather than colour (three bars at rest, a filled disc while the
  microphone is open), and a menu — open Aparté, copy the last dictation, jump
  straight to Settings, quit. It follows the desktop's language, not the
  browser's. It needs PyGObject and the AppIndicator typelib, which are system
  packages: `install-linux.sh` now installs them with `--with-system-deps` and
  creates the virtualenv with `--system-site-packages`. An existing venv only
  needs `include-system-site-packages = true` in its `pyvenv.cfg` — no rebuild,
  so the Whisper and CUDA packages already installed stay put. Without them the server starts exactly as before
  and `aparte doctor` gained a line explaining how to get the icon.
- **The last five dictations, kept in memory.** They appear under the action bar
  in the desktop app; click one to copy it. `aparte last` recalls the most recent
  one from the terminal (`--target paste` re-inserts it). A dictation can carry a
  password or a private message, so the history lives in the runtime directory —
  tmpfs, wiped at logout — and only reaches the disk when the new **Keep history
  between sessions** setting says so, as a file only you can read. Every Aparté
  process shares the one store, so a dictation made through the global hotkey
  shows up in the app without either one having to be running for the other.
  When the list is empty, which is the normal state at the start of a session, it
  shows the global shortcut instead of announcing its own emptiness.
- **Three insertion modes, chosen in Settings** (`paste_mode`): `clipboard`, one
  atomic `Ctrl+V`, unchanged and still the default; `terminal`, which sends
  `Ctrl+Shift+V` because terminals ignore `Ctrl+V` outright; and `direct`, which
  types the text out for the applications that refuse a synthetic paste. Direct
  typing had been dropped when pasting moved to the clipboard; it is back as a
  deliberate choice rather than a fallback. All three copy to the clipboard
  first.
- **Update Aparté from the Setup panel.** An "Update" section shows the version
  installed, checks the remote when you ask it to, lists what is waiting, and
  runs `git pull` plus a reinstall with a live log. It restarts the app on its
  own afterwards, since the running server still holds the old code. It refuses
  and explains rather than trying, when the checkout has uncommitted changes,
  when the branch tracks no remote, or when Aparté was not installed from a
  clone. The remote is read from the branch's own upstream, never assumed to be
  `origin`, and the reinstall only passes the extras already installed. Nothing
  contacts the network until you press Check.
- **A documented design system.** [PRODUCT.md](PRODUCT.md) carries the product
  direction (users, promises, personality, anti-references, the accessibility
  commitment) and [DESIGN.md](DESIGN.md) the visual system (OKLCH tokens for both
  themes, scales, reference components, named rules). Read them before touching
  anything visible.
- **Keyboard and motion accessibility in the desktop UI**: a single visible focus
  ring on every control, `Esc` to close a panel, focus trapped inside an open
  panel and returned to the button that opened it, and a
  `prefers-reduced-motion` fallback for all four animations.
- **A disabled state on the action chips** while a transcription is being
  processed. The clicks were already ignored; now it shows.

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

- **The Settings panel is now ordered by how often you actually touch a
  setting.** Dictation, My dictionary and French typography are open on
  arrival; Hardware and Advanced are folded into native `<details>` — no
  JavaScript, so keyboard and screen readers work for free. Eleven controls to
  face on opening instead of eighteen. Six labels now name the intent rather
  than the mechanism: Cleanup → **Filler word removal** (with the help text it
  never had), Replacements → **Corrections**, Snippets → **Spoken shortcuts**
  (an English word in a French interface), Formatting → **French typography**,
  Polish engine → **Formatting engine**, Short text → **Very short dictations**.

- **A shortcut dictation reuses the running app's Whisper model instead of
  loading its own.** Pressing the global shortcut used to start a fresh process
  that read the model off disk every single time, while the desktop app sitting
  next to it already held that model in memory. It now hands the audio to the
  running app when one answers on the loopback address: **0.26 s instead of
  1.53 s** on the same ten seconds of audio, measured three times each. Nothing
  leaves the machine, and nothing changes when the app is not running — the
  shortcut loads its own model exactly as before, and that fallback is covered by
  tests precisely because it is the path nobody exercises by hand. Delegation is
  also skipped whenever an `APARTE_*` transcription override is set in the
  environment, since those exist only in the process that received them and the
  running app would silently ignore them.
- **"Paste" is now called "Insert".** The button never pasted into the editor —
  it types the text into whichever application was in front, which is what
  Settings already called "Insertion". Status messages follow.
- **A disabled control changes colour instead of fading.** `opacity` blended the
  label into the page background rather than the control's own: in the light
  theme a disabled label sat at **1.69:1**, and reaching 4.5:1 would have taken
  an opacity so high that nothing looked disabled any more. A new
  `ink-disabled` token holds 4.63:1 in light and 4.56:1 in dark. A disabled
  primary button also gives up its carmine fill.

- **The desktop UI was redesigned around one idea: the only saturated thing on
  screen means the microphone is open.** The teal-to-indigo gradient is gone
  everywhere, including the logo. At rest the Talk button is a solid ink disc; it
  floods carmine while recording. Every text/background pair now meets WCAG AA
  (4.5:1), computed rather than eyeballed — the old “Talk” label sat at 2.49:1 on
  the teal end of the gradient, and status messages at 4.17:1.
- **The transcript is now set in a serif face** (a system stack, no downloaded
  font), so the French typography Aparté produces — `« »`, curly apostrophes, the
  space before `;` and `?` — is actually visible. The UI chrome stays in the
  system sans-serif.
- **The interface has real scales** for spacing, radii, type sizes, z-index and
  motion, instead of one-off values.
- **`aria-label`s are translated.** They were hard-coded in English and ignored
  the language switch, so a French screen reader announced an English interface.
  The health dot in the top bar now carries a text equivalent instead of relying
  on colour alone.
- **The README leads with the former name**, so anyone who remembers Murmur lands
  on Aparté and recognises it. Screenshots are refreshed.

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

- **A vocabulary line without an `=` is no longer thrown away in silence.**
  Typing `cloud : Claude` used to save nothing, report nothing, and leave you to
  discover three dictations later that the entry was never there. Saving now
  stops and names the offending line. The same bug quietly broke multi-line
  spoken shortcuts: the signature offered as an example under the field lost
  every line after the first. Continuation lines are now kept.

- **A failed save is no longer displayed behind the drawer that failed.** The
  message went to the main page's status line — under the modal overlay, hidden
  at the exact moment it mattered. It now appears in the drawer footer, next to
  the button that failed.

- **Field help text no longer pollutes the field's accessible name.** Each help
  line sat *inside* its `<label>`, so a screen reader announced "Dictated
  numbers, «vingt-deux personnes» becomes «22 personnes», times and percentages
  always become digits…" as the name of the control. Help is now attached with
  `aria-describedby`, which is what it is for.

- **Dictations no longer end with "Sous-titres réalisés par la communauté
  d'Amara.org".** Whisper was trained on subtitled video, so on silence — the
  tail of a dictation, a pause, a microphone that picks up nothing — it fills the
  gap with a subtitling credit it saw thousands of times rather than returning
  nothing. Known credits are now stripped from every transcript, on every path
  (`--no-polish`, the global shortcut and the live preview included, since the
  filter sits in the transcriber rather than in the polisher). Two lists, because
  the risk differs: signed credits carrying a domain or a broadcaster name are
  removed wherever they appear, while generic video sign-offs — which someone
  writing a video script may genuinely dictate — are only removed when they are
  the entire transcript. A plain dictation comes back byte for byte, and
  "Amara.org" on its own is deliberately absent from the list.
- **The tray icon is now visible at rest, not only while recording.** Its SVG
  opened with a long comment above the root tag, which pushed `<svg` to byte 403
  — past the 256 bytes gdk-pixbuf reads to recognise a file format. The loader
  rejected it, so the panel drew an empty one-millimetre gap; the recording icon,
  whose comment is shorter, loaded fine and appeared. Both files now carry their
  comment inside the root element, and a test guards the rule.

- **Copy on an empty editor no longer wipes the clipboard.** It sent the empty
  string to the system clipboard and reported "Copied." — as did Insert and
  Polish, each announcing a success it had not performed. The three buttons are
  now disabled until there is text.

- **Heuristic polisher no longer mangles words that contain a spoken-punctuation
  keyword**: "commande" stayed ", nde", "colonne" became ": ne", etc. Spoken
  marks (comma, colon, virgule, …) are now matched only as whole words.
- **Numbers dictated in a sentence are left inline** instead of being reformatted
  into a numbered list (e.g. "il y a 1 chien et 2 chats" no longer became a list).

### Fixed

- **The recent-dictations panel lines up with the editor again.** The work area
  is centred, and the panel had no width of its own, so it shrank to fit its
  content: after two short dictations it sat as a narrow strip floating under the
  action bar, its rule a stub instead of spanning the column.
- **No more sideways scrolling in a narrow window.** Below 560 px the top bar's
  two buttons pushed past the viewport; it now wraps onto a second row.
- **The whole app fits on one screen again.** It needed a 984 px viewport — right
  at the edge of what a 1080p screen leaves once the browser's own bars are
  counted, so the recent-dictations panel was usually cut off. Two levers, no
  restructuring: the bottom margin drops from 48 px to 24, and the editor's
  height ceiling from 360 px to 300. It now fits from 900 px, and the editor is
  still resizable by hand for a long text.
- **Launching Aparté while it is already running now opens the running one**
  instead of starting a second server. The menu entry and the autostart entry
  run the same command, so clicking the launcher after login used to start a
  rival server on a random port, with its own tray icon. Anything else holding
  the port is left alone and the usual free-port search still applies.
- **The desktop entry passes `desktop-file-validate`.** `Audio` without
  `AudioVideo` is an error the validator warns will become fatal, and three main
  categories made the app appear three times in the application menu.

### Security

- **The desktop server now refuses POSTs from pages it did not serve.** It only
  listens on 127.0.0.1, so nothing on the network could reach it, but any page
  open in the browser could post to it blindly — and `/api/paste` types text
  into whatever window has focus. The address the request arrived under has to
  be one of ours as well, so a domain rebound to 127.0.0.1 is turned away even
  though its Origin and Host agree with each other. Requests carrying no
  `Origin` header, which is every command-line client, are unaffected.

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
