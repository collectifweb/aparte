# Round 3 — Réponse à Codex

Codex a validé les deux voies alternatives (A : pas de route privilégiée ; B :
faster-whisper CPU en v1) et toute l'architecture. Son `CONSENSUS_REFUSE` ne porte
plus sur un désaccord : il demande d'**intégrer explicitement** deux précisions dans le
plan final. Je le fais ici, avec les faits du code vérifiés, et rien d'autre ne reste
ouvert de mon côté.

## Point 1 — Frontière exacte des routes HTTP à effet système sur macOS

J'ai relevé les routes réelles dans `desktop.py`. Le critère de classement est celui de
la voie A : **une route est un « proxy de privilèges » seulement si elle fait faire au
serveur quelque chose que l'appelant ne pourrait pas faire lui-même** — c'est-à-dire si
elle utilise une permission TCC (micro, Accessibilité) que le serveur résident détient
et qu'un navigateur ou un process local lambda n'a pas.

### Classement des routes existantes sur Darwin

| Route | Effet | TCC requis ? | Décision macOS |
|---|---|---|---|
| `POST /api/transcribe` | reçoit l'audio du navigateur, rend du texte | **non** (le micro est celui du navigateur, pas du serveur) | **gardée**, garde-fou Origin inchangé |
| `POST /api/paste` | **tape le texte dans la fenêtre active** | **oui — Accessibilité** | **désactivée sur Darwin** (404). L'insertion système n'existe que par le raccourci in-process et la CLI |
| `POST /api/copy` | écrit le presse-papiers système (`pbcopy`) | non, mais le navigateur sait le faire lui-même | **désactivée sur Darwin.** L'UI web copie via `navigator.clipboard.writeText` sous geste utilisateur |
| `POST /api/history` | ajoute/efface l'historique (fichier local) | non | **gardée** (opération fichier locale, aucun privilège TCC) |
| `POST /api/config` | écrit `config.json` + vide le cache transcripteur | non | **gardée** |
| `POST /api/update/apply` | `git merge --ff-only` + `pip install` + redémarrage | non (un process local peut lancer git/pip) | **gardée**, mais redémarrage via bundle/LaunchAgent (lot `update.py` macOS), pas `os.execv` nu |
| `GET /api/config`, `/api/history`, `/api/update/check` | lecture seule | non | gardées |

**Le seul vrai proxy de privilèges est `/api/paste`** (Accessibilité), et il est
désactivé sur Darwin. `/api/copy` n'est pas un privilège que le navigateur n'a pas, mais
on le neutralise quand même et on route la copie par l'API navigateur : c'est plus propre
et ça retire une route à effet système de plus. Les autres (`transcribe`, `config`,
`history`, `update`) n'utilisent aucune permission TCC — un process local pourrait faire
la même chose lui-même —, donc elles restent exactement sous le garde-fou Origin
d'aujourd'hui, comme sur Linux. On n'introduit **aucun** nouveau proxy de privilèges.

Il n'existe pas — et il n'existera pas — de route qui fait **capturer le micro par le
serveur** : c'est précisément la route `/api/toggle` que la voie A supprime. Le micro
serveur n'est ouvert que par le raccourci in-process (appel direct au
`RecordingController`), jamais par HTTP.

### Défense en profondeur (en complément, pas en remplacement)

- Les routes à effet système restantes (`config`, `history`, `update/apply`) **refusent
  si le host effectif n'est pas loopback** — utile si quelqu'un lance `--host 0.0.0.0`,
  où `_origin_is_ours()` relâche déjà le contrôle de hostname.
- Un **test explicite** « requête sans `Origin` sur une route à effet système » verrouille
  le comportement.

### Délégation CLI resserrée

Codex a raison, je resserre. Sur macOS :

- Le **raccourci natif** (chemin principal) : résident, appel direct au
  `RecordingController`. Aucun HTTP.
- **`aparte dictate`** (CLI, une passe) : enregistre **dans le processus appelant**,
  transcrit, insère — le tout en un seul processus, sans HTTP ni fichier de session.
  Marche si ce processus a les permissions TCC (documenté : recommandé via le bundle).
- **La bascule à deux appuis** (toggle) est fournie **uniquement par le raccourci natif**
  in-process. On ne réplique pas sur macOS la chorégraphie `session.py` (fichier de
  session + `/proc`) pour coordonner deux invocations CLI : le raccourci natif la remplace.
- La **seule** délégation HTTP de la CLI est `transcribe_via_running_app()` : « transcris
  cet audio, rends du texte » — opération pure, aucun effet système, exactement ce que
  Codex autorise. L'enregistrement, l'historique et l'insertion ne passent **jamais** par
  une route HTTP à effet système.

## Point 2 — Acquisition des modèles faster-whisper vs « tout local »

Fait vérifié : `transcription.py` appelle `WhisperModel(self.model_name, …)`
(`transcription.py:95-112`) **sans** `local_files_only` ni `download_root`. faster-whisper
récupère donc le modèle depuis HuggingFace **au premier usage** si le cache local est
vide. `install.sh` ne précharge aucun modèle. **Ce comportement est déjà celui de Linux**
— ce n'est pas une régression macOS ; le plan doit simplement l'énoncer honnêtement.

La promesse « rien ne sort de la machine » porte sur **l'audio et le contenu dicté** :
ça, ça ne sort jamais. Le téléchargement **unique** d'un modèle, lui, utilise le réseau
une fois. Je tranche pour la combinaison la plus honnête et la moins intrusive, sans
toucher au cœur multiplateforme :

1. **`install-macos.sh` propose le préchargement du modèle par défaut, avec consentement
   réseau explicite** (invite « Télécharger le modèle *small* maintenant ? [O/n] »). Si
   l'utilisateur accepte, la première transcription est hors-ligne. S'il refuse, l'install
   n'appelle pas le réseau.
2. **`doctor` signale l'état du modèle** : présent en cache local → « prêt, hors-ligne » ;
   absent → « la première transcription téléchargera le modèle *X* depuis HuggingFace ».
3. **La documentation le dit explicitement** : l'audio et le texte ne quittent jamais la
   machine ; un téléchargement réseau **unique** du modèle a lieu au premier usage sauf
   préchargement ; ensuite, tout est hors-ligne.

Je ne modifie pas l'appel `WhisperModel` du cœur (ça toucherait Linux) : le point de
contrôle est l'**install** (préchargement consenti) et le **diagnostic** (`doctor` qui
prévient), pas une réécriture du chemin de transcription. La promesse reste vraie et
n'est plus surestimée. Optionnel, hors v1 : pointer `download_root` vers un cache dédié
si on veut un emplacement déterministe pour `doctor`.

## Historique runtime macOS — précision documentaire retenue

Codex est d'accord sur le fichier runtime `0600` plutôt que la mémoire. Je retiens sa
seule demande : sur macOS, `$TMPDIR` n'a pas la sémantique d'un tmpfs systemd. Les textes
qui promettent une disparition « à la fermeture de session » sont **nuancés sur Darwin**
(effacement au redémarrage/nettoyage système, pas garanti à la déconnexion). C'est une
correction de libellé fr/en, pas de comportement.

## État du débat de mon côté

Les deux manques que Codex exigeait sont intégrés :

1. Frontière des routes HTTP macOS : **classée route par route**, seul `/api/paste` est un
   proxy de privilèges et il est désactivé, `/api/copy` neutralisé au profit de l'API
   navigateur, le reste inchangé sous garde-fou Origin, délégation CLI limitée à la
   transcription pure. Défense en profondeur ajoutée (refus hors loopback + test sans
   Origin).
2. Acquisition des modèles : **tranchée** — préchargement consenti à l'install, `doctor`
   qui prévient, doc explicite ; la promesse « tout local » requalifiée (audio/texte
   jamais, modèle une fois au premier usage).

Je ne vois plus aucun désaccord de fond ni aucun manque de mon côté. **Je confirme le
consensus sous réserve que Codex constate que ces deux intégrations répondent bien à ses
deux demandes.** Si c'est le cas, je produis le plan consolidé `docs/plan-portage-macos.md`.
