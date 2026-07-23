# Plan : compatibilité macOS pour Aparté

## Contexte

Aparté est une application de dictée vocale **Linux uniquement**, Python 3.10+, sans
framework, paquet dans `src/aparte/`. Le chemin principal du produit : un raccourci
clavier global démarre l'enregistrement, un second appui transcrit (Whisper local) et
**insère le texte dans l'application active**. Une interface web locale (`desktop.py`,
`127.0.0.1:8765`) sert d'alternative et d'écran de réglages.

On veut rendre l'application **compatible macOS** (cible prioritaire). Windows est
étudié séparément et n'est pas planifié ici.

### Contraintes produit non négociables

- **« Linux d'abord, français d'abord »** est le positionnement identitaire. macOS
  reste un **compagnon** — « Aparté tourne aussi sur Mac » —, jamais un pivot. Le code
  Linux existant et testé ne doit pas être déstabilisé.
- **Interface web sans étape de compilation ni bibliothèque** (HTML/CSS/JS à la main).
  Le portage n'y touche pas.
- **Tout local** : l'audio et le texte dicté ne quittent jamais la machine. (Nuance
  assumée et documentée : le modèle Whisper peut être téléchargé une fois au premier
  usage — voir « Acquisition des modèles ».)

### Le constat qui change le calcul

Le cœur est **déjà portable** : `polish.py`, `numbers.py`, la typographie, l'UI web,
`desktop.py`, faster-whisper — zéro appel système. L'UI web enregistre **dans le
navigateur** (`getUserMedia`). Donc sur Mac aujourd'hui déjà, `pip install` +
`aparte desktop` sert la page, transcrit, polit et copie. Ce qui manque : insertion dans
l'app active, raccourci global, notifications natives, tray, bascule au raccourci.

**Premier palier documentaire (quasi gratuit) :** documenter que la dictée navigateur
fonctionne déjà sur Mac. Ce n'est pas « la compatibilité macOS » au sens fort — le
produit, c'est l'insertion dans l'app active sans revenir à l'interface — mais c'est un
point de départ réel dès M0.

### Ce qui survit tel quel (macOS est de l'Unix)

`os.killpg`, `os.link`, `start_new_session`, signaux, `os.getuid()`, chemins
`~/.config`, repli `$TMPDIR` de `get_runtime_dir()`. Le préchargement CUDA de
`transcription.py` est inoffensif (retour immédiat, aucun `.so` à charger).

### Ce qui casse ou manque

`_recorder_alive()` lit `/proc/<pid>/cmdline` — pas de `/proc` sur Mac. `arecord`
(ALSA), `xclip`/`wtype`, `notify-send`, `gsettings`, PyGObject/GTK, fichiers `.desktop` :
aucun sur Mac. `WhisperCppTranscriber` existe mais reste un wrapper CLI non prouvé
(il passe `-m small` là où whisper.cpp attend un chemin de modèle ggml/gguf).

## Approche

### Architecture : pas de grande couche d'abstraction

Les modules concernés font 44 à 317 lignes, API stables, déjà simulées par les tests.
On garde le patron `*_desktop.py` (le nom porte l'OS) et des branches `sys.platform` :

1. **Modules OS-spécifiques neufs** : `macos_desktop.py` (LaunchAgent + bundle `.app`),
   `macos_hotkey.py` (RegisterEventHotKey, façade testée), `macos_tray.py` (rumps).
   Sélection par `sys.platform == "darwin"` au point d'appel. **Le code Linux n'est pas
   touché.**
2. **Modules mixtes** (`clipboard.py`, `notify.py`, `audio.py`) : branche `sys.platform`
   en tête des fonctions publiques. API inchangée.
3. **`session.py` reste Linux.** Sur Mac, l'état d'enregistrement vit dans le serveur
   résident (voir `RecordingController`).

On écarte une couche `platform/base.py` + implémentations : sur-ingénierie pour 6 modules
courts aux API déjà stables. Le patron ci-dessus suffit et garde le code Linux intact.

### Le pivot : enregistrement in-process dans le serveur résident

Sur Linux, le raccourci lance des **processus CLI éphémères** qui se coordonnent via
fichier de session + lien physique + `/proc`. Ça n'a de sens que parce que le raccourci
gsettings n'a pas de processus à lui.

Sur Mac, le raccourci global **exige** un processus résident (RegisterEventHotKey a
besoin d'une run loop vivante), et ce processus existe déjà : le serveur de bureau, en
autostart. Donc sur Mac, l'enregistrement se fait **en mémoire du serveur**, via un
objet `RecordingController` — zéro sous-processus, zéro PID, zéro fichier de session,
zéro `/proc`. C'est **moins de code** que de transposer `session.py`, pas plus.

**Conséquence produit assumée et documentée :** sur macOS, le raccourci **exige que
l'application tourne** (sur Linux il fonctionne même serveur éteint, car gsettings tire
une commande). Ce n'est pas une couche supplémentaire — sur macOS le serveur résident
**est** l'application (un seul processus porte le tray, le raccourci et le serveur HTTP)
—, mais c'est un prérequis utilisateur réel, signalé par `doctor` et la documentation.

#### `RecordingController` — machine d'état serveur

- **États** : `idle` ; `recording` (stream PortAudio actif, `start_time`, compteur de
  frames, tampon borné, statut overflow/underflow) ; `processing` (finalisation WAV →
  transcription → polissage → insertion) ; `error` (observable).
- **`recording_lock` distinct d'`inference_lock`.** `inference_lock` sérialise déjà les
  transcriptions et protège `transcriber_cache` ; il ne doit pas servir à la concurrence
  d'enregistrement, sinon la bascule bloque l'aperçu navigateur.
- **Le handler du raccourci ne transcrit jamais sur la run loop** : il bascule l'état,
  lance un worker, rend la main immédiatement.
- **Provider d'état** exposé au tray et à `doctor` (`idle`/`recording`/`processing`/
  `error`), sinon l'UI afficherait « idle » pendant qu'un enregistrement mémoire tourne.
- **Sémantique des conflits** (tranchée) :
  - appui pendant `processing` → ignoré + notification « déjà en cours » (pas de file) ;
  - double appui rapide → debounce court (≈250 ms) + état idempotent (`start` sur
    `recording` = no-op) ;
  - `?preview=1` pendant l'arrêt d'une dictée → sémantique actuelle conservée (l'aperçu
    prend le verrou sans attendre, rend `{"text": null, "busy": true}` si occupé) ;
  - fermeture du serveur pendant `recording` → discard propre (stop + close dans un
    `finally`, pas de finalisation à l'arrachée).

#### Contrat du callback PortAudio/sounddevice

Le callback ne bloque pas, ne fait pas d'I/O disque, n'appelle pas Whisper, n'alloue pas
massivement, ne prend pas de verrou long, ne lève pas d'exception espérée récupérable
(les exceptions de callback ne remontent pas comme une exception Python normale). Il
copie les frames vers une queue/tampon borné et capture les statuts overflow/underflow.
Finalisation **hors callback** : `stream.stop()` / `stream.close()` dans un `finally`,
plafond `max_recording_seconds` exprimé en **nombre de frames**, nettoyage si le
périphérique disparaît. Le WAV final s'écrit avec le module `wave` (`wave.open(..., "wb")`
+ `setsampwidth(2)` + `setframerate` + `writeframes`), qui corrige l'en-tête sur flux
seekable — l'en-tête n'est pas un point de risque ici ; la capture temps réel, le stop
propre et la récupération après crash le sont.

### Insertion : Cmd+V d'abord, frappe Unicode en repli

Pour une dictée française longue, le **collage natif** (`pbcopy` + `Cmd+V` simulé via
CGEvent sur les touches Cmd+V) arrive intact dans Slack, Mail, navigateurs, Electron —
bien mieux qu'une rafale d'événements clavier synthétiques. C'est le chemin **principal**
à durcir en premier. La **frappe Unicode directe** (`CGEventKeyboardSetUnicodeString`)
devient le **repli / mode spécialisé**, testée sur texte long, caractères composés,
champs web et apps sandboxées. On écarte `osascript/System Events keystroke` : il
déclenche une invite Automatisation en plus d'Accessibilité, et `keystroke "texte"`
massacre les caractères hors disposition clavier (’ « » U+00A0) — rédhibitoire pour le
français.

Cmd+V s'aligne sur le `paste_mode="clipboard"` **déjà existant** (copie puis colle). Le
mode `terminal` Linux (frappe directe) devient le mode « frappe Unicode » mac, secondaire.

**Continuité comportementale (invariants repris à l'identique) :**
- sortie vide → **ni copie, ni collage, ni historique** ;
- historique écrit **avant** insertion ;
- notification de succès **après** insertion ;
- échec de collage → texte récupérable (historique + presse-papiers selon le mode), pas
  de notification de succès prématurée.

### Le raccourci global : RegisterEventHotKey

`RegisterEventHotKey` (API Carbon, toujours fonctionnelle sur macOS récent) **ne demande
pas la permission « Surveillance de l'entrée »**, contrairement à un event tap
(`CGEventTap`/`pynput`). Le serveur résident satisfait déjà la contrainte « run loop
vivante ». Le gestionnaire appelle **directement**, en in-process, la logique de bascule
du `RecordingController` — aucune route HTTP.

- **`macos_hotkey.py` est une façade testée.** On essaie `quickmachotkey` (PyPI
  2025.7.28, `glyph/QuickMacHotKey`) pour le prototype, mais la façade expose l'`OSStatus`
  et les échecs de combinaison. Si la lib ne donne pas assez de contrôle sur les conflits
  (combinaisons réservées, déjà prises, changements type Sequoia sur Option/Shift seules),
  on la remplace par un petit binding ctypes/PyObjC interne sans changer les appelants.
- Le « 0 permission » est vrai pour la famille « surveillance de l'entrée », mais **pas
  une garantie absolue** : une combinaison réservée ou déjà prise peut échouer, d'où le
  besoin de bons diagnostics.
- **Plan B documenté, non intégré** : `skhd` (une ligne dans `~/.config/skhd/skhdrc`),
  l'équivalent des instructions manuelles que `hotkey.py` imprime déjà pour les bureaux
  Linux non gérés.

### Run loop AppKit unique

**Règle imposée : une seule run loop AppKit sur le fil principal.**

- Le serveur HTTP reste sur un **thread secondaire**.
- Tray disponible → **rumps possède la run loop** (`rumps.App.run()`), le raccourci est
  enregistré pendant l'initialisation de rumps. On n'appelle jamais `rumps.App.run()`
  **et** `AppHelper.runEventLoop()` comme deux boucles concurrentes.
- Tray indisponible → on **ne peut pas** copier la branche Linux « pas de tray ⇒ serveur
  sur le fil principal » : le raccourci a quand même besoin d'une run loop AppKit/CF. Le
  runner macOS démarre alors une run loop AppKit minimale (NSApplication +
  `AppHelper.runEventLoop()`) sur le fil principal, serveur toujours en secondaire.
- Les actions du raccourci partent vers un worker ; elles ne bloquent jamais la run loop
  pendant la transcription.

C'est le point technique le plus incertain — il se **prouve sur un vrai Mac** (M5).

### Sécurité : aucune route HTTP à effet système sur Darwin

Sur macOS, le serveur résident détient des permissions TCC (Microphone, Accessibilité)
qu'un navigateur ou un process local lambda n'a pas. Une route HTTP qui utiliserait ces
permissions deviendrait un **proxy de privilèges**. Le principe, appliqué jusqu'au bout :
**sur Darwin, aucune route HTTP ne réalise une action à effet système ou privilégiée.**
Les actions natives passent par le raccourci in-process, le tray, ou la CLI.

| Route | Décision Darwin |
|---|---|
| `GET /`, `GET /api/config`, `GET /api/doctor`, `GET /api/history`, `GET /api/microphones`, `GET /api/update/check` | **gardées** (lecture seule) |
| `POST /api/transcribe` (rend du texte ; micro = celui du navigateur) | **gardée**, garde-fou Origin |
| `POST /api/polish` (rend du texte poli) | **gardée**, garde-fou Origin |
| `POST /api/config` (écrit `config.json`, donnée applicative) | **gardée** (réglages web ; ni TCC ni action système) |
| `POST /api/history` (écrit l'historique, donnée applicative) | **gardée** |
| `POST /api/paste` (tape dans la fenêtre active, Accessibilité) | **désactivée** (404). Insertion = raccourci in-process + CLI |
| `POST /api/copy` (`pbcopy`) | **désactivée.** L'UI copie via `navigator.clipboard.writeText` sous geste utilisateur |
| `POST /api/update/apply` (`git`/`pip` + redémarrage) | **désactivée.** Update = menu du tray (in-process) ou `aparte update` (CLI) |

Les cinq surfaces sensibles sont donc entièrement hors HTTP sur Darwin : presse-papiers
(`/api/copy`), clavier/insertion (`/api/paste`), update (`/api/update/apply`), et —
déjà le cas — installation du raccourci/LaunchAgent et réparation des permissions
(jamais des routes HTTP ; CLI/natif). `/api/config` et `/api/history` restent parce
qu'elles écrivent les **données de l'application** (réglages, historique), pas un état
système.

**Délégation CLI resserrée :** la seule délégation HTTP de la CLI est
`transcribe_via_running_app()` (« transcris cet audio, rends du texte » — opération pure).
La bascule à deux appuis est fournie **uniquement** par le raccourci natif in-process ;
on ne réplique pas la chorégraphie `session.py` sur macOS. `aparte dictate` (une passe)
enregistre **dans le processus appelant**, transcrit, insère — un seul processus, sans
HTTP ni fichier de session (marche si ce processus a les permissions TCC ; recommandé via
le bundle).

**Défense en profondeur (complément) :** les routes à écriture restantes refusent si le
host effectif n'est pas loopback (utile avec `--host 0.0.0.0`) ; un test explicite
« requête sans `Origin` sur une route à écriture » verrouille le comportement.

### Transcription : faster-whisper CPU en v1, whisper.cpp/Metal après

- **Baseline v1 = faster-whisper CPU.** CTranslate2 a des wheels arm64 ; il tourne sur
  CPU macOS **sans une ligne de code de transcription nouvelle**, et porte « Mes mots »
  (`hotwords`), les langues, le cache serveur — tout ce qui est déjà testé. Plus lent que
  Metal, mais **prouvé et gratuit en code**. C'est ça, le vrai « zéro code ».
- **whisper.cpp/Metal = lot d'optimisation post-v1**, chiffré comme intégration réelle.
  Il demande un réglage **`whisper_cpp_model`** distinct (chemin ggml/gguf, séparé de
  `model` et du `whisper_cpp` exécutable) ; absent ⇒ `WhisperCppTranscriber` refuse
  proprement avec un message clair (aujourd'hui il enverrait `-m small` en silence).
  Nouveau champ dans `DEFAULT_CONFIG` + `EDITABLE_FIELDS`, `None` par défaut : personne
  n'est affecté tant qu'il ne choisit pas whisper.cpp. Plus : doc de placement des
  modèles, détection Metal/Core ML réelle, tests d'erreur.

La **v1 macOS livrable ne dépend pas de whisper.cpp** — ce qui dérisque tout le portage.

### Acquisition des modèles vs « tout local »

`WhisperModel(self.model_name, …)` récupère le modèle depuis HuggingFace **au premier
usage** si le cache local est vide (comportement déjà celui de Linux). La promesse « rien
ne sort de la machine » porte sur **l'audio et le texte dicté** : ça ne sort jamais. Le
téléchargement **unique** du modèle utilise le réseau une fois. On l'énonce honnêtement :

1. **`install-macos.sh` propose le préchargement du modèle par défaut avec consentement
   réseau explicite** (invite « Télécharger le modèle *small* maintenant ? [O/n] »).
   Refus ⇒ pas d'appel réseau à l'install.
2. **`doctor` signale l'état** : modèle en cache → « prêt, hors-ligne » ; absent → « la
   première transcription téléchargera le modèle *X* depuis HuggingFace ».
3. **La documentation** dit : audio et texte ne quittent jamais la machine ; un
   téléchargement réseau **unique** du modèle a lieu au premier usage sauf préchargement ;
   ensuite, tout est hors-ligne.

On ne modifie pas l'appel `WhisperModel` du cœur (ça toucherait Linux). Optionnel,
hors v1 : `download_root` vers un cache dédié pour un emplacement déterministe.

### Autres surfaces

| Surface | macOS | Note |
|---|---|---|
| Copie | `pbcopy` (préinstallé) ; l'UI web via `navigator.clipboard` | — |
| Notifications | natives attribuées au bundle si tray rumps présent, sinon `osascript` | attribution osascript = « Éditeur de script », d'où la préférence native |
| Bips | `afplay` | — |
| Micros | `sounddevice.query_devices()` (IDs PortAudio, **à ne pas confondre** avec les noms ALSA `plughw` de Linux) | sérialisation `microphone` distincte |
| Autostart | LaunchAgent `.plist` + `launchctl bootstrap` | attribution TCC au bundle à préserver |
| Identité | bundle `.app` (`CFBundleIdentifier` stable + `NSMicrophoneUsageDescription`) | voir « TCC » |
| Chemins | inchangés (`~/.config` marche) | — |

### Historique

**Fichier runtime mode `0600`** (dans `$TMPDIR`), pas mémoire serveur : il préserve
`aparte last` et le partage inter-processus sans rendre le serveur encore plus central.
`history_persist=False` garde son sens (pas d'écriture dans `~/.local/state`). **Nuance
documentaire sur Darwin** : `$TMPDIR` n'est pas un tmpfs systemd ; les textes fr/en qui
promettent une disparition « à la fermeture de session » sont nuancés (effacement au
redémarrage/nettoyage système, pas garanti à la déconnexion).

### TCC : deux niveaux, assumés

- **v1 expérimental (sans compte Apple)** : bundle `.app` avec `Info.plist` +
  `CFBundleIdentifier` stable + `NSMicrophoneUsageDescription`, avertissements clairs,
  attribution TCC **possiblement fragile**, testée à la main. Livrable sans dépenser
  99 $/an ni notariser.
- **v1 distribuable (post-v1)** : lanceur Mach-O minuscule (pas `python` nu),
  `CFBundleIdentifier` stable, signature Apple Development ou Developer ID, LaunchAgent
  attribué au bundle, vérification sur compte utilisateur frais.

Un `.app` non signé qui lance `python -m aparte` depuis une venv **n'est pas** une base
fiable d'attribution TCC durable : le « code responsable » vu par TCC peut devenir
Terminal, Python, un ancien chemin de venv ou un helper `launchd`, et la permission se
perdre après update ou relance. Le passage d'un niveau à l'autre est une décision
produit/budget, nommée comme jalon (M10), pas un sous-entendu.

Deux permissions bloquantes, incompressibles (aucune appli de dictée Mac n'y échappe) :
**Microphone** et **Accessibilité** (pour le collage — pas d'invite « Autoriser », détour
Réglages + relance).

### Empaquetage et mise à jour

`install-macos.sh` symétrique du `.sh` Linux : venv, `pip install -e ".[whisper,
recording,macos]"`, écriture du LaunchAgent, création du bundle `.app`, préchargement de
modèle consenti, `brew install whisper-cpp` optionnel (post-v1). Prérequis : Command Line
Tools (git).

Extra **`[macos]`** : frameworks PyObjC exacts utilisés (`pyobjc-framework-Quartz` pour
CGEvent ; `pyobjc-framework-Cocoa`/`AppKit` et `AVFoundation` selon l'implémentation —
micro et notif natives), `rumps`, `quickmachotkey` (derrière la façade). Vérifier les
wheels arm64 ; éviter de tirer la moitié de PyObjC pour trois frameworks.

**Lot `update.py` macOS** (l'actuel ne « fonctionne pas tel quel ») :
- `_installed_extras()` ne connaît que `whisper`/`recording`/`cuda` : **préserver
  `[macos]`** au redémarrage après update.
- `os.execv(sys.executable, argv)` relancerait l'interpréteur/module, pas l'application
  responsable vue par TCC : **redémarrage via le bundle / le LaunchAgent**.
- `find_repo()` suppose un checkout editable : **le lier à l'install** (bundle enveloppant
  la venv du checkout).
- L'update macOS est déclenché par le **menu du tray** (in-process) ou `aparte update`
  (CLI), **jamais** par une route HTTP.

On écarte : py2app/briefcase (gigaoctets, signature/notarisation payante, casse le
checkout git) ; tap Homebrew en v1 (une install brew n'est pas un checkout git, `update.py`
tomberait en état `manual`).

## Étapes d'implémentation

| Lot | Contenu | Effort |
|---|---|---|
| M0 | Dispatch `sys.platform`, extra `[macos]`, classifieurs, **doc dictée navigateur** | 0,5 j |
| M1 | Socle trivial : `pbcopy`, notifs (natives si tray, sinon osascript), `afplay`, micros PortAudio, `record_wav` mac | 1,5–2 j |
| M2 | Diagnostics macOS (`doctor` + panneau) : `AVFoundation` micro (notDetermined/denied/restricted/authorized), `AXIsProcessTrustedWithOptions`, état du modèle, `fix` brew, textes fr/en | 1,5–2 j |
| M3 | Insertion : **Cmd+V d'abord** + frappe Unicode en repli, continuité clipboard/historique/notif, parcours Accessibilité guidé | 2–2,5 j |
| M4 | **`RecordingController`** in-process : machine d'état, `recording_lock`, callback PortAudio borné, worker, provider d'état, CLI `dictate` (repli local intact) | 3–4 j |
| M5 | Raccourci global RegisterEventHotKey via `macos_hotkey.py` (façade) + **run loop AppKit unique**, install-hotkey mac, diagnostics d'échec de combinaison | 2,5–3,5 j |
| M6 | Tray rumps (menu + **item « Mettre à jour »** in-process + provider d'état + icônes PNG template) | 1–1,5 j |
| M7 | Empaquetage v1 expérimental : LaunchAgent, bundle `.app`, `install-macos.sh` (préchargement consenti), **lot `update.py` macOS**, doc | 3–4 j |
| M8 | Tests : unitaires mac mockés (dispatch, plist/bundle, parsing PortAudio, garde-fous HTTP, machine d'état) + Linux-only marqués + **smoke suite manuelle documentée** | 1,5–2,5 j |
| **Total v1 (M0–M8)** | | **17–23 j** |
| M9 *(post-v1, optionnel)* | whisper.cpp/Metal : `whisper_cpp_model`, détection Metal, doc modèles, tests d'erreur | 2–3 j |
| M10 *(post-v1, distribuable)* | Signature/notarisation, lanceur Mach-O, vérif compte frais | selon budget Apple |

M3–M5 se déboguent sur un vrai Mac.

### Smoke suite manuelle Mac (M8)

La CI (runner GitHub) ne valide **ni** les prompts TCC, **ni** l'Accessibilité, **ni** le
raccourci global, **ni** le LaunchAgent au login, **ni** le collage dans de vraies apps.
Matrice manuelle, documentée et répétable :

- lancement depuis Terminal / depuis le bundle `.app` / au login via LaunchAgent ;
- après update-restart ;
- micro refusé puis accordé ; Accessibilité refusée puis accordée ;
- nouveau chemin de venv ; nouvelle version de bundle ;
- compte utilisateur frais ou VM/snapshot.

## Points de vigilance

1. **Attribution TCC réelle** (micro, Accessibilité) à travers update/relance/nouveau
   venv : ne se conclut que par la smoke suite. C'est la raison d'être de M8. Sans bundle
   signé, l'attribution reste fragile — assumé pour la v1 expérimentale.
2. **Cohabitation run loop AppKit** (rumps + RegisterEventHotKey, une seule boucle) :
   conçue, mais à **prouver sur vrai Mac** (M5). Point technique le plus incertain.
3. **Comportement de `RegisterEventHotKey`** sur les combinaisons réservées/récentes
   (Sequoia) : se découvre à l'exécution, d'où la façade avec diagnostics d'`OSStatus`.
4. **Callback PortAudio temps réel** : respecter strictement le contrat (non-bloquant,
   tampon borné, stop dans `finally`, plafond en frames, périphérique disparu). Le
   `audio.py` actuel (`sd.rec()` durée fixe) ne prouve pas la robustesse du toggle.
5. **Sérialisation `microphone`** : IDs PortAudio macOS ≠ noms ALSA `plughw` de Linux.
6. **Dette ×2 permanente** : chaque fonctionnalité système future (ex. Lot 5B, fenêtre
   flottante au raccourci) devra exister en GTK **et** en NSPanel/PyObjC.
7. **Serveur résident obligatoire** pour le raccourci sur macOS : prérequis utilisateur
   réel, à signaler dans `doctor` et la doc.

## Décisions explicitement écartées

- **Couche `platform/base.py` + implémentations** — sur-ingénierie pour 6 modules courts
  aux API déjà stables ; le patron `*_desktop.py` + branche `sys.platform` suffit.
- **Transposer `session.py` littéralement** (enregistreur détaché, `ps` pour la vivacité,
  réécriture de `_captured_seconds`) — plus de code et de surface de bogue pour reproduire
  une architecture dont la raison d'être disparaît sur Mac.
- **Event tap `CGEventTap`/`pynput` pour le raccourci** — demande la permission
  Surveillance de l'entrée, la pire ; RegisterEventHotKey n'en demande aucune.
- **`osascript/System Events keystroke` pour le collage** — invite Automatisation en plus
  d'Accessibilité, et massacre les caractères hors disposition (’ « » U+00A0).
- **Token/IPC pour sécuriser une route de bascule** — inutile : la route privilégiée
  n'existe pas (le raccourci appelle le contrôleur in-process ; aucune route HTTP à effet
  système sur Darwin).
- **whisper.cpp/Metal dans le chemin critique de la v1** — introduirait en même temps
  PortAudio temps réel, TCC, AppKit, packaging et une seconde stratégie de modèles.
  faster-whisper CPU (déjà testé) est la baseline sûre.
- **Bundle autonome py2app/briefcase** — gigaoctets, signature/notarisation payante, casse
  `update.py` (plus de checkout git).
- **Tap Homebrew en v1** — une install brew n'est pas un checkout git ; `update.py`
  tomberait en état `manual`. Envisageable plus tard.
- **Tout miser sur la page web** — palier documentaire utile, mais elle n'offre pas
  l'insertion dans l'app active, qui EST le produit.
