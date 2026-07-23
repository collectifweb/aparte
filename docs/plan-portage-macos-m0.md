# Plan M0 — socle de dispatch macOS + pas gratuit

Tranche d'exécution du portage macOS d'Aparté. Le plan d'architecture complet
vit dans [plan-portage-macos.md](plan-portage-macos.md) ; ce document décrit
seulement **ce que M0 code maintenant**. Consensus atteint avec Codex le 23/07
(archives : `docs/archives/confront-codex-portage-macos-m0-2026-07-23-1725/`).

## Contexte

Aparté est Linux uniquement (Python 3.10+, sans framework). M0 **pose la
couture de plateforme et le packaging macOS**, sans écrire un seul module
`macos_*` : ces implémentations arrivent en M1+ et se prouvent sur un vrai Mac.
Cette machine est sous Linux ; le code macOS ne s'y exécute pas.

Contraintes non négociables :

- **Linux d'abord** : comportement Linux inchangé, suite verte
  (`PYTHONPATH=src python3 -m unittest discover -s tests -t tests`).
- **Le plus simple d'abord**, chirurgical, **rien de spéculatif**.
- **Windows hors périmètre** : zéro ligne, zéro dépendance, zéro mention dans le
  code (on dit « non-Linux » / « unsupported »).
- **Aucun module `macos_*` en M0**.

## Approche

### 1. Le pas gratuit — documenter la dictée navigateur sur Mac

Une section macOS dans le README, ton **aperçu / expérimental**, cohérente avec
« Linux d'abord ». Elle dit précisément :

- installation avec l'extra transcription : `python -m pip install -e ".[whisper]"`
  (un `pip install` nu ne transcrit pas) ;
- l'UI enregistre dans le **navigateur** (`getUserMedia`) et envoie l'audio au
  **serveur local** ; transcription et polissage **locaux** ;
- **copie via le presse-papiers du navigateur** sous geste utilisateur ;
- **ne marche pas encore** : insertion dans l'app active (= le produit),
  raccourci global, launcher/autostart natif, tray, notifications natives ;
- nuance « tout local » : la **première** transcription peut télécharger le
  modèle Whisper s'il est absent du cache (ensuite tout est hors-ligne) ;
- renvoi vers `docs/plan-portage-macos.md`.

### 2. Le socle — `src/aparte/platform_dispatch.py` (neuf)

Source unique de détection d'OS, minuscule, sans API dérivée inutile :

```python
from __future__ import annotations
import sys


class UnsupportedPlatformError(RuntimeError):
    """Raised when a feature has no implementation for the current OS."""


def is_macos() -> bool:
    return sys.platform == "darwin"


def is_linux() -> bool:
    return sys.platform.startswith("linux")   # linux, linux2


def desktop_integration():
    """Return the OS-specific launcher/autostart backend (the *_desktop family).

    Linux returns the existing module unchanged. Every other OS raises — no
    per-OS branch and no macos_* import exists yet.
    """
    if is_linux():
        from . import linux_desktop
        return linux_desktop
    raise UnsupportedPlatformError(
        "Desktop integration (launcher and autostart) is available on Linux "
        "only for now. On other systems, run `aparte desktop` to use browser "
        "dictation."
    )
```

- `is_macos()` est gardé comme **primitif symétrique** du socle demandé (M1
  l'utilisera) ; il n'est pas appelé par `desktop_integration()`, qui ne teste
  que `is_linux()` — Darwin tombe donc directement dans l'erreur, sans simuler
  une branche macOS vide.
- **`current_platform()` n'est pas introduit en M0** (aucun appelant). Il naîtra
  en M2 avec `doctor`, son premier vrai consommateur.

### 3. Brancher l'unique frontière — `cli.py`

`cli.py` cesse d'importer les cinq noms de `linux_desktop` et passe par le
sélecteur. Sur Linux, `desktop_integration()` rend `linux_desktop` : comportement
**identique**. Sur tout autre OS, `UnsupportedPlatformError` remonte au
`try/except Exception` déjà présent dans `main()` → `error: ...`, code retour 1.

```python
from .platform_dispatch import desktop_integration

def handle_install_desktop(args):
    desktop = desktop_integration()
    if args.print:
        print(desktop.build_desktop_entry(), end=""); return
    print(desktop.install_desktop_entry(force=args.force))

def handle_install_autostart(args):
    desktop = desktop_integration()
    if args.remove:
        removed = desktop.uninstall_autostart_entry()
        print(f"removed {removed}" if removed else "no autostart entry to remove"); return
    if args.print:
        print(desktop.build_autostart_entry(), end=""); return
    print(desktop.install_autostart_entry(force=args.force))
```

`install-hotkey` reste Linux et **n'est pas touché** (le raccourci Mac est M5).
Les modules mixtes (`clipboard`, `notify`, `audio`) et leurs branches `darwin`
sont M1.

### 4. Packaging — `pyproject.toml`

Extra `[macos]`, frameworks PyObjC **exacts** (pas le méta-paquet `pyobjc`),
chacun marqué Darwin pour rester inerte hors Mac :

```toml
macos = [
  "pyobjc-framework-Quartz; sys_platform == 'darwin'",        # CGEvent (insertion, M3)
  "pyobjc-framework-Cocoa; sys_platform == 'darwin'",         # AppKit / run loop (M5)
  "pyobjc-framework-AVFoundation; sys_platform == 'darwin'",  # permission micro (M2)
  "rumps; sys_platform == 'darwin'",                          # tray (M6)
  "quickmachotkey; sys_platform == 'darwin'",                 # façade raccourci (M5)
]
```

Classifieur `"Operating System :: MacOS :: MacOS X"` ajouté ; classifieur Linux
gardé (Linux d'abord). La vérification des wheels arm64 est **déférée au vrai
Mac** ; ici on prouve seulement que le fichier parse et que l'extra est inerte
sous Linux.

### 5. CHANGELOG

Remplacer « Nothing yet. » sous `[Unreleased]` par une entrée : socle de dispatch
macOS + doc dictée navigateur. **Pas de release** (M0 ne livre aucune
fonctionnalité Mac).

## Preuve exigée

- `tests/test_platform_dispatch.py` : classification correcte en patchant
  `aparte.platform_dispatch.sys.platform` (`linux`, `linux2`, `darwin`,
  `freebsd13`) ; `desktop_integration()` rend l'objet `linux_desktop` sur Linux ;
  lève `UnsupportedPlatformError` sur Darwin **et** freebsd, **sans importer**
  de `macos_*`.
- `tests/test_cli.py` (ajouts, via `cli.main()`, stdout/stderr capturés,
  oracles `linux_desktop.build_*`) :
  - `install-desktop --print` → 0, stdout == `build_desktop_entry()`, stderr vide ;
  - `install-autostart --print` → 0, stdout == `build_autostart_entry()` ;
  - `install-autostart --remove` (XDG_CONFIG_HOME temporaire vide) → « no
    autostart entry to remove » ;
  - `install-desktop` (XDG_DATA_HOME temporaire) → même chemin et contenu ;
  - OS non supporté (patch `sys.platform`) → `main()` rend **1**, stderr
    `error: Desktop integration...`, **aucun traceback**.
- test packaging `tomllib`, `@unittest.skipUnless(sys.version_info >= (3, 11))` :
  extra `macos` présent ; **chaque** dépendance porte `sys_platform == 'darwin'` ;
  classifieurs Linux **et** MacOS présents.
- Suite complète verte. Smoke `python -m pip install -e ".[macos]"` sur Linux
  tenté et **rapporté comme smoke dépendant de l'environnement**, pas comme
  preuve des wheels macOS.

## Points de vigilance (implémentation)

- Les tests de dispatch patchent `sys.platform`, **jamais** une constante
  interne : le module lit `sys.platform` à chaque appel, c'est ce qui les rend
  fiables.
- Ne pas laisser `desktop_integration()` importer un `macos_*` : Darwin doit
  lever **avant** tout import.
- Le classifieur MacOS suppose **aucune release M0** vendue comme « support
  macOS » et un README explicite sur le statut partiel. Si une release publique
  devait sortir avant les lots insertion/raccourci, rouvrir la question.

## Décisions explicitement écartées

- **Constantes `IS_MACOS`/`IS_LINUX` figées à l'import** — moins testables (forcent
  le patch d'état interne), aucun gain en prod.
- **`platform.py` (nom)** — pas de collision technique, mais `platform_dispatch.py`
  décrit mieux un module qui **route** des intégrations, sans ambiguïté avec la
  stdlib.
- **Détection pure (module non branché)** — code mort spéculatif ; une couture
  n'existe que si elle a ses deux extrémités.
- **Brancher `clipboard`/`notify`/`audio` dès M0** — c'est M1 ; disperser des
  `if sys.platform` sans implémentation native derrière serait du bruit.
- **Méta-paquet `pyobjc`** — tire des dizaines de frameworks pour trois besoins.
- **`current_platform()` en M0** — sans appelant, donc spéculatif ; reporté à M2.
