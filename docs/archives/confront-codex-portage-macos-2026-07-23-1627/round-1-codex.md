# Round 1 - Revue Codex du plan macOS

## Ce que j'approuve

### Garder macOS comme compagnon, pas comme pivot

Le cadrage est bon. Le produit et les invariants du dépôt disent explicitement
"Linux d'abord" (`CLAUDE.md:10`, `PRODUCT.md:54-55`), et le chemin principal
reste le raccourci global qui insère le texte dans l'application active
(`CLAUDE.md:5-8`, `PRODUCT.md:23-26`). Un port macOS doit donc s'ajouter sans
déstabiliser le code Linux existant. La proposition de nouveaux modules
`macos_*` et de branches `sys.platform` limitées dans `audio.py`,
`clipboard.py` et `notify.py` est pragmatique.

Je valide aussi le rejet d'une grande couche `platform/base.py` pour un premier
port. Les modules actuels sont petits et leurs API publiques sont étroites :
`clipboard.copy_text/paste_text`, `notify.notify`, `audio.record_wav`,
`hotkey.install_hotkey`, `tray.run`. Introduire une abstraction complète avant
d'avoir une implémentation macOS réelle créerait probablement plus de surface à
maintenir que de clarté.

### Ne pas transposer `session.py` littéralement

Le pivot "enregistrement in-process dans le serveur résident" est, à mon avis,
la bonne direction pour macOS.

`session.py` est une solution très Linux : coordination entre processus CLI
éphémères, fichier de session, `os.link()` atomique, `arecord`, `/proc/<pid>/cmdline`
pour éviter les PID recyclés, signaux vers le groupe de processus
(`session.py:80-92`, `session.py:148`, `session.py:172-184`,
`session.py:184-246`). Cette architecture existe parce que le raccourci
gsettings lance une commande sans garder de processus applicatif vivant.

Sur macOS, un raccourci global natif implique au contraire un processus résident
avec run loop. Si ce processus est déjà le serveur de bureau, enregistrer en
mémoire ou vers un tampon temporaire contrôlé par ce serveur évite de répliquer
des mécanismes qui n'ont plus leur justification : pas de `/proc`, pas de
sous-processus `arecord`, pas de fichier de verrou partagé entre instances CLI.

La contrepartie est importante : ce choix n'est bon que si le plan ajoute une
vraie machine d'état d'enregistrement côté serveur. Tel qu'écrit, le plan a la
bonne intuition, mais pas encore la spécification suffisante.

### Préférer `RegisterEventHotKey` à un event tap pour le raccourci

Le choix de départ est solide. Un event tap `CGEventTap` bascule dans le monde
des permissions d'entrée/Accessibilité et reçoit les événements depuis une run
loop, ce qui est une surface plus invasive. `RegisterEventHotKey` est plus
adapté à un raccourci global d'application : il enregistre une combinaison, ne
demande pas d'observer tout le clavier, et évite en principe la permission
"Input Monitoring".

Il faut toutefois nuancer le "0 permission" : c'est vrai pour la famille de
permission "surveillance de l'entrée", mais cela ne veut pas dire "aucun cas
limite". Les combinaisons réservées par le système, déjà prises par une autre
app, ou affectées par des changements macOS récents peuvent échouer. Apple a par
exemple documenté un changement dans macOS Sequoia autour des combinaisons ne
contenant que Option/Shift, ensuite corrigé dans 15.2 beta. Donc je valide le
choix, pas l'assurance trop absolue.

### Les primitives simples sont probablement les bonnes

`pbcopy` pour copier, `afplay` pour le bip, `sounddevice.query_devices()` pour
lister les périphériques et `sounddevice`/PortAudio pour capturer sont des choix
raisonnables pour un v1.

Le point WAV est moins inquiétant que le plan ne le formule. Dans le code actuel,
`sounddevice` ne "produit" pas le WAV : `audio.py` capture des échantillons avec
`sd.rec(..., dtype="int16")`, puis écrit le fichier avec le module standard
`wave` (`audio.py:86-97`). Le module `wave` corrige l'en-tête sur flux seekable
et `writeframes()` sait poser le nombre de frames correct. Si le nouveau toggle
macOS écrit le WAV final avec `wave.open(..., "wb")`, `setsampwidth(2)`,
`setframerate(...)`, puis `writeframes(...)`, l'hypothèse "WAV bien formé" est
solide. Le piège n'est pas l'en-tête WAV ; il est dans la capture temps réel, le
stop propre et la récupération après crash.

### Documenter la page web comme premier palier

Le plan a raison de dire que la page web locale couvre déjà une partie du besoin
sur macOS : enregistrement navigateur, transcription, polissage, copie. Mais il
faut rester précis : ce n'est pas le produit complet, parce que le produit est
l'insertion dans l'application active sans revenir à l'interface (`PRODUCT.md:28-33`,
`PRODUCT.md:59`). Je l'approuverais comme étape documentaire, pas comme
"compatibilité macOS" au sens fort.

## Ce que je désapprouve

### Le bundle `.app` non signé comme identité TCC stable

Je désapprouve nettement cette hypothèse. Un bundle `.app` avec
`NSMicrophoneUsageDescription` est nécessaire, mais pas suffisant pour promettre
une attribution TCC durable.

Apple rattache les permissions de confidentialité à l'identité du code
responsable. Les notes techniques et réponses DTS d'Apple insistent sur le fait
qu'une identité de signature stable est importante ; les binaires unsigned ou
ad-hoc, les scripts, les interpréteurs et les helpers lancés par `launchd`
peuvent provoquer des prompts répétés ou une attribution au mauvais processus.
Un `.app` minuscule non signé qui lance `python -m aparte` depuis une venv n'est
donc pas une base fiable pour "TCC stable".

Conséquence pratique : le plan doit distinguer deux niveaux.

- v1 expérimental sans compte Apple : bundle avec `Info.plist`, avertissements,
  tests manuels, attribution possiblement fragile.
- v1 distribuable sérieusement : petit lanceur Mach-O, `CFBundleIdentifier`
  stable, signature Apple Development ou Developer ID, `NSMicrophoneUsageDescription`,
  stratégie LaunchAgent avec attribution au bundle, et vérification sur compte
  utilisateur frais.

Sans cela, le risque n'est pas cosmétique : l'utilisateur peut accorder le micro
à Terminal, Python, un ancien chemin de venv, ou un helper launchd, puis perdre
la permission après mise à jour ou relance.

### "`update.py` fonctionne tel quel"

C'est faux.

`update.py` est POSIX, mais il encode des hypothèses d'installation courante. Il
reconstruit les extras installés avec `_installed_extras()`, qui ne connaît que
`whisper`, `recording` et `cuda` (`update.py:152-164`). Un extra `[macos]` serait
perdu lors d'un update. Le redémarrage fait `os.execv(sys.executable, argv)` en
fonction de `sys.argv` (`update.py:234-245`) : dans un bundle macOS, cela risque
de relancer l'interpréteur ou le module, pas l'application responsable vue par
TCC. Enfin, le modèle actuel `find_repo()` suppose un checkout editable
(`update.py:40-95`), ce qui peut rester acceptable, mais doit être explicitement
lié à la stratégie d'installation macOS.

Il faut un lot macOS dans `update.py` : préserver `[macos]`, redémarrer via le
bundle ou le LaunchAgent, et vérifier que l'identité TCC ne change pas après
update.

### "whisper.cpp/Metal déjà codé, zéro code"

Là aussi, le plan surestime l'existant. `WhisperCppTranscriber` existe, mais il
appelle `whisper-cli -m self.model -f audio.wav -nt` (`transcription.py:160-173`).
Or la configuration actuelle expose des noms de modèles comme `small`, `base` ou
`medium`, alors que whisper.cpp attend normalement un chemin de fichier ggml/gguf
du type `models/ggml-base.bin`. Le champ `whisper_cpp` ne représente que le
chemin de l'exécutable (`config.py:44`, `transcription.py:198-214`), pas le chemin
du modèle.

Donc "whisper.cpp est déjà codé" n'est vrai qu'au sens minimal : il existe un
wrapper CLI non prouvé. Il manque au moins :

- un réglage séparé pour le chemin du modèle whisper.cpp ;
- une logique de téléchargement/conversion ou une documentation stricte ;
- une détection Metal/Core ML réelle ;
- des tests d'erreur quand `model=small` est envoyé à `whisper-cli -m small`.

Le plan peut garder whisper.cpp comme objectif macOS, mais il ne doit pas le
chiffrer à "nulle en code".

### `/api/toggle` sans nouveau modèle de sécurité

Le plan réutilise le modèle de délégation HTTP existant sans assez le challenger.
Aujourd'hui, le serveur accepte les POST sans `Origin` parce que `CLAUDE.md`
raisonne ainsi : une requête sans `Origin` vient de `curl` ou d'un processus
local, qui pourrait déjà appeler `wtype` lui-même (`CLAUDE.md:252-258`). Le code
applique cette logique dans `_guard_post_origin()` (`desktop.py:326-344`) et les
routes `/api/transcribe`, `/api/paste`, `/api/copy`, `/api/update/apply` sont
accessibles derrière ce garde-fou (`desktop.py:291-310`). Si l'utilisateur lance
le serveur avec `--host 0.0.0.0`, le contrôle de hostname est même explicitement
relâché (`desktop.py:340-342`).

Sur macOS, ce raisonnement ne tient plus. Le serveur résident détiendra des
permissions TCC que n'importe quel processus local n'a pas : Microphone,
Accessibilité, peut-être notifications. Une route `/api/toggle` ou `/api/paste`
devient alors un proxy de privilèges locaux. Elle doit être protégée par autre
chose qu'un contrôle d'Origin navigateur :

- écoute loopback stricte pour les routes privilégiées ;
- token local mode 0600, ou IPC par socket Unix avec permissions de fichier ;
- refus des routes TCC si le host effectif n'est pas loopback ;
- tests explicites pour requêtes sans `Origin`.

Sans ce durcissement, le port macOS crée une surface que Linux n'avait pas au
même niveau.

### "CGEvent Unicode est la seule route sûre"

Je désapprouve la formulation. Écarter `osascript/System Events keystroke` est
raisonnable pour du français riche : disposition clavier, guillemets, apostrophe
typographique et espaces insécables sont effectivement des pièges. Mais conclure
que `CGEventKeyboardSetUnicodeString` est "la seule route sûre" est trop fort.

Pour une dictée française longue, la voie la plus fiable reste probablement :
écrire le texte dans le presse-papiers natif, simuler Cmd+V, et garder la frappe
directe Unicode comme fallback ou mode spécialisé. Beaucoup d'apps macOS traitent
le collage beaucoup mieux qu'une rafale d'événements clavier synthétiques. La
frappe directe doit être testée avec texte long, caractères composés, champs web,
Slack, Mail, éditeurs Electron et apps sandboxées.

### Les "surfaces triviales" ne sont pas toutes triviales

`pbcopy` et `afplay` sont simples. Le reste l'est moins que le tableau ne le dit.

- Notifications via `osascript display notification` risquent d'être attribuées
  à Script Editor, Terminal ou osascript, pas à Aparté. Si le tray rumps/PyObjC
  existe, il faut probablement une notification native attribuée au bundle.
- LaunchAgent + `launchctl bootstrap` n'est pas trivial si l'on veut conserver
  l'identité TCC du bundle responsable.
- `sounddevice.query_devices()` est simple, mais la sérialisation de
  `microphone` ne l'est pas : le champ actuel stocke des noms ALSA `plughw` issus
  de `arecord -L` (`audio.py:23-33`, `config.py:38`, `config.py:112`). Les IDs
  PortAudio macOS ne doivent pas être confondus avec ces valeurs.

## Ce qui manque

### Une machine d'état serveur pour le toggle macOS

Le plan doit spécifier un objet d'enregistrement macOS, pas seulement une route
`/api/toggle`.

Je m'attendrais à un état explicite :

- `idle` ;
- `recording` avec stream actif, start time, compteur frames, tampon, statut
  PortAudio ;
- `processing` pendant finalisation WAV, transcription, polissage et insertion ;
- `error` observable par tray/doctor/UI.

Ce state machine doit avoir un `recording_lock` séparé de `inference_lock`.
`inference_lock` sérialise déjà les transcriptions du serveur (`desktop.py:192`,
`desktop.py:359-377`) et protège `transcriber_cache` (`desktop.py:184-227`). Le
toggle macOS ne doit pas bloquer la preview navigateur par accident, ni permettre
deux enregistrements concurrents, ni démarrer un nouvel enregistrement pendant
qu'un arrêt précédent est encore en train de transcrire. Le handler du raccourci
doit probablement déclencher un worker et retourner vite, pas faire la
transcription sur la run loop.

Il faut aussi décider la sémantique des conflits :

- appui hotkey pendant `processing` : ignoré, notification "déjà en cours", ou
  mise en file ?
- POST `/api/transcribe?preview=1` pendant arrêt de dictée : réponse `busy` comme
  aujourd'hui ou priorité au toggle ?
- double appui très rapide : debounce côté hotkey ou état idempotent ?
- fermeture du serveur pendant recording : discard ou tentative de finalisation ?

### Les contraintes du callback PortAudio/sounddevice

Le plan parle de `sounddevice.InputStream` "en mémoire", mais ne détaille pas le
modèle temps réel.

Le callback PortAudio ne doit pas bloquer, faire d'I/O disque, appeler le moteur
Whisper, allouer massivement, prendre des verrous longs ou lever une exception
que l'application espère récupérer normalement. Les exceptions de callback ne
remontent pas comme une exception Python classique au thread appelant. Il faut
copier les frames rapidement vers une queue ou un tampon borné, capturer les
statuts overflow/underflow, puis finaliser hors callback.

L'arrêt propre doit être explicite : `stream.stop()`/`stream.close()` dans un
`finally`, limite `max_recording_seconds` par nombre de frames, et nettoyage si
le périphérique disparaît. Le code actuel `audio._record_wav_sounddevice()` est
simple parce qu'il capture une durée fixe avec `sd.rec()` (`audio.py:76-97`) ;
il ne prouve pas encore que le toggle temps réel sera robuste.

### Un runner macOS avec une seule run loop AppKit

Le point run loop n'est pas seulement "à valider", il doit être conçu.

Aujourd'hui, Linux fait : serveur HTTP `ThreadingHTTPServer` en arrière-plan,
GTK/AppIndicator sur le fil principal si le tray est disponible (`desktop.py:67-88`,
`tray.py:156`). Sur macOS, rumps possède sa propre `App.run()` qui démarre la run
loop AppKit. `quickmachotkey`, d'après ses exemples, s'attache aussi à une run
loop AppKit/PyObjC.

La règle à imposer : une seule run loop AppKit sur le fil principal. Si rumps est
présent, rumps doit probablement posséder cette run loop et le hotkey doit être
enregistré avant ou pendant son initialisation. Il ne faut pas appeler à la fois
`rumps.App.run()` et `PyObjCTools.AppHelper.runEventLoop()` comme deux boucles
indépendantes. Si le tray est désactivé ou indisponible, il faut quand même une
run loop AppKit/CF pour le hotkey ; donc le runner macOS ne peut pas simplement
copier la branche Linux "pas de tray => serveur sur le fil principal".

Le serveur HTTP peut rester sur un thread secondaire. Les actions de hotkey
doivent ensuite passer à un worker ou poster vers le serveur interne ; elles ne
doivent pas bloquer la run loop AppKit pendant la transcription.

### TCC : onboarding, diagnostics et tests de régression

Il manque un vrai plan TCC.

Pour le micro, il faut `NSMicrophoneUsageDescription` dans `Info.plist`, un appel
d'autorisation ou une première capture contrôlée, et un diagnostic qui distingue
`notDetermined`, `denied`, `restricted` et `authorized` via AVFoundation quand
possible. Pour l'Accessibilité, il faut `AXIsProcessTrustedWithOptions` et une
expérience qui explique la relance nécessaire après accord.

Surtout, les tests depuis Terminal ne suffisent pas. Il faut une matrice manuelle
sur Mac récent :

- lancement depuis Terminal ;
- lancement depuis le bundle `.app` ;
- lancement au login via LaunchAgent ;
- après update/restart ;
- permission micro refusée puis accordée ;
- Accessibilité refusée puis accordée ;
- nouveau chemin de venv ;
- nouvelle version du bundle ;
- utilisateur macOS frais ou VM/snapshot.

Sans cette matrice, le plan ne peut pas conclure sur la stabilité réelle des
permissions.

### Les consommateurs cachés de `session.py`

Dire "`session.py` reste Linux" est acceptable, mais il faut inventorier les
consommateurs. `cli.py` importe directement `get_active_session`,
`start_toggle_recording` et `stop_toggle_recording` (`cli.py:28`,
`cli.py:336-366`). `tray.py` sonde aussi l'état d'enregistrement Linux via
`get_active_session()` (`tray.py:128`). `diagnostics.py` dépend de `hotkey_info`
et du modèle Linux. `history.py` suppose un runtime dir partagé par processus et
souvent tmpfs (`history.py:1-10`, `history.py:28-34`).

Le port macOS doit donc fournir un provider d'état pour le tray et doctor, pas
seulement une route toggle. Sinon l'UI dira "idle" pendant qu'un enregistrement
macOS tourne en mémoire.

### Le parcours collage/presse-papiers

Le code actuel copie avant de coller dans tous les modes (`clipboard.py:13-18`,
`clipboard.py:40-66`) et les invariants interdisent de toucher au presse-papiers
si la sortie est vide (`CLAUDE.md:134-140`, `cli.py:361-366`). Le port macOS doit
préserver exactement ces garanties :

- sortie vide : ni copie, ni collage, ni historique ;
- historique avant insertion, comme aujourd'hui (`cli.py:290-293`) ;
- notification de succès après insertion ;
- échec de collage : texte récupérable dans l'historique ou le clipboard selon
  le mode.

Le plan ne décrit pas assez cette continuité comportementale.

### Tests et CI

Le lot CI est nécessaire mais insuffisant s'il se limite à "runner macOS". GitHub
Actions ne validera pas correctement les prompts TCC, l'Accessibilité, le
raccourci global système, le LaunchAgent au login, ni le collage dans de vraies
apps. Il faut séparer :

- tests unitaires macOS mockés : dispatch plateforme, génération plist/bundle,
  parsing périphériques, garde-fous HTTP, state machine recording ;
- tests Linux inchangés et marqués Linux-only ;
- smoke suite manuelle Mac, documentée et répétable.

### Dépendances et packaging Python

Il manque un audit d'extras. L'extra `[macos]` devrait probablement inclure les
morceaux PyObjC exacts utilisés (`pyobjc-framework-Quartz`, possiblement
`pyobjc-framework-Cocoa`/`AppKit`/`AVFoundation` selon l'implémentation), `rumps`,
et peut-être `quickmachotkey`. Il faut vérifier les wheels arm64 et éviter une
installation qui télécharge la moitié de PyObjC inutilement si seules quelques
frameworks sont nécessaires.

Il faut aussi clarifier la promesse "tout local" : comme noté dans l'audit
précédent du dépôt, `faster-whisper` peut télécharger un modèle au premier
chargement si le modèle n'est pas déjà local. Sur macOS, si l'installation ajoute
whisper.cpp, il faut dire clairement quels modèles sont installés, où, et à quel
moment le réseau est utilisé.

## Ce que je remettrais en question

### `quickmachotkey` : dépendance acceptable, mais pas à avaler sans wrapper

La dépendance existe réellement et semble récente : PyPI affiche une version
2025.7.28, et le dépôt `glyph/QuickMacHotKey` est petit. Je ne la rejetterais pas
par réflexe.

Je la remettrais pourtant en question pour deux raisons. D'abord, sa surface est
minuscule et le code qu'elle remplace n'est pas énorme : un wrapper interne
ctypes/PyObjC autour de `RegisterEventHotKey` peut offrir de meilleurs messages
d'erreur et exposer l'`OSStatus` quand une combinaison échoue. Ensuite, le projet
dit lui-même envelopper des APIs macOS peu documentées ; dans ce cas, masquer les
erreurs derrière une dépendance obscure peut compliquer le support.

Ma position : essayer `quickmachotkey` pour le prototype M5, mais construire
`macos_hotkey.py` comme une façade testée. Si la lib ne donne pas assez de
contrôle sur les conflits, remplacer par un petit binding interne. Carbon est
déprécié depuis longtemps, mais `RegisterEventHotKey` survit encore sur macOS
récent ; le vrai risque v1 est moins sa disparition immédiate que les restrictions
de combinaisons et les diagnostics d'échec.

### Direct typing vs collage Cmd+V en v1

Je remettrais en question la priorité donnée à la frappe Unicode directe. Pour
Aparté, le texte peut être long, typographié et destiné à des apps variées. Le
collage natif via presse-papiers + Cmd+V est probablement le chemin principal à
durcir en premier. La frappe directe devrait venir ensuite, avec limites
documentées, chunking éventuel et tests sur caractères français.

Ce n'est pas un débat esthétique : la fiabilité perçue du produit dépend plus du
texte qui arrive intact dans Slack/Mail/navigateur que du fait d'éviter le
presse-papiers pendant quelques millisecondes.

### Historique non persistant sur macOS

Le plan remarque à juste titre que `$TMPDIR` macOS n'est pas le tmpfs systemd
attendu par `history.py`. Deux options méritent débat :

- garder un fichier runtime mode 0600 pour préserver `aparte last` et le partage
  inter-processus ;
- passer l'historique non persistant en mémoire du serveur sur macOS, plus fidèle
  à la promesse de confidentialité, mais qui impose que la CLI interroge le
  serveur pour `last`.

Je ne choisirais pas automatiquement l'option mémoire : elle améliore la
confidentialité, mais elle rend le serveur encore plus central sur macOS.

### Le serveur résident obligatoire

Je pense que c'est probablement le bon choix, mais il faut l'assumer comme
changement produit. Sur Linux, le raccourci peut fonctionner même si le serveur
web n'est pas lancé. Sur macOS, le plan rend le daemon de bureau obligatoire pour
le raccourci et le toggle. Ce n'est pas un détail technique ; c'est un prérequis
utilisateur, un point de diagnostic et une cause de support.

### Garder un seul champ `model`

Le plan devrait remettre en question le modèle de configuration transcription.
`model=small` convient à faster-whisper/openai-whisper, mais pas à whisper.cpp si
`-m` attend un chemin de fichier. Pour macOS, je préférerais séparer clairement :

- `model` : taille/nom logique pour faster-whisper ;
- `whisper_cpp_executable` : chemin de `whisper-cli` ;
- `whisper_cpp_model_path` : chemin du modèle ggml/gguf ;
- éventuellement `whisper_cpp_acceleration` : auto/metal/coreml, si mesurable.

## Conclusion

Le plan est bon dans sa direction générale : ne pas pivoter le produit, garder
Linux stable, ajouter des modules macOS ciblés, utiliser un processus résident,
éviter l'event tap pour le raccourci global. Je ne le validerais toutefois pas
comme plan d'exécution complet.

Les corrections indispensables avant feu vert sont :

1. remplacer l'hypothèse "bundle `.app` non signé = TCC stable" par une stratégie
   d'identité/signature/test réelle ;
2. ajouter une machine d'état d'enregistrement macOS et son modèle de concurrence
   avec `inference_lock` ;
3. durcir les routes HTTP privilégiées macOS avec token ou IPC local ;
4. retirer "`update.py` fonctionne tel quel" et planifier le redémarrage/update
   via bundle/LaunchAgent ;
5. requalifier whisper.cpp/Metal comme travail d'intégration réel, pas comme code
   déjà terminé ;
6. définir une architecture run loop unique AppKit/rumps/hotkey ;
7. documenter une smoke suite Mac réelle, car la CI ne couvrira pas TCC, le hotkey
   global ni l'insertion dans les apps.

Avec ces amendements, je donnerais un feu vert pour un prototype M0-M2 puis une
preuve M3-M5 sur vrai Mac. Sans eux, le plan risque surtout d'échouer sur les
permissions, le redémarrage, la concurrence serveur et les cas d'insertion réels,
c'est-à-dire précisément les surfaces que Claude reconnaît ne pas pouvoir
vérifier.

## Sources externes consultées

- Apple Developer Forums, `RegisterEventHotKey` et macOS Sequoia :
  https://developer.apple.com/forums/thread/763878
- Apple Developer Forums, TCC, code signing et "responsible code" :
  https://developer.apple.com/forums/thread/678819
- Apple, autorisation microphone macOS et `NSMicrophoneUsageDescription` :
  https://developer.apple.com/documentation/bundleresources/requesting-authorization-for-media-capture-on-macos
- Apple, `CGEventTapCreate` et permission Accessibilité/Input Monitoring :
  https://developer.apple.com/documentation/coregraphics/cgevent/tapcreate%28tap%3Aplace%3Aoptions%3Aeventsofinterest%3Acallback%3Auserinfo%3A%29
- Python `wave`, correction d'en-tête sur flux seekable :
  https://docs.python.org/3.10/library/wave.html
- python-sounddevice, contraintes de callback PortAudio :
  https://python-sounddevice.readthedocs.io/en/0.5.3/api/streams.html
- rumps, `App.run()` et run loop d'application :
  https://rumps.readthedocs.io/en/latest/App.html
- quickmachotkey sur PyPI :
  https://pypi.org/project/quickmachotkey/
- quickmachotkey sur GitHub :
  https://github.com/glyph/QuickMacHotKey
- whisper.cpp, modèles attendus par `whisper-cli -m` :
  https://github.com/ggml-org/whisper.cpp/blob/master/models/README.md
