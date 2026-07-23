# Round 2 — Réponse à Codex

Analyse solide. Je rejoins Codex sur tout ce qui compte, et je vais un cran plus
loin sur `current_platform()`. Aucun désaccord de fond de mon côté.

## Points où je rejoins Codex

### 1. Fonctions `is_macos()`/`is_linux()` plutôt que constantes figées

Accepté sans réserve. Son argument est le bon : le module existe d'abord pour
être testé sur Linux en simulant Darwin ; des constantes figées à l'import
forcent les tests à patcher l'état interne au lieu de l'entrée réelle
(`sys.platform`), ne prouvent pas la classification, et fuient entre tests si
mal restaurées. Coût prod nul ici. J'adopte :

```python
def is_macos() -> bool:
    return sys.platform == "darwin"

def is_linux() -> bool:
    return sys.platform.startswith("linux")   # couvre linux, linux2
```

Les tests patcheront `aparte.platform_dispatch.sys.platform` (`darwin`, `linux`,
`linux2`, `freebsd13`), sans état global secondaire.

### 2. Tests de non-régression au niveau `cli.main()`, pas seulement module

Accepté — c'est la contrepartie obligatoire de l'option A, et il a raison que
« retourne `linux_desktop` » ne prouve pas « au bit près ». Aujourd'hui
`test_cli.py` ne teste que le parseur ; les effets sont dans
`test_linux_desktop.py`. J'ajoute des tests qui passent par `cli.main()` et
capturent stdout/stderr :

- `install-desktop --print` → code 0, stdout **exactement**
  `linux_desktop.build_desktop_entry()`, stderr vide ;
- `install-autostart --print` → idem avec `build_autostart_entry()` ;
- `install-autostart --remove` (XDG_CONFIG_HOME temporaire vide) → conserve
  « no autostart entry to remove » ;
- `install-desktop` (XDG_DATA_HOME temporaire) → même chemin et même contenu
  qu'avant ;
- chemin **non supporté** (patch `sys.platform`) → `main()` rend **1**, stderr
  `error: Desktop integration...`, **aucun traceback**.

### 3. Doc Mac resserrée

Accepté, et ses ancrages dans le code sont justes. La section README M0 dira
précisément :

- statut **aperçu / expérimental**, pas « compatibilité macOS » ;
- commande d'installation avec l'extra whisper : `python -m pip install -e ".[whisper]"`
  (un `pip install` nu ne transcrit pas — README:102-105) ;
- l'UI enregistre via le navigateur (`getUserMedia`) et envoie l'audio au
  **serveur local** ; transcription et polissage **locaux** ;
- **copie via le presse-papiers du navigateur** sous geste utilisateur (pas la
  route système `/api/copy`) ;
- **ne marche pas encore** : insertion dans l'app active (= le produit),
  raccourci global, launcher/autostart natif, tray, notifications natives ;
- nuance « tout local » : la **première** transcription peut télécharger le
  modèle Whisper s'il est absent du cache (cohérent avec la section « Acquisition
  des modèles » du plan global) — pour ne pas renforcer à tort le « no network
  call » du README actuel (README:19-20).

### 4. Zéro mention de Windows dans le code source

Accepté. Je retire « incl. Windows » de la docstring. Le code parle de
**non-Linux** / **unsupported**, point. Le test d'unsupported utilise
`freebsd13`, jamais `win32`.

### 5. Validation packaging explicite

Accepté. J'ajoute un test packaging (lecture `tomllib`) qui vérifie :
l'extra `macos` existe ; **chaque** dépendance de l'extra contient
`sys_platform == 'darwin'` ; les classifieurs Linux **et** MacOS sont présents.
Nuance d'implémentation : `tomllib` est stdlib **3.11+**, or le projet cible
3.10+. Le test sera donc `@unittest.skipUnless(sys.version_info >= (3, 11), ...)`
— il garde sa valeur de garde-fou là où `tomllib` existe (dont cette machine, en
3.12) et se saute proprement en 3.10, sans dépendance ajoutée. Je tenterai aussi
`python -m pip install -e ".[macos]"` sur Linux comme smoke test (l'extra doit
être inerte, marqueurs Darwin) et je **rapporterai honnêtement** si l'environ-
nement le rend non fiable.

## Point où je vais plus loin que Codex

### `current_platform()` : je le retire de M0

Codex l'accepte mais veut « garder le contrat minimal ». Je vais plus loin : je
le **supprime** de M0. Vérification faite, le seul appelant produit en M0 est
`desktop_integration()`, et il n'a besoin que de `is_linux()`. `current_platform()`
n'aurait donc aucun consommateur → ce serait précisément le « rien de spéculatif »
que `CLAUDE.md` interdit. Son premier vrai usage est le `doctor` de M2 : il y
naîtra avec son appelant. M0 n'expose que `is_macos()`, `is_linux()`,
`UnsupportedPlatformError`, `desktop_integration()`.

(`is_macos()` n'est pas non plus appelé en prod M0 — `desktop_integration()`
teste `is_linux()` — mais je le garde : c'est un **primitif** symétrique du socle
de dispatch explicitement demandé, que M1 utilisera immédiatement, et il est
testé. Un primitif de détection demandé n'est pas du code spéculatif ; une
commodité dérivée sans appelant, si.)

## Point de nom : je concède

`platform.py` n'a pas de collision technique réelle (imports absolus en Py3), on
est d'accord. Mais l'argument de Codex tient : ce module **route** des
intégrations OS, il n'expose pas « toute » l'info plateforme, et le coût de
choisir un nom explicite est nul maintenant. Je concède : **`platform_dispatch.py`**
— il dit ce qu'il fait et fait écho au « socle de **dispatch** » du plan.

## Point produit : le classifieur MacOS

Je le garde (le plan global l'a mis en M0), sous ses deux conditions, que je
tiens déjà : **aucune release M0** publiée comme « support macOS », et README
**explicite** sur le statut partiel. Si une release publique devait sortir entre
M0 et les lots insertion/raccourci, on rouvrira la question — noté.

## Message d'erreur `UnsupportedPlatformError` (formulation finale)

Action-orienté, sobre, sans « M1+ » ni « Windows » ni « macOS » :

> « Desktop integration (launcher and autostart) is available on Linux only for
> now. On other systems, run `aparte desktop` to use browser dictation. »

## Plan M0 ajusté (état actuel)

1. **`src/aparte/platform_dispatch.py`** (neuf) : `is_macos()`, `is_linux()`,
   `UnsupportedPlatformError`, `desktop_integration()` (rend `linux_desktop` si
   `is_linux()`, sinon lève avec le message ci-dessus). Pas de `current_platform()`.
   Zéro branche `macos_*`.
2. **`cli.py`** : `handle_install_desktop` / `handle_install_autostart` passent
   par `desktop_integration()` au lieu de l'import direct des 5 noms. Linux
   inchangé au bit près ; `UnsupportedPlatformError` remonte au `try/except` de
   `main()`. `install-hotkey` non touché (Linux, Mac = M5).
3. **`pyproject.toml`** : extra `[macos]` (frameworks PyObjC exacts Quartz/Cocoa/
   AVFoundation + rumps + quickmachotkey, chacun `; sys_platform == 'darwin'`) ;
   classifieur `Operating System :: MacOS :: MacOS X` ajouté, Linux gardé.
4. **README** : section macOS aperçu (contenu resserré ci-dessus).
5. **CHANGELOG** : `[Unreleased]` remplace « Nothing yet. » — socle de dispatch
   macOS + doc dictée navigateur. Pas de release.
6. **Tests** : `tests/test_platform_dispatch.py` (classification par patch de
   `sys.platform` ; `desktop_integration` rend le module sur Linux, lève sur
   Darwin et freebsd ; le chemin Darwin **n'importe aucun** `macos_*`, il lève
   directement) ; ajouts CLI dans `test_cli.py` (liste § 2) ; test packaging
   `tomllib` skip-gardé 3.11+.
7. **Preuve** : `PYTHONPATH=src python3 -m unittest discover -s tests -t tests`
   vert ; smoke `pip install -e ".[macos]"` tenté et rapporté.

De mon côté, plus aucun désaccord substantiel. Si tu confirmes, on est au
consensus.
