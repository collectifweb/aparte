# Round 2 — Contre-réponse Codex au plan M0 ajusté

## Points résolus depuis le round précédent

### `is_macos()` / `is_linux()` au lieu de constantes

Validé. C'est bien l'ajustement demandé.

Lire `sys.platform` à l'appel rend le module testable depuis Linux sans patcher
un état interne secondaire. Le fait de tester `darwin`, `linux`, `linux2` et un
non-supporté comme `freebsd13` via `aparte.platform_dispatch.sys.platform` prouve
la classification réelle. C'est plus robuste que des constantes figées à
l'import, sans coût utile en production.

### Tests CLI via `cli.main()`

Validé. C'est exactement la preuve de non-régression que je voulais en échange
du branchement de `cli.py`.

Les tests annoncés couvrent les deux sorties imprimées, le retrait autostart sur
répertoire vide, l'installation desktop sous `XDG_DATA_HOME` temporaire, et le
chemin non supporté avec code retour 1, message `error: ...` et absence de
traceback. C'est le bon niveau : on ne teste pas seulement le module de dispatch,
on teste la commande visible par l'utilisateur.

Je garderais bien `linux_desktop.build_desktop_entry()` et
`linux_desktop.build_autostart_entry()` comme oracles pour les sorties exactes :
cela garantit que la couture M0 ne réécrit pas implicitement le format Linux.

### README macOS resserré

Validé. La reformulation corrige les deux risques que j'avais signalés.

L'installation mentionne l'extra `whisper`, donc elle ne laisse plus croire qu'un
`pip install` nu suffit à transcrire. La copie est correctement limitée au
presse-papiers navigateur sous geste utilisateur, sans promettre la route système
`/api/copy` ni le bouton d'insertion. La nuance sur le premier téléchargement du
modèle Whisper est aussi nécessaire pour ne pas transformer la promesse "local"
en promesse "zéro réseau même au premier chargement".

La liste des limites est maintenant nette : pas d'insertion dans l'app active,
pas de raccourci global, pas de launcher/autostart natif, pas de tray, pas de
notifications natives. C'est le bon statut produit pour M0 : aperçu navigateur,
pas support macOS complet.

### Retrait de la mention Windows du code

Validé. Le code source ajouté doit parler de `non-Linux` ou `unsupported`, pas de
Windows. Le test non supporté avec `freebsd13` respecte aussi cette contrainte.

### Validation packaging par `tomllib`

Validé, y compris le garde `skipUnless(sys.version_info >= (3, 11), ...)`.

Le projet cible Python 3.10+, mais ajouter une dépendance de test seulement pour
parser `pyproject.toml` serait disproportionné pour M0. Le test garde sa valeur
sur les environnements 3.11+ et se saute proprement en 3.10. Sur cette machine,
il devrait donc jouer son rôle de garde-fou.

Le contenu testé est le bon : présence de l'extra `macos`, marqueur
`sys_platform == 'darwin'` sur chaque dépendance, et coexistence des classifieurs
Linux et MacOS. Le smoke `pip install -e ".[macos]"` sur Linux reste utile, mais
son résultat doit être rapporté comme un smoke dépendant de l'environnement, pas
comme preuve des wheels macOS.

## Points encore en débat

### Suppression complète de `current_platform()` en M0

Je suis d'accord avec Claude, et je resserre ma position précédente.

J'avais accepté `current_platform()` avec un contrat minimal, mais l'argument
"pas d'appelant produit en M0" est plus fort. Si `desktop_integration()` n'a
besoin que de `is_linux()`, alors `current_platform()` serait une commodité
dérivée sans consommateur réel. Dans un lot qui revendique "rien de spéculatif",
il vaut mieux ne pas l'introduire maintenant.

Le bon endroit pour `current_platform()` sera le premier lot qui a un vrai
consommateur, probablement `doctor` en M2. À ce moment-là, son contrat sera guidé
par un usage concret au lieu d'être deviné.

### Nom `platform_dispatch.py`

D'accord avec la concession.

`platform.py` n'était pas techniquement bloquant, mais `platform_dispatch.py`
décrit mieux le rôle réel du module : router des intégrations OS-spécifiques.
Le coût du renommage est nul maintenant, et il évite une ambiguïté inutile avec
la bibliothèque standard et avec une éventuelle API générale de plateforme.

### `is_macos()` gardé même sans appel produit M0

J'accepte la distinction de Claude.

`is_macos()` n'est pas du même ordre que `current_platform()`. Dans M0, le socle
demandé est explicitement un dispatch `sys.platform` pour préparer macOS, et le
primitif Darwin est la moitié naturelle de ce socle. Il est minuscule, testé
directement, ne tire aucune dépendance, ne promet aucune fonctionnalité native et
n'importe aucun module `macos_*`.

La limite importante est celle que Claude pose déjà : `desktop_integration()` ne
doit pas utiliser `is_macos()` pour simuler une branche macOS vide. Tant que
Darwin tombe directement dans l'erreur non supportée, garder `is_macos()` comme
primitif symétrique est acceptable. C'est une brique de détection demandée, pas
une fonctionnalité anticipée.

### Classifieur MacOS en M0

Je maintiens mon acceptation sous les mêmes conditions, qui sont maintenant
intégrées au plan : pas de release M0 vendue comme support macOS complet, et
README explicite sur le statut aperçu navigateur. Avec ces garde-fous, le
classifieur reste cohérent avec le lot packaging prévu par le plan global.

## Évaluation globale

Il ne reste pas de désaccord substantiel.

Le plan M0 ajusté est prêt : couture réelle et minimale dans `cli.py`, module
`platform_dispatch.py` sans API dérivée inutile, pas de module `macos_*`, extra
`macos` correctement gardé par marqueurs Darwin, documentation honnête sur le
palier navigateur, et tests au bon niveau pour prouver la non-régression Linux.

Je valide le plan M0 dans sa forme actuelle.
CONSENSUS_ATTEINT
