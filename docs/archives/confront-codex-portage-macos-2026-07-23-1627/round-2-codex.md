# Round 2 - Réponse Codex

## Points résolus depuis le round précédent

### TCC et identité applicative

L'ajustement de Claude correspond exactement à ma critique. Le round 1 présentait
le bundle `.app` non signé comme une quasi-garantie d'attribution TCC stable ; le
round 2 retire cette hypothèse et sépare correctement :

- une v1 expérimentale sans compte Apple, avec bundle, `CFBundleIdentifier` et
  `NSMicrophoneUsageDescription`, mais stabilité TCC explicitement fragile ;
- une version distribuable sérieuse avec lanceur Mach-O, signature et vérification
  sur compte utilisateur frais.

Je valide cette correction. Le point important n'était pas "il faut payer Apple en
v1", mais "ne pas promettre une stabilité TCC que l'architecture non signée ne
garantit pas". C'est maintenant formulé ainsi.

### RecordingController, concurrence et callback PortAudio

Claude a bien corrigé le manque principal : le pivot in-process ne peut pas être
juste une route et un `InputStream`, il lui faut une machine d'état serveur.

Les états `idle` / `recording` / `processing` / `error`, le `recording_lock`
séparé de `inference_lock`, le worker hors run loop et les règles de conflit
sont ce que j'attendais. Le contrat du callback PortAudio est aussi recadré au
bon niveau : callback court, tampon borné, pas d'I/O disque, pas de Whisper, stop
et close dans un `finally`, finalisation hors callback.

Je valide aussi le déplacement du risque WAV : l'en-tête n'est pas le vrai sujet
si l'écriture finale passe par `wave.writeframes`; le vrai sujet est la capture
temps réel, les overflows, les arrêts propres et les périphériques qui changent.

### Run loop AppKit unique

Le round 2 répond à la critique. La règle "une seule run loop AppKit sur le fil
principal" est maintenant une contrainte de conception, pas une simple zone à
valider. Le partage entre rumps, hotkey et serveur HTTP est correctement posé :
rumps possède la boucle si le tray est là, une boucle AppKit minimale existe sans
tray, et les actions hotkey partent vers un worker.

Il restera à prouver cela sur un vrai Mac, mais le plan ne masque plus cette
contrainte.

### `update.py`

Correction acceptée. Claude retire "fonctionne tel quel" et ajoute le lot macOS
nécessaire : préserver l'extra `[macos]`, redémarrer via bundle ou LaunchAgent, et
lier explicitement `find_repo()` à l'installation editable enveloppée par le
bundle. C'est le bon niveau de travail.

### `session.py` et état visible

L'inventaire des consommateurs cachés est maintenant intégré. Le provider d'état
macOS pour tray et doctor évite le piège où le serveur enregistre en mémoire
pendant que l'UI continue de lire `session.py` et affiche `idle`. C'est résolu.

### Clipboard, insertion et invariants comportementaux

Claude reprend les invariants que je voulais préserver : sortie vide sans copie,
collage ni historique ; historique avant insertion ; notification de succès après
insertion ; texte récupérable si le collage échoue. C'est bon.

Je valide aussi le changement de priorité : `pbcopy` + Cmd+V doit être le chemin
principal macOS, avec frappe Unicode CGEvent seulement en repli ou mode spécialisé.
La formulation "CGEvent Unicode est la seule route sûre" est retirée, ce qui était
nécessaire.

### Tests et CI

Le découpage est maintenant honnête : unitaires macOS mockés, tests Linux marqués
Linux-only, et smoke suite manuelle Mac pour TCC, Accessibilité, hotkey global,
LaunchAgent et insertion réelle. C'est la bonne séparation. La CI macOS ne doit
pas être vendue comme preuve de compatibilité TCC.

### Proposition B - faster-whisper CPU comme moteur par défaut v1

Je change ma position par rapport à mon round précédent. Je proposais surtout de
requalifier whisper.cpp/Metal comme travail réel ; Claude va plus loin et son
argument est meilleur : whisper.cpp/Metal ne doit pas être dans le chemin critique
de la v1 macOS.

La baseline v1 en `faster-whisper` CPU est plus sûre :

- elle réutilise le backend déjà testé par le produit ;
- elle garde `hotwords`, langues, polissage et cache serveur dans le modèle
  existant ;
- elle évite d'introduire en même temps PortAudio temps réel, TCC, AppKit,
  packaging macOS et une seconde stratégie de modèles Whisper.

Le lot whisper.cpp/Metal devient donc correctement post-v1, avec
`whisper_cpp_model` séparé de `model`, erreurs explicites si le chemin ggml/gguf
manque, doc de modèles et détection d'accélération réelle. Je valide B.

## Points encore en débat

### Proposition A - pas de route HTTP privilégiée

Sur le principe, je suis convaincu par Claude. Supprimer la surface est meilleur
qu'ajouter un token autour d'une surface qui n'a pas besoin d'exister.

Ma position actualisée :

- pas de `/api/toggle` sur macOS ;
- le hotkey résident appelle `RecordingController` directement, in-process ;
- le navigateur macOS ne peut pas déclencher de collage système, de frappe
  clavier, de capture micro serveur, de LaunchAgent, de permission fix ou
  d'update applicatif ;
- le bouton "Copier" de l'UI web doit utiliser l'API Clipboard du navigateur sous
  geste utilisateur, pas `/api/copy` côté serveur ;
- `aparte toggle` ne doit utiliser HTTP que pour une opération pure du type
  "transcrire ce fichier et retourner du texte" ; l'enregistrement, l'historique
  et l'insertion restent dans le processus appelant ou dans le hotkey résident
  par appel direct, jamais dans une route HTTP à effet système.

Ce point n'est donc pas un désaccord de fond, mais il reste une ambiguïté à lever
dans le plan final. Le dépôt expose aujourd'hui des POST à effet local comme
`/api/copy`, `/api/paste`, `/api/history` et `/api/update/apply`
(`desktop.py:294-311`). Dire "aucune route HTTP à effet système sur macOS"
implique de les classer explicitement et de désactiver au minimum les routes qui
touchent presse-papiers, clavier, update, launchd ou permissions depuis HTTP sur
Darwin.

La phrase de Claude "la CLI garde une délégation HTTP" doit aussi être resserrée :
acceptable pour `/api/transcribe` qui retourne du texte ; pas acceptable si cela
réintroduit un toggle, un paste ou une capture micro pilotés par HTTP.

### Promesse "tout local" et acquisition des modèles faster-whisper

Ce point reste non résolu. Je l'avais déjà signalé au round 1 : `faster-whisper`
peut télécharger le modèle au premier chargement si le modèle n'est pas déjà dans
le cache local. Le round 2 choisit `faster-whisper` CPU comme baseline v1, ce que
j'approuve, mais il ne tranche pas le moment et la formulation de cette acquisition.

Le plan final doit dire explicitement l'une de ces choses :

- l'install macOS précharge un modèle connu avec consentement réseau explicite ;
- le premier lancement prévient qu'un modèle local va être téléchargé avant toute
  transcription ;
- l'utilisateur fournit un modèle déjà local, et `doctor` signale clairement qu'il
  manque.

Sans cette décision, la contrainte produit "rien ne sort de la machine" reste trop
forte pour le comportement réel. Même si l'audio ne sort jamais, le réseau peut
être utilisé pour récupérer un modèle. Ce n'est pas bloquant pour choisir
`faster-whisper` CPU, mais c'est bloquant pour valider le plan "en l'état".

### Historique runtime macOS

Je suis d'accord avec le choix de Claude : fichier runtime `0600` plutôt que
mémoire serveur. Il préserve `aparte last` et évite de rendre le serveur encore
plus central.

Le seul ajustement à garder dans le plan final est documentaire et UI : sur macOS,
ce runtime n'a pas exactement la même sémantique qu'un tmpfs systemd Linux. Les
textes qui promettent disparition à la fermeture de session devront être nuancés
sur Darwin.

## Évaluation globale

Sur les deux arbitrages clés, ma position est maintenant :

- A : accepté, à condition que "pas de route HTTP à effet système" soit appliqué
  strictement et que la délégation CLI HTTP soit limitée à la transcription pure ;
- B : accepté sans réserve comme baseline v1, whisper.cpp/Metal étant un lot
  d'optimisation post-v1.

Il ne reste plus de désaccord substantiel sur l'architecture macOS : serveur
résident, hotkey in-process, `RecordingController`, AppKit run loop unique,
TCC assumé, faster-whisper CPU en v1. En revanche, le plan n'est pas prêt "en
l'état" parce que deux manques doivent encore être intégrés explicitement :

1. la frontière exacte des routes HTTP macOS à effet système, en tenant compte
   des routes existantes ;
2. la stratégie d'acquisition locale des modèles faster-whisper et la formulation
   de la promesse "tout local".

Si Claude intègre ces deux points dans le plan consolidé, je ne vois plus de
raison de continuer le débat.

CONSENSUS_REFUSE
