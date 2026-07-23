# Round 1 — Plan : compatibilité macOS pour Aparté

## 1. Contexte

Aparté est une application de dictée vocale **Linux uniquement**, Python 3.10+,
sans framework, paquet dans `src/aparte/`. Chemin principal du produit : un
raccourci clavier global lance l'enregistrement, un second appui transcrit
(Whisper local) et **insère le texte dans l'application active**. Une interface
web locale (`desktop.py`, 127.0.0.1:8765) sert d'alternative et d'écran de
réglages.

On veut le rendre **compatible macOS** (cible prioritaire ; Windows étudié à part,
non planifié). Deux sous-agents ont audité le code le 23/07 ; ce plan en est la
synthèse, à challenger.

### Contraintes produit non négociables

- **« Linux d'abord, français d'abord »** est le positionnement identitaire
  (PRODUCT.md). macOS doit rester un **compagnon** — « Aparté tourne aussi sur
  Mac » — jamais un pivot. Le code Linux existant, testé, ne doit pas être
  déstabilisé.
- **Interface web sans étape de compilation ni bibliothèque** (HTML/CSS/JS à la
  main). Le portage ne doit pas y toucher.
- **Tout local** : rien ne sort de la machine.

### Le constat qui change le calcul

Le cœur est **déjà portable** : `polish.py`, `numbers.py`, la typographie, l'UI
web, `desktop.py`, faster-whisper — zéro appel système. L'UI web enregistre
**dans le navigateur** (`getUserMedia`). Donc sur Mac aujourd'hui, `pip install`
+ `aparte desktop` sert la page, transcrit, polit et copie. Ce qui manque :
insertion dans l'app active, raccourci global, notifications, tray, toggle CLI.
**Un premier pas quasi gratuit existe : documenter que la dictée navigateur
marche déjà**, avant tout engagement lourd.

### Ce qui survit tel quel (macOS est de l'Unix)

`os.killpg`, `os.link`, `start_new_session`, signaux, `os.getuid()`, chemins
`~/.config`, repli `$TMPDIR` de `get_runtime_dir()`. Le préchargement CUDA de
`transcription.py:23-51` est inoffensif (retour immédiat, aucun `.so` à charger).
**whisper.cpp est déjà codé** (`WhisperCppTranscriber`, `transcription.py:160`) :
c'est le moteur rapide sur Mac via Metal.

### Ce qui casse ou manque

`_recorder_alive()` lit `/proc/<pid>/cmdline` (`session.py:89`) — pas de `/proc`
sur Mac. `arecord` (ALSA), `xclip`/`wtype`, `notify-send`, `gsettings`,
PyGObject/GTK, fichiers `.desktop` : aucun sur Mac.

## 2. Approche proposée

### Architecture : pas de grande couche d'abstraction

Les modules concernés font 44 à 317 lignes, API stables, déjà simulées par les
tests. Deux mécanismes, en réutilisant le patron `linux_desktop.py` (le nom porte
l'OS) :

1. **Modules OS-spécifiques neufs** : `macos_desktop.py` (LaunchAgent + bundle
   `.app`), `macos_hotkey.py` (RegisterEventHotKey), `macos_tray.py` (rumps).
   Sélection par `sys.platform == "darwin"` au point d'appel. **Le code Linux
   n'est pas touché.**
2. **Modules mixtes** (`clipboard.py`, `notify.py`, `audio.py`) : branche
   `sys.platform` en tête des fonctions publiques. API inchangée.
3. **`session.py` reste Linux** ; sur Mac, l'état d'enregistrement vit dans le
   serveur résident (voir plus bas).

### Le pivot architectural : enregistrement in-process sur Mac

Sur Linux, le raccourci lance des **processus CLI éphémères** qui se coordonnent
via fichier de session + lien physique + `/proc`. Ça n'a de sens que parce que le
raccourci gsettings n'a pas de processus à lui.

Sur Mac, le raccourci global **exige** un processus résident (RegisterEventHotKey
a besoin d'une run loop), et ce processus existe déjà : le serveur de bureau, en
autostart. Donc sur Mac :

- une route `/api/toggle` démarre/arrête un `sounddevice.InputStream` **en
  mémoire du serveur** — zéro sous-processus, zéro PID, zéro fichier de session,
  zéro `/proc` ;
- `aparte toggle` en CLI **délègue au serveur par HTTP**, exactement le patron
  déjà éprouvé de `transcribe_via_running_app()` ;
- le plafond `max_recording_seconds` devient un compteur d'échantillons.

C'est **moins de code que de transposer `session.py`**, pas plus.

### Correspondances par surface

| Surface | macOS | Difficulté |
|---|---|---|
| Copie | `pbcopy` (préinstallé) | triviale |
| Collage / frappe | `CGEventPost` + `CGEventKeyboardSetUnicodeString` (PyObjC/Quartz) — seule route sûre pour ’ « » U+00A0 | modérée + **permission Accessibilité** |
| Mode `terminal` | disparaît (Cmd+V partout) | simplification |
| Notifications | `osascript display notification` (attribué à « Éditeur de script ») | triviale |
| Bips | `afplay` | triviale |
| Micros | `sounddevice.query_devices()` | triviale |
| Raccourci global | `RegisterEventHotKey` (Carbon) via `quickmachotkey`/PyObjC, **0 permission** | dure (run loop) |
| Tray | `rumps` (NSStatusBar) + 2 PNG « template » | modérée |
| Autostart | LaunchAgent `.plist` + `launchctl bootstrap` | triviale |
| Identité / lanceur | bundle `.app` minuscule (identité TCC stable + `NSMicrophoneUsageDescription`) | modérée |
| Vie des processus | in-process dans le serveur ; `_recorder_alive` → `ps -p` (chemin Linux) | modérée |
| Chemins | inchangés (`~/.config` marche) | nulle |
| Moteur rapide | whisper.cpp/Metal (déjà codé) | nulle en code |

### Le raccourci global : RegisterEventHotKey, et pourquoi

C'est le choix structurant. `RegisterEventHotKey` (API Carbon, toujours
fonctionnelle) **ne demande aucune permission TCC**, contrairement à un event tap
(`CGEventTap`/`pynput` → permission Surveillance de l'entrée). Le serveur est déjà
résident au login, donc la contrainte « il faut une run loop vivante » est déjà
satisfaite. Le gestionnaire appelle directement la logique de toggle dans le
processus qui tient Whisper en mémoire. Plan B documenté, non intégré : `skhd`
(une ligne dans `~/.config/skhd/skhdrc`), l'équivalent moral des instructions
manuelles que `hotkey.py` imprime déjà pour les bureaux non gérés.

### Empaquetage

`install-macos.sh` symétrique du `.sh` Linux : venv, `pip install -e
".[whisper,recording,macos]"` (extra `macos = ["pyobjc-framework-Quartz",
"rumps", "quickmachotkey"]`), écriture du LaunchAgent, création du bundle `.app`,
`brew install whisper-cpp` optionnel. Prérequis : Command Line Tools (git).
**`update.py` fonctionne tel quel** (git + `pip install -e` + `os.execv`, tout
POSIX) — aucun travail. Pas de py2app/briefcase (gigaoctets, signature/notarisation
99 $/an) ; pas de tap Homebrew en v1 (casserait `update.py` en état `manual`).

## 3. Étapes d'implémentation

| Lot | Contenu | Effort |
|---|---|---|
| M0 | Dispatch `sys.platform`, extra `[macos]`, classifieurs | 0,5 j |
| M1 | Socle trivial : `pbcopy`, notifs osascript, `afplay`, micros sounddevice, `record_wav` mac | 1,5–2 j |
| M2 | Diagnostics macOS (`doctor` + panneau) : vérifs, `fix` brew, `AXIsProcessTrusted`, textes fr/en | 1–1,5 j |
| M3 | Insertion : Cmd+V + frappe Unicode via CGEvent, fusion clipboard/terminal, parcours Accessibilité guidé | 1,5–2 j |
| M4 | Toggle résident : enregistrement in-process, route `/api/toggle`, CLI déléguée | 2–3 j |
| M5 | Raccourci global RegisterEventHotKey + run loop AppKit partagée avec le tray, `install-hotkey` mac | 2–3 j |
| M6 | Tray rumps (menu + sondage d'état + icônes PNG template) | 1–1,5 j |
| M7 | Empaquetage : LaunchAgent, bundle `.app`, `install-macos.sh`, doc | 2–3 j |
| M8 | CI macOS (runner gratuit, dépôt public) + étiquetage tests Linux-only + tests modules mac | 1–2 j |

**Total : 13 à 18 jours de travail réel.** M3–M5 se déboguent sur un vrai Mac.

## 4. Points sensibles

1. **Les permissions TCC dégradent le « ça marche tout de suite ».** Deux
   bloquantes : **Microphone** (attribution fragile sans bundle `.app` — chaque
   recréation de venv peut l'invalider) et **Accessibilité** pour le collage
   (pas d'invite « Autoriser », détour Réglages + relance). Incompressible :
   aucune appli de dictée Mac n'y échappe. Est-ce que le bundle `.app` suffit à
   rendre l'attribution micro stable, ou faut-il aller jusqu'à une identité
   signée ?
2. **La run loop partagée hotkey + tray sur le fil principal.** GTK impose déjà
   cette structure aujourd'hui (`desktop.py:81-88`, serveur sur fil secondaire).
   Sur Mac, RegisterEventHotKey ET rumps veulent tous deux la run loop AppKit du
   fil principal. Cohabitation à valider — c'est le point technique le plus
   incertain.
3. **`_captured_seconds()` ne se transpose pas.** Il suppose l'en-tête exact
   d'arecord (44 o, bouche-trou 2 Gio). Avec l'enregistrement in-process
   sounddevice, cette logique disparaît plutôt qu'elle ne se réécrit — mais il
   faut le vérifier : sounddevice écrit-il un WAV bien formé, ou faut-il gérer la
   finalisation d'en-tête nous-mêmes ?
4. **« Mes mots » (`hotwords`) indisponible avec whisper.cpp/Metal.** L'utilisateur
   Mac choisit entre moteur rapide (Metal, sans Mes mots) et faster-whisper (avec
   Mes mots, CPU). Arbitrage produit à écrire dans l'interface — pas un bug.
5. **L'historique non persistant vit sur disque** (`$TMPDIR`) au lieu d'un tmpfs
   effacé à la déconnexion. Affaiblit la promesse de confidentialité. Mitiger en
   le gardant en mémoire du serveur ?
6. **Le raccourci exige un serveur lancé** (sur Linux il marche sans démon).
   Recul réel de la promesse, imposé par l'OS. À assumer et documenter.
7. **La dette ×2 permanente.** Exemple concret : le Lot 5B (fenêtre flottante au
   raccourci, planifié) devrait exister en GTK **et** en NSPanel/PyObjC. Chaque
   fonctionnalité système future coûte double.

## 5. Alternatives écartées

- **Une grande couche `platform/base.py` + implémentations.** Écartée :
  sur-ingénierie pour 6 modules de 44–317 lignes aux API déjà stables. Le patron
  `*_desktop.py` + branche `sys.platform` suffit et garde le code Linux intact.
- **Transposer `session.py` littéralement sur Mac** (sox/ffmpeg détaché, `ps`
  pour la vivacité, réécriture de `_captured_seconds`). Écartée : plus de code,
  plus de surface de bogue, pour reproduire une architecture dont la raison
  d'être (raccourci sans processus) disparaît sur Mac.
- **Event tap `CGEventTap`/`pynput` pour le raccourci.** Écartée : demande la
  permission Surveillance de l'entrée, la pire, alors que RegisterEventHotKey n'en
  demande aucune.
- **osascript/System Events pour le collage.** Écartée : déclenche une invite
  Automatisation en plus d'Accessibilité, et `keystroke "texte"` massacre les
  caractères hors disposition clavier (’ « » U+00A0) — rédhibitoire pour le
  français. CGEvent Unicode est la seule route sûre.
- **Bundle autonome py2app/briefcase.** Écartée : gigaoctets (PyTorch/CTranslate2
  embarqués), signature/notarisation Apple payante, et casse `update.py` (plus de
  checkout git). Contraire à l'esprit du projet.
- **Tap Homebrew en v1.** Écartée : une install brew n'est pas un checkout git,
  donc `update.py` tomberait en état `manual`. Envisageable plus tard.
- **Ne rien faire côté natif, tout miser sur la page web.** C'est le « pas
  gratuit » qu'on garde comme préalable — mais il n'offre pas l'insertion dans
  l'app active, qui EST le produit. Insuffisant seul.

## 6. Zones d'incertitude que j'assume

- Je n'ai **pas de Mac pour vérifier** la cohabitation run loop hotkey+tray ni le
  comportement réel des permissions. Les estimations M3–M5 sont les plus fragiles.
- Le comportement WAV de `sounddevice` en écriture (point sensible 3) n'est pas
  vérifié dans le code — c'est une hypothèse.
- `quickmachotkey` : dépendance tierce peu connue ; à valider (maintenue ? ou
  écrire les ~20 lignes ctypes sur Carbon directement ?).
