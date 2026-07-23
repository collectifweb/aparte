# Round 1 — Analyse Codex du plan M0

## Verdict

Le plan est globalement bien cadré pour M0 : il ne tente pas de livrer un port macOS déguisé, il identifie le seul point `*_desktop.py` déjà branchable, et il refuse correctement d'écrire des modules `macos_*` avant leur lot. Je valide l'option **A** sur la profondeur de couture : brancher le sélecteur dans `cli.py` est le bon niveau pour M0. L'option **B** livrerait un module de dispatch non appelé, donc spéculatif.

Je ne validerais pas le plan tel quel sans deux corrections : remplacer les constantes `IS_MACOS` / `IS_LINUX` figées à l'import par des fonctions testables, et durcir les tests CLI pour prouver que le chemin Linux reste identique en sortie et en effets. Je corrigerais aussi la formulation README proposée : "pip install + aparte desktop" est trop vague, et "copie fonctionne" doit désigner la copie navigateur, pas les routes système Linux.

## 1. Ce que j'approuve

### Option A : brancher `desktop_integration()` dans `cli.py`

J'approuve **catégoriquement** l'option A. Le code actuel importe directement cinq fonctions de `linux_desktop` au niveau de `cli.py` (`src/aparte/cli.py:19-25`) et ne les utilise que dans deux handlers (`src/aparte/cli.py:430-447`). C'est une vraie frontière OS : launcher `.desktop`, autostart XDG, icône hicolor, chemins Linux (`src/aparte/linux_desktop.py:65-151`).

Brancher le sélecteur à cet endroit est la couture minimale qui a une valeur exécutable. Sur Linux, si `desktop_integration()` retourne le module `linux_desktop`, les deux handlers peuvent appeler exactement les mêmes fonctions : `build_desktop_entry()`, `install_desktop_entry()`, `build_autostart_entry()`, `install_autostart_entry()`, `uninstall_autostart_entry()`. C'est le bon compromis entre "rien de spéculatif" et "Linux inchangé".

L'option B ne me convainc pas. Un `platform.py` que rien n'appelle ne protège pas le chemin Linux, il repousse simplement le vrai changement à M1. Dans un lot M0 censé poser un socle de dispatch, ce serait du code mort avec une promesse d'architecture.

### Ne brancher que la frontière desktop

Je valide le choix de ne pas toucher `clipboard.py`, `notify.py`, `audio.py`, `session.py` ou `hotkey.py` en M0. Les branches `darwin` de ces modules appartiennent aux lots suivants. M0 doit prouver un patron, pas disperser des `if sys.platform` sans implémentation native derrière.

### Extra `[macos]` avec marqueurs `sys_platform == 'darwin'`

J'approuve l'extra `[macos]` avec un marqueur sur chaque dépendance PyObjC / rumps / quickmachotkey. C'est la bonne défense : `pip install .[macos]` demandé par erreur sur Linux ne doit pas essayer de résoudre ou compiler des dépendances natives macOS. Le choix de frameworks PyObjC ciblés plutôt que le méta-paquet `pyobjc` est aussi sain.

La vérification des wheels arm64 et du nom exact des paquets reste à faire sur un vrai Mac. Sur cette machine, on peut seulement valider que le `pyproject.toml` parse et que les marqueurs rendent l'extra inerte hors Darwin.

### Aucun module `macos_*` en M0

Le plan respecte la contrainte. C'est important : écrire `macos_desktop.py` vide ou pseudo-implémenté maintenant serait pire que ne rien faire, parce que les tests Linux ne pourraient pas prouver son comportement réel.

### CHANGELOG

Ajouter une entrée sous `[Unreleased]` est cohérent. Le fichier existe et contient actuellement `Nothing yet.` (`CHANGELOG.md:8-10`) ; M0 doit remplacer cette ligne par une entrée explicite, sans créer de release.

## 2. Ce que je désapprouve

### Constantes `IS_MACOS` / `IS_LINUX` figées à l'import

Je désapprouve ce choix. Pour un module dont la première utilité est d'être testé sur Linux en simulant Darwin, des constantes figées à l'import forcent les tests à patcher l'état interne du module au lieu de patcher l'entrée réelle du système (`sys.platform`). Ce n'est pas seulement "plus verbeux" de faire des fonctions : c'est plus correct.

Le plan propose de tester `desktop_integration()` en modifiant `aparte.platform.IS_LINUX` et `IS_MACOS`. Ce test ne prouve pas que `sys.platform == "darwin"` est classé correctement ; il prouve seulement qu'une variable globale mutable a été lue. Il augmente aussi le risque de fuite entre tests si une constante patchée n'est pas restaurée.

Je ferais plutôt :

```python
def is_macos() -> bool:
    return sys.platform == "darwin"


def is_linux() -> bool:
    return sys.platform.startswith("linux")


def current_platform() -> str:
    if is_macos():
        return "macos"
    if is_linux():
        return "linux"
    return "unsupported"
```

Les tests peuvent alors patcher `aparte.platform.sys.platform` à `"darwin"`, `"linux"`, ou `"freebsd13"` sans état global secondaire. En production, le coût est nul dans ce contexte.

### L'affirmation "comportement Linux identique au bit près" est trop rapide

Je suis d'accord avec l'intention, mais pas avec la preuve proposée. Le fait que le sélecteur retourne `linux_desktop` ne suffit pas à établir le "bit près". On change quand même le chemin d'appel de deux commandes CLI visibles.

Aujourd'hui, `tests/test_cli.py` ne teste que le parseur pour `install-desktop --print` (`tests/test_cli.py:107-110`). Les effets et sorties des handlers sont couverts dans `tests/test_linux_desktop.py` au niveau module (`tests/test_linux_desktop.py:21-106`), pas via `cli.main()`. Si M0 touche `cli.py`, il faut des tests CLI qui capturent stdout/stderr et comparent les sorties à celles de `linux_desktop`.

### La doc Mac proposée est trop large

La phrase "sur Mac, `pip install` + `aparte desktop` sert la page ; getUserMedia, transcription faster-whisper CPU, polissage, copie fonctionnent" doit être resserrée.

Le README actuel dit déjà qu'un `pip install -e .` nu ne permet pas de transcrire (`README.md:102-105`). La dictée navigateur Mac a besoin au minimum de l'extra `whisper` ou d'un autre backend de transcription configuré. La doc M0 doit donc montrer une commande du type `python -m pip install -e ".[whisper]"`, pas "pip install" tout court.

Le code confirme aussi que la copie UI essaye d'abord `/api/copy`, qui appelle `copy_text()` côté serveur (`src/aparte/desktop.py:294-297`), puis retombe sur `navigator.clipboard.writeText()` en cas d'échec (`src/aparte/assets/app.js:279-287`). Sur Mac aujourd'hui, il faut présenter comme fonctionnelle la **copie navigateur sous geste utilisateur**, pas la route système `/api/copy`. Le bouton Paste, lui, appelle `/api/paste` (`src/aparte/assets/app.js:289-292`) et reste hors promesse M0.

### Mentionner Windows dans le code proposé

La contrainte donnée est "Windows zéro ligne". Le pseudo-code du plan met "incl. Windows" dans la docstring de `desktop_integration()`. Même si ce n'est pas une branche ni une dépendance, je l'enlèverais du code source. Le code doit parler de "non-Linux" ou "unsupported", point. Les tests d'unsupported peuvent utiliser `freebsd13` plutôt que `win32`.

## 3. Ce qui manque

### Tests CLI de non-régression Linux

M0 doit ajouter des tests qui passent par `cli.main()`, pas seulement par `desktop_integration()`.

Je veux au minimum :

- `cli.main(["install-desktop", "--print"])` retourne `0`, stdout égale exactement `linux_desktop.build_desktop_entry()`, stderr vide.
- `cli.main(["install-autostart", "--print"])` retourne `0`, stdout égale exactement `linux_desktop.build_autostart_entry()`, stderr vide.
- `cli.main(["install-autostart", "--remove"])`, avec `XDG_CONFIG_HOME` dans un répertoire temporaire vide, conserve la sortie actuelle `no autostart entry to remove`.
- `cli.main(["install-desktop"])`, avec `XDG_DATA_HOME` temporaire, écrit le même chemin et le même contenu qu'avant.
- Un test unsupported mocké vérifie que `install-desktop --print` retourne `1` avec `error: Desktop integration...` sur stderr, sans traceback.

Ces tests sont la contrepartie obligatoire de l'option A. Sans eux, on dit "inchangé" au lieu de le démontrer.

### Tests du dispatch par `sys.platform`

Avec des fonctions `is_linux()` / `is_macos()`, les tests doivent patcher `aparte.platform.sys.platform`, pas des constantes. Il faut tester `linux`, `linux2` ou équivalent préfixé, `darwin`, et un unsupported non Windows.

Il faut aussi tester que le chemin Darwin ne tente pas d'importer un module `macos_*` inexistant en M0. La condition doit lever directement `UnsupportedPlatformError`.

### Validation packaging minimale

Le plan mentionne "pyproject parse" et `pip install -e .`, mais M0 devrait être plus explicite :

- test ou commande `tomllib` pour vérifier que l'extra `macos` existe ;
- vérifier que chaque dépendance de l'extra contient `sys_platform == 'darwin'`;
- vérifier que les classifiers Linux et Mac sont tous les deux présents ;
- lancer la suite `PYTHONPATH=src python3 -m unittest discover -s tests -t tests`.

Si l'environnement le permet, `python -m pip install -e ".[macos]"` sur Linux est un bon smoke test précisément parce que l'extra doit être inerte hors Darwin. Si le réseau ou l'environnement rend ce test non fiable, il faut le dire dans le compte rendu.

### Documentation : limites exactes du palier navigateur

La section README M0 doit dire explicitement :

- statut expérimental / aperçu, pas compatibilité macOS complète ;
- commande d'installation avec `whisper` au minimum ;
- l'UI web enregistre via le navigateur (`getUserMedia`) et envoie l'audio au serveur local (`src/aparte/assets/app.js:97-132`) ;
- transcription locale via le backend configuré ;
- polissage local ;
- copie via le presse-papiers du navigateur si la route système échoue ;
- pas d'insertion dans l'app active, pas de raccourci global, pas de launcher/autostart natif, pas de tray, pas de notifications natives ;
- premier téléchargement possible du modèle Whisper si absent du cache, pour ne pas renforcer la promesse README actuelle "no network call" (`README.md:19-20`).

### Portée des erreurs unsupported

Le message d'erreur de `UnsupportedPlatformError` doit être stable et orienté action, mais pas trop bavard. Il devrait dire que launcher/autostart ne sont disponibles que sous Linux pour l'instant, et pointer vers `aparte desktop` pour l'aperçu navigateur. Il ne doit pas promettre M1+ comme si c'était déjà planifié pour l'utilisateur final, sauf dans la doc développeur.

## 4. Ce que je remettrais en question

### Nom `platform.py`

Je ne vois pas de collision technique bloquante avec la stdlib dans l'usage normal du paquet. Avec `PYTHONPATH=src`, `import platform` reste un import absolu de la stdlib ; `aparte.platform` n'est trouvé que par import relatif ou import qualifié. Donc je ne rejetterais pas le plan pour ce nom.

Cela dit, je préfère légèrement `platform_dispatch.py` ou `os_dispatch.py`, parce que ce module ne vise pas à exposer toutes les informations de plateforme : il route des intégrations OS-spécifiques. Le coût de choisir un nom plus explicite est nul maintenant. Mon avis : `platform.py` est acceptable, `platform_dispatch.py` est plus clair. Ce n'est pas un point de blocage.

### Classifier macOS dès M0

Le plan global inclut les classifieurs dans M0, donc je ne relance pas la décision. Mais il y a un risque de signal produit : `Operating System :: MacOS :: MacOS X` peut être lu comme "l'application supporte macOS", alors que M0 ne documente qu'un palier navigateur et garde le produit principal incomplet.

Je l'accepte seulement si deux conditions sont respectées : pas de release M0 publiée comme support macOS complet, et README très explicite sur le statut partiel. Si une release publique devait sortir après M0 mais avant les lots d'insertion/raccourci, je remettrais le classifier en débat.

### Exposer `current_platform()`

`current_platform()` est pratique pour les tests et le diagnostic mental, mais M0 n'en a pas forcément besoin dans le code produit si le seul point appelé est `desktop_integration()`. Je ne l'interdirais pas, mais je garderais son contrat minimal. Éviter d'en faire une API publique que les autres modules commencent à consulter partout en M1/M2 ; les décisions doivent rester au point d'appel.

### Dépendances `[macos]` non utilisées immédiatement

Ajouter les dépendances Mac dès M0 est acceptable parce que le lot inclut packaging. Mais il faut assumer que cet extra est une préparation de packaging, pas une preuve que ces intégrations fonctionnent. Les commentaires dans `pyproject.toml` peuvent nommer les lots futurs, mais il ne faut pas ajouter d'import ni de test qui suppose ces paquets installés sur Linux.

## Avis tranché sur les points prioritaires

- **Profondeur M0** : option **A**. Je rejette B comme code mort spéculatif. A est sûre si les tests CLI exacts sont ajoutés.
- **Nom `platform.py`** : pas de collision technique réelle dans le paquet. Gênant seulement pour la lisibilité. Acceptable, mais je choisirais `platform_dispatch.py` si on tranche maintenant.
- **Constantes import-time** : non. Utiliser `is_linux()` / `is_macos()` qui lisent `sys.platform` à l'appel.
- **Extra `[macos]` avec marqueurs Darwin** : oui. C'est la bonne forme. Vérification réelle des paquets reportée au Mac.
- **Linux inchangé** : objectif atteignable avec A, mais pas prouvé par les tests proposés. Ajouter des tests via `cli.main()`.
- **Windows zéro ligne** : pas de branche, pas de dépendance, et idéalement pas de mention dans le code source ajouté. Utiliser "unsupported".
- **Aucun `macos_*` en M0** : oui, à maintenir strictement.
- **Machine Linux / tests mockés** : oui, mais mocker `sys.platform`, pas des constantes internes.
