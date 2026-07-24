# Round 1 — M4 : `RecordingController` in-process (revue a posteriori)

## Nature de cette revue

**Le code est déjà écrit, testé et commité** (`08ab0d9`, 306 tests verts sous
Linux). Ce n'est pas une revue de plan avant écriture : c'est une **contre-expertise
a posteriori** du découpage M4, avant d'attaquer M5 (le raccourci global + la run
loop AppKit qui *déclenchera* ce contrôleur). La question utile n'est donc pas
« coderais-tu autrement » dans l'absolu, mais : **ce contrôleur est-il correct et
la couture M4→M5 tient-elle ?** Un défaut structurel qui obligerait à réécrire le
contrôleur en M5 est ce que je cherche à débusquer maintenant.

Tu as accès au workspace. Les fichiers à lire en priorité :
- `src/aparte/macos_recording.py` — le contrôleur (l'objet de la revue).
- `src/aparte/desktop.py` — l'intégration serveur (`handler_factory`,
  `_transcribe_capture`, route `GET /api/recording-state`), sous `if is_macos()`.
- `src/aparte/cli.py` — `deliver_transcript` (helper extrait) + branche `toggle` Mac.
- `tests/test_macos_recording.py` — le fake `sounddevice` et le contrat verrouillé.
- `docs/plan-portage-macos-m4.md` — le plan consolidé.
- `docs/plan-portage-macos.md` — le plan global (M5/M6 y sont détaillés).

## Contexte

Aparté : dictée vocale locale, Linux d'abord, français d'abord. Portage macOS mené
comme un **compagnon** — le comportement Linux doit rester **byte-identique**, la
machine de dev est sous Linux donc **le code Mac ne s'exécute pas ici** (tout est
mocké, l'effet réel est validé sur un vrai Mac en M8).

Sur Linux, `aparte toggle` lance des **processus CLI éphémères** coordonnés par
fichier de session + `os.link` + `/proc` (`session.py`). Ça n'a de sens que parce
que le raccourci gsettings n'a pas de processus à lui. Sur macOS, le raccourci
global (M5) **exige** un résident — et il existe déjà : le serveur de bureau en
autostart. L'enregistrement se fait donc **en mémoire du serveur**, via
`RecordingController` : zéro sous-processus, zéro PID, zéro fichier de session,
zéro `/proc`.

## Ce qui a été livré (périmètre réel)

1. **`macos_recording.py` (neuf)** — `RecordingController`, dépendances injectées
   (`transcribe_fn`, `settings_provider`, `clock`, `sample_rate`) :
   - **Machine d'état** `idle → recording → processing → (idle | error)`, mutée
     sous un `_lock` propre. `error` est observable et s'efface au prochain appui.
   - **Capture PortAudio bornée** : `sd.RawInputStream` int16 mono 16 kHz. Le
     callback temps réel ne bloque pas, ne fait pas d'I/O, n'appelle pas Whisper,
     ne lève pas ; il copie les frames dans une liste **bornée** (`_max_frames =
     sample_rate * max_recording_seconds`) et note les statuts.
   - **Worker** : sur stop, un fil daemon finalise le WAV (`wave`), appelle
     `transcribe_fn(wav)`, puis `deliver_transcript(output, "paste", settings)` ;
     toute exception → `error` + notif `critical`.
   - **Auto-stop** par `threading.Timer(max_recording_seconds)`.
   - **`shutdown()`** : coupe une capture vive proprement, sans transcription à
     l'arrachée.
   - **Debounce** ~250 ms (`time.monotonic`) contre le double appui.

2. **`desktop.py` (mac only)** — sous `if is_macos()` uniquement (Linux
   byte-identique) : `_transcribe_capture(wav)` = `with inference_lock:
   get_transcriber(current_settings()).transcribe(wav).text` (serveur-local, un
   seul modèle, jamais d'auto-HTTP), instanciation du contrôleur attaché à
   `DesktopHandler._recording_controller`, route **lecture seule**
   `GET /api/recording-state` → `{"state": …}`. Off Darwin : pas de contrôleur,
   route 404.

3. **`cli.py`** — extraction de `deliver_transcript(output, target, settings)` :
   vide → `_notify_nothing_heard` + `False` ; sinon historique **avant** insertion,
   puis `_deliver`, → `True`. `dictate_once` et `toggle_dictation` l'appellent
   (dédup réelle) → Linux byte-identique. Branche `is_macos()` dans
   `toggle_dictation` : message clair au lieu d'un crash `arecord`.

## Décisions structurantes (et pourquoi)

- **`recording_lock` distinct d'`inference_lock`.** `inference_lock` sérialise déjà
  les transcriptions et protège le cache ; le réutiliser pour la concurrence
  d'enregistrement bloquerait l'aperçu navigateur au fil de la parole. Deux verrous.
- **`transcribe_fn` serveur-local, jamais self-HTTP.** Le worker transcrit sous
  `inference_lock` via `get_transcriber`, pas un appel à `/api/transcribe` : le
  serveur qui s'appelle lui-même en HTTP serait absurde.
- **Contrôleur dormant en M4.** La machine d'état (pur Python, testable) est isolée
  de la run loop AppKit (non testable ici) = M5. **Aucune route HTTP ne le
  déclenche** (invariant Darwin : pas de route à effet système). Seul
  `GET /api/recording-state` l'observe, en lecture seule.
- **`deliver_transcript` extrait** plutôt qu'inline dans le worker : les invariants
  d'insertion (vide → rien ; historique avant insertion ; notif de succès après ;
  échec → texte récupérable + notif critical) sont porteurs. Les dupliquer sur le
  chemin que personne n'exerce à la main = dérive silencieuse garantie.
- **Import `cli` paresseux** (dans `_deliver`, au runtime du worker) : sinon cycle
  `desktop → macos_recording → cli → desktop` à l'import.
- **Auto-stop par `Timer`**, pas `sd.CallbackStop` : simple, testable, pas de
  sémantique PortAudio à émuler sous Linux.

## Points sur lesquels je pense être solide

- La séparation des deux verrous et le worker off-thread : le déclencheur (M5) rend
  la main tout de suite, il ne transcrit jamais sur le fil de la run loop.
- L'ordre post-capture centralisé dans un seul helper partagé avec la CLI.
- Le WAV via `wave` sur flux seekable : le piège d'en-tête `SIGKILL` d'`arecord`
  (Linux) ne s'applique pas ici, l'en-tête est corrigé à la fermeture.
- `_close_stream` best-effort : les frames sont déjà en mémoire avant `stop()`, un
  hoquet de fermeture ne coûte pas la dictée.

## Zones faibles que j'assume, à challenger

Je ne les cache pas — dis-moi lesquelles comptent vraiment avant M5 et lesquelles
sont du bruit acceptable pour une infra dormante validée en M8 :

1. **Drapeaux `_truncated` et `_overflowed` posés mais jamais lus.** Le callback les
   arme (`macos_recording.py:198-202`) et rien ne les surface à l'utilisateur ni
   aux logs. État mort. Faut-il notifier « enregistrement tronqué au plafond » /
   « le micro a débordé », ou est-ce du sur-signalement qu'on ajoutera si le besoin
   réel émerge en M8 ?

2. **`shutdown()` ne couvre que `RECORDING`, pas `PROCESSING`.** Si le serveur
   ferme pendant qu'un worker transcrit, le fil daemon est tué abruptement. Le texte
   éventuel est déjà en historique (écrit avant insertion), mais l'insertion peut
   être coupée en vol. Acceptable, ou faut-il attendre/joindre le worker ?

3. **Le debounce peut avaler un stop volontaire.** Deux appuis à < 250 ms sont
   traités comme un seul intent : le second est ignoré (`toggle()`
   `macos_recording.py:135-136`). Un utilisateur qui tape start puis stop très vite
   croit avoir arrêté ; l'enregistrement continue jusqu'au plafond ou au prochain
   appui. 250 ms est-il le bon seuil, la bonne sémantique ?

4. **Fuite théorique de stream si `_arm_cap_timer` lève.** Dans `_start_locked`,
   l'ordre est : stream créé, `stream.start()`, `self._stream = stream`, état
   `RECORDING`, `_arm_cap_timer`, beep. Si `_arm_cap_timer` levait (p. ex.
   `Timer.start()` → `RuntimeError: can't start new thread` sous épuisement de
   threads), `_begin_locked` fait `self._stream = None` **sans** `close()` → stream
   ouvert orphelin, callback encore vivant. Cas extrême, mais réel. Vaut-il un
   `close()` dans le `except` de `_begin_locked` ?

5. **Redondance plafond-frames / cap-timer.** `_max_frames` et le `Timer` valent
   tous deux `max_recording_seconds` : au plafond, le callback cesse d'ajouter des
   frames pile quand le timer va tirer. Ceinture + bretelles voulue, ou complexité
   inutile (un des deux suffit) ?

6. **La couture M4→M5.** Le contrôleur est instancié dans `handler_factory` et
   attaché à `DesktopHandler._recording_controller` (attribut de **classe**). M5
   devra le retrouver depuis la run loop AppKit pour appeler `toggle()`. Est-ce le
   bon point d'ancrage, ou M5 va-t-il buter dessus (une seule instance de handler ?
   accès depuis un autre thread que le serveur HTTP) ?

## Alternatives explicitement écartées

- **Transposer `session.py` sur Mac** (enregistreur détaché, fichier de session,
  `/proc`) — plus de code pour reproduire une architecture dont la raison d'être
  (pas de processus résident) disparaît sur Mac.
- **Une route HTTP de bascule** — proxy de privilèges TCC ; le contrôleur s'appelle
  in-process.
- **Auto-délégation HTTP du worker** vers `/api/transcribe` — absurde dans le
  serveur lui-même ; transcription locale sous `inference_lock`.
- **Câbler le contrôleur au tray/doctor maintenant** — tray = M6 ; M4 n'expose que
  le provider d'état et la route lecture seule.

## Ce que j'attends de toi

Concentre-toi sur : (a) la **correction** du contrôleur (concurrence, états, fuites,
chemins d'erreur) ; (b) la **solidité de la couture M4→M5** — un défaut qui
forcerait à réécrire ce contrôleur quand le raccourci arrivera ; (c) mes 6 zones
faibles ci-dessus : lesquelles bloquent M5, lesquelles sont du bruit acceptable
pour une infra dormante validée à la main en M8. Ne réinvente pas un design
Linux-first ni ne rejoue le plan global déjà acté. Sois catégorique où tu as des
certitudes.
