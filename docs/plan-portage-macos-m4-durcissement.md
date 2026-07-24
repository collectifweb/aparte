# Plan : durcissement M4 avant M5 — `RecordingController` (Aparté, portage macOS)

Issu d'une contre-expertise a posteriori du lot M4 (le `RecordingController`
in-process, commit `08ab0d9`). Verdict partagé : **le découpage M4 tient** — rien
n'oblige à réécrire le contrôleur pour brancher M5. Mais **cinq corrections
chirurgicales doivent être appliquées avant de câbler le raccourci global (M5)**,
plus six points datés à des lots ultérieurs. Ce document est la liste de travail.

Le M4 tel que livré ne change **aucun comportement observable** : le contrôleur est
dormant (rien ne l'appelle avant M5), le chemin Linux est byte-identique. Les
défauts ci-dessous se manifesteraient **au moment où M5 déclenche le contrôleur** —
d'où « avant M5 ». La machine de dev est sous Linux : tout reste prouvé par tests
mockés, l'effet réel est validé à la main sur un vrai Mac en M8.

## Contexte

Sur macOS, l'enregistrement vit **en mémoire du serveur résident**
(`RecordingController`, `src/aparte/macos_recording.py`) : pas de sous-processus, pas
de fichier de session, pas de `/proc`. Trois fils cohabitent : le fil **déclencheur**
(le raccourci, en M5), le fil **audio temps réel** (callback PortAudio), et un fil
**worker** (transcription + insertion). Les corrections portent sur les courses
entre ces fils et sur la parité fonctionnelle avec le chemin Linux.

## À corriger maintenant (avant M5)

### 1. Callback isolé par capture (course callback tardif / stream fuité)

**Défaut.** `_callback` écrit dans les attributs d'instance (`self._frames`,
`self._frame_count`, `self._truncated`, `self._overflowed`) sans garde. À l'arrêt,
`_stop_locked` échange `self._frames` et défère la fermeture du stream au worker. Un
callback qui arrive entre l'échange et le `stop()` réel — ou sur un ancien stream
dont `close()` a silencieusement échoué — écrit dans l'état vivant et peut
**contaminer la capture suivante**, parce que le callback est une méthode liée
partagée qui vise toujours l'instance courante. Rare, mais c'est un défaut de
correction.

**Correction.** Faire du callback une **fermeture propre à chaque capture**.
`_start_locked` crée une **capsule mutable par capture** — un objet portant au
minimum `frames`, `frame_count`, `max_frames`, `active` (et idéalement `truncated`,
`overflowed`) — et lie le callback à *cette* capsule. Un stream fuité écrit alors
dans sa propre capsule morte, jamais dans la vivante. Le contrôleur ne garde qu'une
référence à la capsule active pour que `_stop_locked` la saisisse, et bascule
`active = False` à l'arrêt.

`_close_stream` **reste best-effort** (les frames sont déjà saisies ; un hoquet de
fermeture ne doit pas coûter la dictée — invariant du projet). L'isolation par
capsule rend ce best-effort sûr : une fermeture ratée peut laisser le périphérique
ouvert, mais **ne peut plus contaminer** la capture d'après.

**Tests.** Nourrir l'ancien callback **après** stop → aucune écriture dans la capsule
suivante. Forcer un `close()` qui échoue, démarrer une nouvelle capture, nourrir
l'ancien callback → la nouvelle capture reste propre.

### 2. Ordre des bips (le ton d'ouverture entrait dans l'enregistrement)

**Défaut.** `play_beep` est synchrone exprès : « le ton d'ouverture doit être fini
avant que le micro démarre, sinon il entre dans l'enregistrement »
(`src/aparte/audio.py`). Le chemin Linux respecte (bip puis capture). Le contrôleur
fait l'inverse : `stream.start()` **puis** le bip `start`.

**Correction.** Jouer le bip `start` **avant le démarrage effectif de la capture**
(`stream.start()`). Il n'est pas nécessaire qu'il précède la *construction* de
`RawInputStream`, seulement son démarrage. Déplacer le bip `stop` **après** la
fermeture du stream (cohérence ; la fermeture partant dans le worker, ça ne bloque
pas la run loop).

**Test.** Avec `beep = True`, le bip d'ouverture est joué avant le démarrage de la
capture.

### 3. Polissage dans le worker (parité typographie française)

**Défaut.** `_transcribe_capture` rend `transcribe(wav).text` **cru**
(`src/aparte/desktop.py`), et le worker enchaîne `deliver_transcript`, qui ne polit
pas. Le chemin Linux polit par défaut (`transcribe_path` → `polish_text` selon les
réglages). Résultat : le futur raccourci macOS livrerait du texte **sans typographie
française** — l'app « français d'abord » perdrait sa raison d'être sur son chemin
principal.

**Correction.** Le polissage va dans le **worker** (`_finalize`), **pas** dans
`_transcribe_capture` : cette primitive est l'équivalent conceptuel de
`/api/transcribe` (transcription brute serveur-locale) et doit rester réutilisable
sans effet de polissage caché. Pipeline du worker :

1. transcription brute sous `inference_lock` ;
2. polissage selon les réglages du raccourci résident (le raccourci n'a pas d'args
   par appel → défauts des réglages : polissage activé, `style = default_style`,
   `cleanup_level = settings.cleanup_level`) ;
3. `deliver_transcript`.

Extraire un **helper partagé avec la CLI** qui exprime lisiblement ce pipeline, au
lieu de reconstruire un `argparse.Namespace` fragile — même raison que l'extraction
de `deliver_transcript` : empêcher la dérive sur le chemin que personne n'exerce à
la main. Le worker prend **une seule snapshot de `Settings`** pour polir **et**
livrer, sinon on polirait avec un jeu de réglages et on insérerait/historiserait
avec un autre.

**Test.** Le chemin in-process livre du texte **poli** (typographie française), même
chaîne que Linux.

### 4. Stop robuste (jamais d'état `PROCESSING` collé)

**Défaut.** Dans `_stop_locked`, l'état passe à `PROCESSING` **puis** on lit
`settings_provider().beep` et on démarre le worker. Si l'un lève (config JSON
corrompue ; épuisement de threads sur `Thread.start()`), le stream n'est pas fermé,
les frames sont perdues, et l'état **reste collé sur `PROCESSING` pour toujours** —
tout appui suivant répond « déjà en cours », la dictée est morte jusqu'au
redémarrage.

**Correction.** Lire le réglage du bip **avant** de muter l'état ; envelopper le
démarrage du worker de sorte qu'un échec ferme le stream, nettoie les références et
bascule en **`ERROR`** (observable, s'efface au prochain appui), jamais un
`PROCESSING` orphelin.

**Test (le test EST le contrat).** `settings_provider` **ou** `Thread.start` qui lève
pendant `_stop_locked` ⇒ stream fermé + état `ERROR`.

### 5. Fermeture du stream dans le chemin d'erreur de start

**Défaut.** Si `_arm_cap_timer` lève après `stream.start()` (ex. `Timer.start()` →
`RuntimeError` sous épuisement de threads), le `except` de `_begin_locked` fait
`self._stream = None` **sans** fermer le stream déjà démarré → stream ouvert
orphelin, callback encore vivant.

**Correction.** Dans le chemin d'erreur de `_begin_locked`, fermer le stream déjà
créé/assigné **avant** de le mettre à `None`. Chirurgical, sans contrepartie.

## Reporté, explicitement daté

- **M5 — `toggle()` tient le lock pendant de l'I/O.** `toggle()` garde `_lock`
  pendant l'import/ouverture `sounddevice`, `RawInputStream.start()`, `Timer.start()`,
  les bips, les notifications. Ce n'est pas un défaut M4 mais une **contrainte ferme
  de M5** : le callback Carbon/AppKit doit **dispatcher hors run loop** avant
  d'appeler `toggle()`, sinon il bloque la run loop.
- **M5 — référence explicite au contrôleur.** L'ancrage actuel
  `DesktopHandler._recording_controller` (attribut de classe) ne bloque pas M5, mais
  le propriétaire naturel est le processus desktop / run loop. M5 garde une
  référence explicite dans `run_desktop()` et la passe au hotkey/tray ; le handler
  HTTP ne fait qu'observer.
- **M5/M6 — câbler `shutdown()`.** Dès que M5 rend la capture déclenchable dans
  l'application résidente, `run_desktop()` doit appeler `shutdown()` au shutdown
  applicatif (aujourd'hui son `finally` ne fait que `server_close()`). Le choix fin
  abandon-immédiat vs `join()` borné vs état « closing » peut rester M5/M6, avec le
  menu « Quitter » du tray.
- **M5 — sémantique du debounce.** Le debounce global 250 ms (< seuil transcrivable
  300 ms) reste défendable ; le restreindre à `IDLE/ERROR → RECORDING` se décide
  **après** avoir observé si `RegisterEventHotKey` duplique les événements.
- **M6/M8 — surface d'état riche.** Surfacer `_truncated`, `_overflowed` et la
  dernière erreur (le tray/doctor diagnostique une capture réelle dégradée). Inutile
  pour brancher le raccourci.
- **M6 — worker daemon vs fermeture pendant `PROCESSING`.** Trancher explicitement
  abandon documenté vs `join()` borné, avec « Quitter » / « Mettre à jour ».

## Points de vigilance pendant l'implémentation

- **Comportement Linux byte-identique** : toutes ces corrections sont sous le chemin
  macOS ou dans le contrôleur dormant. La suite complète reste verte, les tests
  Linux inchangés.
- **Le plus simple d'abord** : la capsule par capture est une *simplification* du
  modèle de concurrence (chaque capture possède son état), pas une surcouche.
- **Plafond en frames** : le décrire comme « max + un bloc de callback » (le chunk
  qui franchit le seuil est accepté), pas comme une limite stricte à la frame près.
- **Preuve** : `PYTHONPATH=src python3 -m unittest discover -s tests -t tests`, plus
  les tests neufs des cinq corrections.

## Décisions explicitement écartées

- **Polissage dans `_transcribe_capture`** — casse la primitive de transcription
  pure ; le polissage vit dans le worker.
- **Rendre `_close_stream` fatal** — un hoquet de fermeture ne doit pas coûter une
  dictée déjà capturée ; l'isolation par capsule rend le best-effort sûr.
- **Corriger le debounge / la surface d'état / le câblage `shutdown` maintenant** —
  non bloquant pour M5, daté aux lots où le besoin réel apparaît.
- **Réécrire le contrôleur** — aucun défaut structurel ne le justifie.
