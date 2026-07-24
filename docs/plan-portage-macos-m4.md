# Plan : Lot M4 — Enregistrement in-process macOS (Aparté)

Tranche M4 du portage macOS. Le plan global `docs/plan-portage-macos.md` fait
autorité ; ce document consolide le découpage exécuté pour M4. Livré, prouvé sous
Linux par tests mockés, à valider sur un vrai Mac en M8.

## Contexte

Sur Linux, la bascule dictée (`aparte toggle`) lance des processus CLI éphémères
coordonnés par un fichier de session, `os.link` et `/proc` (`session.py`). Ça n'a
de sens que parce que le raccourci gsettings n'a pas de processus à lui.

Sur macOS, le raccourci global (M5) exige un processus résident — et il existe
déjà : le serveur de bureau, en autostart. L'enregistrement se fait donc **en
mémoire du serveur**, via un objet `RecordingController` : zéro sous-processus,
zéro PID, zéro fichier de session, zéro `/proc`. C'est moins de code que de
transposer `session.py`, pas plus.

M4 construit et prouve ce contrôleur (machine d'état + capture PortAudio bornée +
worker + provider d'état), isolément, par tests mockés. Ce qui le *déclenche* (le
raccourci natif + la run loop AppKit) est M5. En fin de M4, le contrôleur est une
infrastructure dormante, observable, câblée à un déclencheur en M5.

### Contraintes non négociables

- **Linux d'abord** : comportement Linux byte-identique, toute la suite verte.
- **Le plus simple d'abord**, modifications chirurgicales.
- **macOS dormant** : la machine de dev est Linux ; le code Mac ne s'exécute pas
  ici, tout est mocké, l'effet réel est validé en M8.

## Approche

### `RecordingController` (`macos_recording.py`, neuf)

Classe autonome, **dépendances injectées** pour rester testable sans Mac :
`transcribe_fn(wav) -> str` (transcription serveur-local) et `settings_provider()`
(relu à chaque dictée). `sounddevice` et `cli` importés paresseusement.

**Capture PortAudio bornée** — `sd.RawInputStream` int16 mono 16 kHz. Le callback
temps réel ne bloque pas, ne fait pas d'I/O disque, n'appelle pas Whisper, ne lève
pas : il copie les frames dans un tampon **borné** (plafond en frames), note les
statuts overflow. Finalisation hors callback : `stop()`/`close()` best-effort (les
frames sont déjà en mémoire, un hoquet de fermeture ne doit pas coûter la dictée) ;
WAV écrit via le module `wave`, qui corrige l'en-tête sur flux seekable. Un
`threading.Timer` (`max_recording_seconds`) arrête une dictée oubliée.

**Machine d'état** — `idle` → `recording` → `processing` → (`idle` | `error`).
`error` est observable et s'efface au prochain appui. `recording_lock` **distinct**
d'`inference_lock` : mélanger les deux bloquerait l'aperçu navigateur. Conflits :
appui en `processing` → refusé + notif « déjà en cours » (pas de file) ; double
appui rapide → debounce ~250 ms (`time.monotonic`). Fermeture du serveur en
`recording` → discard propre, aucune finalisation à l'arrachée.

**Worker** — sur arrêt, un fil : finalise le WAV → `transcribe_fn(wav)` →
`deliver_transcript(output, "paste", settings)` → `idle` ; toute exception →
`error` + notif `critical`. Le déclencheur ne transcrit jamais sur son fil.

### Intégration serveur (`desktop.py`, mac only)

Sous `if is_macos()` uniquement (Linux inchangé) : un `transcribe_fn` serveur-local
(`with inference_lock: get_transcriber(current_settings()).transcribe(wav).text` —
jamais un appel HTTP à soi-même, un seul modèle, un seul verrou), l'instanciation du
contrôleur attaché à `DesktopHandler._recording_controller`, et une route **lecture
seule** `GET /api/recording-state` → `{"state": …}`. Off Darwin : pas de contrôleur,
route absente (404).

### Continuité comportementale (invariants repris à l'identique)

- Sortie vide → ni copie, ni collage, ni historique.
- Historique écrit **avant** insertion ; notif de succès **après**.
- Échec d'insertion → texte récupérable, notif `critical`, jamais de succès anticipé.
- Ces trois règles vivent désormais dans **un seul** helper, `deliver_transcript`
  (`cli.py`), partagé par `dictate_once`, `toggle_dictation` et le worker macOS —
  extraction qui retire une duplication existante et empêche toute dérive sur le
  chemin que personne n'exerce à la main.

### Sécurité : aucune route HTTP à effet système sur Darwin

Le contrôleur est appelé **in-process** (par le raccourci en M5), jamais par HTTP.
Aucune route de bascule n'est créée. `GET /api/recording-state` est en lecture
seule, donc autorisée — elle n' observe qu'un état, elle ne déclenche rien.

### `aparte toggle` / `dictate` sur macOS

`toggle_dictation` : branche `is_macos()` après le `--status`, message clair au lieu
d'un crash sur l'`arecord` Linux ; `session.py` reste Linux only, intact. `dictate`
(passe unique) marchait déjà de bout en bout après M1+M3 (record_wav sounddevice →
`transcribe_path` avec **repli local** → `paste_text` mac) ; M4 n'y ajoute aucun
runtime, seulement la garantie du repli, déjà couverte par `DelegationFallbackTest`.

## Étapes d'implémentation (livrées)

1. **`deliver_transcript`** extrait dans `cli.py`, `dictate_once`/`toggle_dictation`
   le réutilisent → Linux byte-identique.
2. **`macos_recording.py`** : `RecordingController` (capture bornée, machine d'état,
   worker) + `test_macos_recording.py` (fake `sounddevice`, 16 tests).
3. **`desktop.py`** : `transcribe_fn` serveur-local, instanciation mac-only, route
   `GET /api/recording-state` + tests.
4. **`aparte toggle` mac** : message clair + test ; repli local `dictate` déjà couvert.
5. Doc : ce fichier, `tasks/todo.md` §M4, `CHANGELOG`.

Preuve : `PYTHONPATH=src python3 -m unittest discover -s tests -t tests` → 306 verts.

## Points de vigilance

- **Callback temps réel** : contrat strict (non bloquant, tampon borné, stop en
  best-effort, plafond en frames, périphérique disparu). Le `audio.py` actuel
  (`sd.rec()` durée fixe) ne prouve pas la robustesse du toggle — c'est M8.
- **Deux verrous distincts** : `recording_lock` (contrôleur) ≠ `inference_lock`
  (modèle unique, cache). Ne jamais les fusionner.
- **`macos_recording` n'importe `cli` que paresseusement** (dans le worker) : sinon
  cycle `desktop → macos_recording → cli → desktop` à l'import.
- **PyObjC/PortAudio non testables sous Linux** : capture réelle, insertion, discard
  au shutdown → smoke suite manuelle M8.

## Décisions explicitement écartées

- **Transposer `session.py` sur Mac** (enregistreur détaché, `/proc`) — plus de code
  pour reproduire une architecture dont la raison d'être disparaît en résident.
- **Une route HTTP de bascule** — serait un proxy de privilèges TCC ; le raccourci
  appelle le contrôleur in-process.
- **Auto-délégation HTTP du worker** vers `/api/transcribe` — absurde dans le serveur
  lui-même ; il transcrit localement sous `inference_lock`.
- **Inliner les invariants d'insertion dans le worker** — duplication d'un code
  porteur ; on extrait `deliver_transcript` à la place.
- **Câbler le contrôleur au tray/doctor maintenant** — le tray est M6 ; M4 n'expose
  que le provider et la route lecture seule.
