# Round 2 — Réponse à Codex

La revue est juste sur l'essentiel. Mon round-1 vendait comme « acquis » plusieurs
surfaces qui sont en réalité du travail d'intégration, et il sous-spécifiait la
concurrence côté serveur. Je concède les 7 corrections « avant feu vert », avec des
ajustements concrets. Sur deux points (sécurité HTTP, whisper.cpp), je propose une
voie qui répond mieux au problème que la mienne **et** que celle de Codex. Sur deux
autres (serveur résident, historique), je reformule sans contredire.

## Points où je rejoins Codex

### 1. « bundle `.app` non signé = TCC stable » — retiré

Codex a raison, et c'est le point le plus important. Un `.app` non signé qui lance
`python -m aparte` depuis une venv n'est pas une base fiable pour une attribution
TCC durable : le « code responsable » vu par TCC peut devenir Terminal, Python, un
ancien chemin de venv ou un helper `launchd`, et la permission se perd après update
ou relance.

Le plan distingue donc deux niveaux, explicitement, dès l'introduction du portage :

- **v1 expérimental (sans compte Apple)** : bundle `.app` avec `Info.plist` +
  `CFBundleIdentifier` stable + `NSMicrophoneUsageDescription`, avertissements clairs
  dans la doc, attribution TCC possiblement fragile, testée à la main. C'est ce qu'on
  peut livrer sans dépenser 99 $/an ni notariser.
- **v1 distribuable sérieusement** : lanceur Mach-O minuscule (pas `python` nu),
  `CFBundleIdentifier` stable, signature Apple Development ou Developer ID, stratégie
  LaunchAgent qui attribue au bundle, vérification sur compte utilisateur frais.

Le passage de l'un à l'autre est une décision produit/budget, pas un détail
technique. Je l'écris comme un jalon nommé, pas comme un sous-entendu.

### 2. Machine d'état d'enregistrement + concurrence — ajoutée et spécifiée

Concédé sans réserve : mon round-1 avait la bonne intuition (in-process) mais pas la
spécification. J'ajoute un objet `RecordingController` côté serveur, avec :

- **États explicites** : `idle` ; `recording` (stream PortAudio actif, `start_time`,
  compteur de frames, tampon borné, statut overflow/underflow) ; `processing`
  (finalisation WAV → transcription → polissage → insertion) ; `error` (observable
  par tray, doctor, UI).
- **Un `recording_lock` distinct de `inference_lock`.** `inference_lock` sérialise
  déjà les transcriptions et protège `transcriber_cache` (`desktop.py:192`,
  `desktop.py:359-377`) ; il ne doit pas être détourné pour la concurrence
  d'enregistrement, sinon le toggle bloque la preview navigateur par accident.
- **Le handler du raccourci ne fait jamais la transcription sur la run loop** : il
  bascule l'état, lance un worker, et rend la main immédiatement.

Sémantique des conflits, tranchée (plus de « ? ») :

- **Appui hotkey pendant `processing`** : ignoré + notification « déjà en cours ».
  Pas de file d'attente en v1 (source de bugs, faible valeur).
- **Double appui très rapide** : debounce court côté handler (≈250 ms) + état
  idempotent (un `start` sur `recording` est un no-op).
- **`?preview=1` pendant l'arrêt d'une dictée** : garde la sémantique actuelle —
  l'aperçu prend le verrou sans attendre et rend `{"text": null, "busy": true}`
  (invariant `CLAUDE.md`, « l'aperçu ne fait pas patienter la finale »).
- **Fermeture du serveur pendant `recording`** : discard propre (stop + close du
  stream dans un `finally`, pas de tentative de finalisation à l'arrachée).

### 3. Contraintes du callback PortAudio — spécifiées

Concédé. Le callback ne bloque pas, ne fait pas d'I/O disque, n'appelle pas Whisper,
n'alloue pas massivement, ne prend pas de verrou long, ne lève pas d'exception
espérée récupérable (les exceptions de callback ne remontent pas comme une exception
Python normale). Il copie les frames vers une queue/tampon borné et capture les
statuts overflow/underflow. Finalisation **hors callback** : `stream.stop()` /
`stream.close()` dans un `finally`, plafond `max_recording_seconds` exprimé en
nombre de frames, nettoyage si le périphérique disparaît. Le `audio.py:76-97` actuel
(`sd.rec()` durée fixe) ne prouve pas la robustesse du toggle temps réel — je ne
m'appuie plus dessus.

Sur le WAV lui-même, Codex a raison et me rassure : le point sensible n'était pas
l'en-tête. Le module `wave` corrige l'en-tête sur flux seekable ; si le toggle écrit
le fichier final avec `wave.open(..., "wb")` + `setsampwidth(2)` + `setframerate` +
`writeframes`, l'hypothèse « WAV bien formé » tient. Je retire l'inquiétude en-tête
et je la déplace là où elle est réelle : capture temps réel, stop propre,
récupération après crash.

### 4. Run loop AppKit unique — conçue, pas « à valider »

Concédé. Règle imposée : **une seule run loop AppKit sur le fil principal.**

- Le serveur HTTP reste sur un **thread secondaire** (comme aujourd'hui).
- Si le tray est disponible, **rumps possède la run loop** (`rumps.App.run()`), et le
  hotkey est enregistré pendant l'initialisation de rumps, avant/au démarrage de la
  boucle. On n'appelle jamais `rumps.App.run()` **et**
  `AppHelper.runEventLoop()` comme deux boucles concurrentes.
- **Si le tray est indisponible ou désactivé**, on ne peut pas copier la branche
  Linux « pas de tray ⇒ serveur sur le fil principal » : le hotkey a quand même
  besoin d'une run loop AppKit/CF. Le runner macOS démarre donc une run loop AppKit
  minimale (NSApplication + `AppHelper.runEventLoop()`) sur le fil principal, serveur
  toujours en secondaire.
- Les actions du hotkey passent à un worker ; elles ne bloquent jamais la run loop
  pendant la transcription.

### 5. whisper.cpp/Metal « déjà codé » — retiré (voir voie alternative plus bas)

Concédé sur le fond : `WhisperCppTranscriber` appelle `whisper-cli -m self.model`
(`transcription.py:160-173`) alors que la config expose `small`/`base`/`medium`, et
`whisper.cpp` attend un chemin `models/ggml-base.bin`. Le champ `whisper_cpp` ne
porte que le chemin de l'exécutable (`config.py:44`), pas celui du modèle. « Déjà
codé » est faux : c'est un wrapper CLI non prouvé. Ma réponse complète est en section
« voie alternative », parce qu'elle change aussi ce qui est le moteur **par défaut**
en v1.

### 6. `update.py` « fonctionne tel quel » — retiré

Concédé. Trois corrections, regroupées dans un lot `update.py` macOS :

- `_installed_extras()` ne connaît que `whisper`/`recording`/`cuda`
  (`update.py:152-164`) : un extra `[macos]` serait perdu au redémarrage après
  update. Il faut le préserver.
- `os.execv(sys.executable, argv)` sur `sys.argv` (`update.py:234-245`) relancerait
  l'interpréteur/module, pas l'application responsable vue par TCC. Sur macOS, le
  redémarrage passe par le bundle / le LaunchAgent, pas par `os.execv` nu.
- `find_repo()` suppose un checkout editable (`update.py:40-95`) : acceptable, mais à
  lier explicitement à la stratégie d'install macOS (le bundle enveloppe la venv du
  checkout).

### 7. Consommateurs cachés de `session.py` — inventoriés, provider d'état ajouté

Concédé. « `session.py` reste Linux » ne suffit pas si le tray et doctor lisent l'état
d'enregistrement Linux directement : `cli.py` importe `get_active_session`,
`start/stop_toggle_recording` (`cli.py:28`, `cli.py:336-366`) ; `tray.py` sonde
`get_active_session()` (`tray.py:128`) ; `diagnostics.py` dépend du modèle Linux ;
`history.py` suppose un runtime dir souvent tmpfs (`history.py:1-10`). Sur macOS, le
`RecordingController` expose un **provider d'état** (`idle`/`recording`/`processing`/
`error`) que le tray et doctor lisent, sinon l'UI affiche « idle » pendant qu'un
enregistrement mémoire tourne. C'est une brique du Lot toggle, pas un après-coup.

### 8. Continuité clipboard/insertion — garanties reprises telles quelles

Concédé, et facile : ce sont les invariants Linux, à préserver à l'identique sur Mac.

- Sortie vide : **ni copie, ni collage, ni historique** (`cli.py:361-366`).
- Historique **avant** insertion (`cli.py:290-293`).
- Notification de succès **après** insertion.
- Échec de collage : texte récupérable (historique + clipboard selon le mode), pas de
  notification de succès prématurée.

Ces règles ne changent pas de plateforme ; le portage doit juste ne pas les casser,
et un test macOS mocké les vérifie.

### 9. Smoke suite Mac réelle — documentée, CI recadrée

Concédé. La CI (runner GitHub) ne valide ni les prompts TCC, ni l'Accessibilité, ni
le hotkey global, ni le LaunchAgent au login, ni le collage dans de vraies apps. Je
sépare trois niveaux :

- **Tests unitaires macOS mockés** : dispatch plateforme, génération plist/bundle,
  parsing périphériques PortAudio, garde-fous HTTP, machine d'état recording.
- **Tests Linux inchangés**, marqués Linux-only.
- **Smoke suite manuelle Mac**, documentée et répétable, avec la matrice : lancement
  Terminal / bundle `.app` / LaunchAgent au login ; après update-restart ; micro
  refusé puis accordé ; Accessibilité refusée puis accordée ; nouveau chemin de venv ;
  nouvelle version de bundle ; compte utilisateur frais ou VM/snapshot.

### 10. Extras PyObjC — audités

Concédé. L'extra `[macos]` liste les frameworks PyObjC exacts utilisés
(`pyobjc-framework-Quartz` pour CGEvent ; `pyobjc-framework-Cocoa`/`AppKit` et
`AVFoundation` selon l'implémentation retenue — micro et notif natives), `rumps`, et
`quickmachotkey` **derrière la façade** (voir plus bas). On vérifie les wheels arm64
et on évite de tirer la moitié de PyObjC pour trois frameworks.

## Points où je propose une voie alternative

### A. Sécurité HTTP : ne pas ajouter de surface plutôt qu'ajouter un token

Codex a raison sur le **diagnostic** : sur macOS le serveur résident détient des
permissions TCC (Micro, Accessibilité) qu'un process local lambda n'a pas. Une route
`/api/toggle` ou une route qui déclenche un collage système devient un **proxy de
privilèges** — ce que Linux n'était pas (là, n'importe quel process pouvait appeler
`wtype` lui-même, donc le serveur n'ajoutait aucun privilège).

Mais sa solution (token 0600 / socket Unix pour les routes privilégiées) traite le
symptôme. La vraie réponse est de **ne pas créer la route privilégiée du tout** :

1. **Le hotkey n'appelle pas `/api/toggle` par HTTP.** Le handler du raccourci vit
   dans le **même processus** que le serveur (c'est tout l'intérêt du pivot
   in-process). Il appelle donc `RecordingController` **directement, par appel de
   fonction** — aucun aller-retour HTTP, aucune route réseau, zéro surface. La route
   `/api/toggle` de mon round-1 disparaît.

2. **`aparte toggle` en CLI** garde une délégation HTTP (patron
   `transcribe_via_running_app`), mais c'est un chemin déjà couvert par
   `_origin_is_ours()` + loopback, et il ne déclenche qu'un enregistrement — pas une
   insertion dans une autre app. Le repli local (sans serseur) reste le chemin CLI
   pur, comme sur Linux.

3. **La question qui reste, et je donne raison à Codex là-dessus** : faut-il exposer
   au **navigateur** une route qui exécute un collage système (`Cmd+V` dans une autre
   app) ? Sur Linux, `/api/paste` existe. Sur macOS, ce serait exactement le proxy de
   privilèges. Ma proposition : **sur macOS, le navigateur n'obtient pas d'insertion
   système.** L'UI web rend le texte transcrit dans l'éditeur (route `/api/transcribe`,
   aucun effet système), avec un bouton « Copier ». L'insertion dans l'app active est
   réservée au **hotkey** (in-process) et à la **CLI** (qui pourrait de toute façon
   appeler l'insertion elle-même). Les routes purement « retourne du texte » gardent
   le garde-fou Origin ; aucune route ne devient un proxy d'Accessibilité.

Résultat : la surface HTTP privilégiée **n'existe pas**, donc il n'y a pas de token à
gérer, à faire fuir, ni à tester. Si Codex tient à une défense en profondeur
supplémentaire, j'accepte volontiers en complément un **refus explicite des routes à
effet système quand le host effectif n'est pas loopback** (utile si quelqu'un lance
`--host 0.0.0.0`), plus un **test explicite « requête sans Origin sur une route à
effet système »**. Mais l'architecture, elle, ne crée pas le proxy en premier lieu.

### B. whisper.cpp : moteur d'optimisation, pas moteur par défaut de v1

Codex démonte à juste titre « whisper.cpp déjà codé ». J'en tire une conclusion plus
nette que « c'est du vrai travail d'intégration » : **whisper.cpp n'est pas le moteur
par défaut de la v1 macOS.**

- **Baseline v1 = faster-whisper CPU.** CTranslate2 a des wheels arm64 ; il tourne sur
  CPU macOS **sans une ligne de code de transcription nouvelle**, et il porte « Mes
  mots » (`hotwords`), les langues, tout le reste déjà testé. C'est plus lent que
  Metal, mais c'est **prouvé et gratuit en code**. C'est ça, le vrai « zéro code » —
  pas whisper.cpp.
- **whisper.cpp/Metal = lot d'optimisation séparé, chiffré comme intégration
  réelle**, pas comme acquis. Il demande : un réglage distinct pour le chemin du
  modèle ggml/gguf (Codex a raison, le champ unique `model` ne peut pas servir les
  deux moteurs) ; une doc stricte de téléchargement/placement des modèles ; une
  détection Metal/Core ML réelle ; des tests d'erreur quand `model=small` arrive à
  `whisper-cli -m small`.

Sur le schéma de config, j'adopte la séparation proposée par Codex, mais **scindée
proprement pour ne pas toucher Linux** :

- `model` : taille/nom logique, inchangé (faster-whisper, openai-whisper).
- `whisper_cpp` : chemin de l'exécutable `whisper-cli` (déjà existant, inchangé).
- **nouveau** `whisper_cpp_model` : chemin du fichier ggml/gguf. Absent ⇒
  `WhisperCppTranscriber` refuse proprement avec un message clair (aujourd'hui il
  enverrait `-m small` en silence). Ce champ entre dans `DEFAULT_CONFIG` et
  `EDITABLE_FIELDS` (invariant `CLAUDE.md`), donc il existe côté Linux aussi mais
  reste `None` par défaut : personne n'est affecté tant qu'il ne choisit pas
  whisper.cpp.

Conséquence sur le chiffrage : M-transcription (Metal) sort de « nulle en code » et
devient un lot optionnel post-v1. La **v1 macOS livrable ne dépend pas de
whisper.cpp** — elle marche en faster-whisper CPU, ce qui dérisque tout le portage.

## Points où je reformule sans contredire

### C. Serveur résident « obligatoire » : différence produit réelle, mais pas composant en plus

Codex dit, avec raison, qu'exiger le serveur pour le hotkey est un **changement
produit** (sur Linux, gsettings tire le raccourci même serveur éteint) — prérequis
utilisateur, point de diagnostic, cause de support. Je l'assume et je le documente.

Je nuance sur un seul mot : ce n'est pas un composant **supplémentaire**. Sur macOS,
le serveur résident **est** l'application — un seul processus porte le tray rumps, le
hotkey et le serveur HTTP. Sur Linux il y a deux mondes (le démon web optionnel + les
commandes CLI éphémères tirées par gsettings) précisément parce que gsettings n'a pas
de processus. Le « serveur obligatoire » macOS est donc la forme **la plus simple** (un
process au lieu de la chorégraphie fichier-de-session), pas une couche de plus. La
différence de promesse (« l'app doit tourner ») est réelle et va dans doctor + la doc ;
la charge architecturale, elle, diminue.

### D. Historique non persistant : fichier runtime 0600, pas mémoire

Codex refuse de choisir « mémoire » par réflexe, et il a raison. Je tranche pour le
**fichier runtime mode 0600** (dans `$TMPDIR`), pas la mémoire du serveur :

- il préserve `aparte last` et le partage inter-processus (la CLI n'a pas à
  interroger le serveur pour relire la dernière dictée) ;
- il ne rend pas le serveur **encore plus** central qu'il ne l'est déjà sur macOS.

Le recul de confidentialité par rapport au tmpfs systemd (fichier effacé au
redémarrage seulement, pas à la déconnexion) est documenté comme limite macOS connue,
pas masqué. `history_persist=False` garde son sens : pas d'écriture dans
`~/.local/state`, seulement le runtime éphémère.

### E. Frappe Unicode vs collage Cmd+V : Cmd+V d'abord, frappe en repli

Codex a raison, et je corrige la formulation de mon round-1. « CGEvent Unicode est la
seule route sûre » était faux : ce que j'écartais légitimement, c'était
`osascript/System Events keystroke` (disposition clavier, guillemets, apostrophe,
insécables — rédhibitoire pour le français). Mais entre `pbcopy` + `Cmd+V` (CGEvent
sur les touches Cmd+V) et la frappe Unicode directe (`CGEventKeyboardSetUnicodeString`),
c'est **Cmd+V qui est le chemin principal à durcir en premier** : pour une dictée
française longue, le collage natif arrive intact dans Slack, Mail, navigateurs,
Electron, bien mieux qu'une rafale d'événements clavier synthétiques. La frappe
Unicode directe devient le **repli/mode spécialisé**, testé sur texte long, caractères
composés, champs web et apps sandboxées.

Bonus : ça aligne macOS sur le `paste_mode="clipboard"` **déjà existant** (copie puis
colle) au lieu d'inventer un comportement mac. Le mode `terminal` Linux (frappe
directe) devient le mode « frappe Unicode » mac, secondaire.

### F. `quickmachotkey` derrière une façade testée

D'accord avec Codex, sans réserve : `quickmachotkey` (PyPI 2025.7.28, dépôt
`glyph/QuickMacHotKey`) est acceptable pour le prototype M5, mais `macos_hotkey.py`
est une **façade testée** qui expose l'`OSStatus`/l'échec de combinaison. Si la lib ne
donne pas assez de contrôle sur les conflits (combinaisons réservées, déjà prises,
changements type Sequoia sur les combinaisons Option/Shift seules), on remplace par un
petit binding ctypes/PyObjC interne sur `RegisterEventHotKey` sans changer les
appelants. Et je retire l'assurance « 0 permission » absolue : c'est vrai pour la
famille « surveillance de l'entrée », mais les combinaisons réservées/déjà prises
peuvent échouer — d'où le besoin de bons diagnostics d'échec, pas d'une promesse.

### G. Page web = palier documentaire, pas « compatibilité macOS »

D'accord. Je requalifie : la dictée navigateur (enregistrement `getUserMedia`,
transcription, polissage, copie) est un **palier documentaire** utile dès M0, **pas**
« la compatibilité macOS » au sens fort — parce que le produit, c'est l'insertion dans
l'app active sans revenir à l'interface (`PRODUCT.md:28-33`).

## Plan ajusté — état actuel

**Cadrage inchangé** : macOS compagnon, pas de pivot, code Linux intact, modules
`macos_*` + branches `sys.platform`, pas de couche `platform/base.py`, enregistrement
in-process côté serveur résident, `RegisterEventHotKey` (pas d'event tap).

**Ce qui change depuis le round-1** :

1. **Deux niveaux de TCC/signature** nommés (expérimental non signé vs distribuable
   signé), au lieu de « le bundle suffit ».
2. **`RecordingController`** : machine d'état `idle/recording/processing/error`,
   `recording_lock` séparé d'`inference_lock`, worker hors run loop, sémantique de
   conflits tranchée, provider d'état pour tray + doctor.
3. **Contrat de callback PortAudio** explicite (non-bloquant, tampon borné, stop dans
   `finally`, plafond en frames, périphérique disparu géré).
4. **Run loop AppKit unique** : rumps possède la boucle si tray présent, sinon
   NSApplication minimale ; jamais deux boucles ; HTTP en thread secondaire.
5. **Pas de route `/api/toggle`** : le hotkey appelle `RecordingController` en
   in-process. **Sur macOS, aucune route ne déclenche d'insertion système** (le
   navigateur obtient du texte + « Copier », jamais un `Cmd+V` dans une autre app).
   Défense en profondeur en complément : refus des routes à effet système hors
   loopback + test « sans Origin ».
6. **whisper.cpp retiré de v1** : baseline faster-whisper CPU (zéro code), whisper.cpp/
   Metal = lot d'optimisation post-v1 avec `whisper_cpp_model` (chemin ggml) séparé de
   `model`.
7. **Cmd+V = insertion principale** (`pbcopy` + Cmd+V), frappe Unicode CGEvent en
   repli. Aligné sur `paste_mode="clipboard"`.
8. **Historique = fichier runtime 0600** (pas mémoire), limite de confidentialité
   documentée.
9. **`update.py` macOS** : préserver `[macos]` dans `_installed_extras`, redémarrer via
   bundle/LaunchAgent (pas `os.execv` nu), `find_repo` lié à l'install bundle-sur-venv.
10. **Trois niveaux de tests** : unitaires mac mockés, Linux-only marqués, smoke suite
    manuelle Mac documentée (matrice TCC/hotkey/insertion).
11. **`quickmachotkey` derrière `macos_hotkey.py`** (façade testée, `OSStatus`
    exposé) ; « 0 permission » nuancé.
12. **Page web = palier documentaire**, pas la compatibilité au sens fort.

**Chiffrage révisé** — les lots gonflent parce qu'ils étaient sous-estimés :

| Lot | Contenu | Effort |
|---|---|---|
| M0 | Dispatch `sys.platform`, extra `[macos]`, classifieurs, **doc dictée navigateur** | 0,5 j |
| M1 | Socle trivial : `pbcopy`, notifs (natives si tray, sinon osascript), `afplay`, micros PortAudio, `record_wav` mac | 1,5–2 j |
| M2 | Diagnostics macOS (doctor + panneau) : `AVFoundation` micro (notDetermined/denied/restricted/authorized), `AXIsProcessTrustedWithOptions`, `fix` brew, textes fr/en | 1,5–2 j |
| M3 | Insertion : **Cmd+V d'abord** + frappe Unicode en repli, continuité clipboard/historique/notif, parcours Accessibilité guidé | 2–2,5 j |
| M4 | **`RecordingController`** in-process : machine d'état, `recording_lock`, callback PortAudio borné, worker, provider d'état, CLI déléguée (repli local intact) | 3–4 j |
| M5 | Raccourci global RegisterEventHotKey via `macos_hotkey.py` (façade) + **run loop AppKit unique**, install-hotkey mac, diagnostics d'échec de combinaison | 2,5–3,5 j |
| M6 | Tray rumps (menu + provider d'état + icônes PNG template) | 1–1,5 j |
| M7 | Empaquetage v1 expérimental : LaunchAgent, bundle `.app` (`CFBundleIdentifier` stable, `NSMicrophoneUsageDescription`), `install-macos.sh`, **lot `update.py` macOS**, doc | 3–4 j |
| M8 | Tests : unitaires mac mockés + Linux-only + **smoke suite manuelle documentée** | 1,5–2,5 j |
| M9 *(optionnel, post-v1)* | whisper.cpp/Metal : `whisper_cpp_model`, détection Metal, doc modèles, tests d'erreur | 2–3 j |
| M10 *(optionnel, distribuable)* | Signature/notarisation, lanceur Mach-O, vérif compte frais | selon budget Apple |

**Total v1 (M0–M8) : 17 à 23 jours de travail réel**, contre 13–18 annoncés au
round-1 — l'écart, c'est la dette que je masquais (state machine, TCC réel, whisper.cpp,
run loop). M9/M10 sont hors v1.

## Zones que j'assume toujours (sans Mac pour vérifier)

- La cohabitation exacte rumps + RegisterEventHotKey sur une seule run loop se prouve
  sur un vrai Mac (M5). Le plan la **conçoit** désormais, mais la vérification reste
  manuelle.
- La stabilité réelle de l'attribution TCC (micro, Accessibilité) à travers
  update/relance/nouveau venv ne se conclut que par la smoke suite (M8). C'est
  précisément pourquoi elle existe.
- Le comportement de `RegisterEventHotKey` sur les combinaisons réservées/récentes
  (Sequoia) se découvre à l'exécution ; d'où la façade avec diagnostics.

Je pense qu'après ces ajustements il ne reste pas de désaccord de fond. Reste à voir si
Codex estime que la voie A (pas de route privilégiée plutôt qu'un token) et la voie B
(faster-whisper CPU en v1) répondent bien à ses points 3 et 5.
