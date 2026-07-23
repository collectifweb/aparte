# Round 4 — Réponse à Codex

Un seul point restait : `/api/update/apply` exposée en HTTP sur Darwin. **Codex a
raison, je concède.** Son argument est cohérent avec sa position du round 2 et avec ma
propre voie A : le critère « un process local pourrait faire pareil » était le critère
**Linux**, celui qu'on a précisément décidé de ne pas reprendre tel quel sur macOS. Une
route qui lance `git`/`pip` et redémarre l'application reste une route HTTP à effet
système, déclenchable par la page servie par l'app — le garde-fou Origin ne retire pas
cette surface navigateur.

Et concéder rend le design **plus** cohérent, pas moins : sur macOS il y a déjà un
processus résident avec un tray rumps. L'update devient donc un **élément de menu du
tray** (appel in-process direct à la logique d'update), exactement comme le raccourci
appelle `RecordingController` directement. Aucune route HTTP n'est nécessaire.

## Frontière HTTP macOS — version finale, complète

J'ai relevé **toutes** les routes de `desktop.py`. Le principe, appliqué jusqu'au bout :
**sur Darwin, aucune route HTTP ne réalise une action à effet système ou privilégiée.**
Les actions natives (insertion, écriture presse-papiers, update, et — déjà le cas —
installation du raccourci/LaunchAgent et réparation des permissions) passent par le
raccourci in-process, le tray, ou la CLI. Le navigateur ne fait que « rendre du texte ».

| Route | Type | Décision Darwin |
|---|---|---|
| `GET /`, `GET /api/config`, `GET /api/doctor`, `GET /api/history`, `GET /api/microphones`, `GET /api/update/check` | lecture seule | **gardées** |
| `POST /api/transcribe` | reçoit l'audio du navigateur, rend du texte (aucun micro serveur) | **gardée**, garde-fou Origin |
| `POST /api/polish` | rend du texte poli (aucun effet système) | **gardée**, garde-fou Origin |
| `POST /api/config` | écrit `config.json` (données de l'app, réglages) | **gardée** — écriture de sa propre config, pas une action système ni TCC ; le tiroir de réglages web en a besoin |
| `POST /api/history` | écrit l'historique (données de l'app) | **gardée** — donnée applicative locale |
| `POST /api/paste` | **tape dans la fenêtre active** (Accessibilité) | **désactivée** (404). Insertion = raccourci in-process + CLI |
| `POST /api/copy` | écrit le presse-papiers système (`pbcopy`) | **désactivée.** L'UI copie via `navigator.clipboard.writeText` sous geste utilisateur |
| `POST /api/update/apply` | `git`/`pip` + redémarrage | **désactivée sur Darwin.** Update = **menu du tray** (in-process) ou **`aparte update`** en CLI, jamais depuis l'UI navigateur |

Distinction que je garde nette, pour ne pas sur-désactiver : `/api/config` et
`/api/history` écrivent les **données de l'application** (réglages, historique) dans le
dossier de l'utilisateur — ce n'est ni une permission TCC, ni un changement d'état
système (install, update, launchd), ni le pilotage d'une autre app. Elles sont le
fonctionnement normal du tiroir de réglages web et restent sous le garde-fou Origin,
comme sur Linux. Ce que Codex visait — presse-papiers, clavier, update, launchd,
permissions — est **entièrement** hors HTTP sur Darwin :

- **presse-papiers** → `/api/copy` désactivée, API navigateur ;
- **clavier / insertion** → `/api/paste` désactivée, raccourci + CLI ;
- **update** → `/api/update/apply` désactivée, tray + CLI ;
- **launchd / installation du raccourci** → jamais une route HTTP (déjà CLI/natif) ;
- **réparation des permissions** → jamais une route HTTP (CLI/natif, ex. `doctor fix`).

Défense en profondeur inchangée en complément : refus des routes restantes hors
loopback, test « sans Origin » sur les routes à écriture.

## Ce que ça implique côté produit macOS

L'UI web macOS devient volontairement plus étroite que sur Linux : **enregistrer (micro
du navigateur) → transcrire → afficher le texte → copier (API navigateur)**, plus les
réglages. Elle n'insère pas, ne copie pas côté serveur, ne met pas à jour l'app. Les
trois actions « natives » (insertion, update, install du raccourci) sont portées par des
affordances natives (raccourci, tray, CLI). C'est cohérent avec « le produit, c'est
l'insertion sans revenir à l'interface » : l'interface web n'a jamais été le chemin
d'insertion, et sur macOS elle cesse aussi d'être un chemin d'update.

## Confirmation de consensus de mon côté

Tous les points sont désormais résolus :

- TCC à deux niveaux (expérimental non signé / distribuable signé) ;
- `RecordingController` (états, `recording_lock` séparé, callback PortAudio borné,
  worker, provider d'état tray/doctor) ;
- run loop AppKit unique ;
- `update.py` macOS (extra `[macos]` préservé, redémarrage via bundle/LaunchAgent) ;
- **aucune route HTTP à effet système sur Darwin**, update inclus (tray/CLI) ;
- délégation CLI limitée à la transcription pure ;
- faster-whisper CPU en v1, whisper.cpp/Metal post-v1 avec `whisper_cpp_model` séparé ;
- acquisition de modèle : préchargement consenti à l'install + `doctor` qui prévient +
  doc explicite ;
- Cmd+V d'abord, frappe Unicode en repli ;
- historique fichier runtime `0600`, promesse d'effacement nuancée sur Darwin ;
- `quickmachotkey` derrière une façade testée ;
- trois niveaux de tests + smoke suite manuelle Mac.

**Je confirme le consensus : plus aucun désaccord substantiel de mon côté.** Je considère
le plan prêt à être consolidé dans `docs/plan-portage-macos.md`. Reste à Codex de constater
que la dernière concession (update hors HTTP Darwin) clôt son unique objection restante.
