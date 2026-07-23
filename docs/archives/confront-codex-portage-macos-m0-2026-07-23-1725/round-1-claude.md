# Round 1 — Plan M0 (socle de dispatch macOS + pas gratuit)

## Contexte

Aparté est une application de dictée vocale **Linux uniquement**, Python 3.10+,
sans framework, paquet `src/aparte/`. Le plan de portage macOS complet
(`docs/plan-portage-macos.md`) a **déjà atteint le consensus** avec toi le 23/07
(4 rounds). **On ne rejoue pas ce plan.** Ce débat porte uniquement sur le
**premier lot d'exécution, M0**, tel qu'il doit être codé maintenant, sur une
machine Linux (le code macOS ne s'exécute pas ici ; tests mockés seulement).

Le plan global fixe M0 ainsi (tableau des lots, ligne M0, effort 0,5 j) :
> Dispatch `sys.platform`, extra `[macos]`, classifieurs, **doc dictée navigateur**.

Et précise l'architecture retenue (section « Architecture ») :
> On garde le patron `*_desktop.py` (le nom porte l'OS) et des branches
> `sys.platform`. [...] On écarte une couche `platform/base.py` + implémentations :
> sur-ingénierie pour 6 modules courts aux API déjà stables.

Contraintes non négociables (issues du plan global et de `CLAUDE.md`) :
- **Linux d'abord** : comportement Linux **inchangé au bit près**, suite de tests
  verte (`PYTHONPATH=src python3 -m unittest discover -s tests -t tests`).
- **Le plus simple d'abord**, modifications chirurgicales, rien de spéculatif.
- **Windows hors périmètre** : zéro ligne, zéro dépendance, zéro branche.
- **Aucun module `macos_*` en M0** : on pose la couture, on n'écrit pas encore
  d'implémentation Mac.

## État du code (vérifié)

- **Aucune détection d'OS centralisée** : `grep sys.platform|platform.system|os.name`
  sur `src/aparte/` = 0 occurrence. Terrain neuf.
- Le patron `*_desktop.py` **existe déjà** : `src/aparte/linux_desktop.py`
  (152 lignes — fichiers `.desktop`, autostart, icône hicolor). Importé par
  `cli.py:19-25` :
  ```python
  from .linux_desktop import (
      build_autostart_entry, build_desktop_entry,
      install_autostart_entry, install_desktop_entry,
      uninstall_autostart_entry,
  )
  ```
  Utilisé uniquement dans `handle_install_desktop()` (cli.py:430) et
  `handle_install_autostart()` (cli.py:438). Cinq fonctions, deux handlers.
- `pyproject.toml` : extras `whisper`, `recording`, `cuda`, `dev`. Classifieur
  `Operating System :: POSIX :: Linux` seul. `requires-python = ">=3.10"`.
- Les modules « mixtes » du plan (`clipboard.py`, `notify.py`, `audio.py`)
  appellent des binaires Linux en dur (xclip/wtype, notify-send, arecord/aplay).
  **Leurs branches `darwin` sont M1, pas M0.**

## Approche proposée

### 1. Le pas gratuit — doc dictée navigateur sur Mac

Une section macOS dans le README (aperçu/expérimental, ton modeste, cohérent avec
« Linux d'abord ») : aujourd'hui, sur Mac, `pip install` + `aparte desktop` sert
la page ; `getUserMedia` (enregistrement navigateur), transcription
faster-whisper CPU, polissage, copie **fonctionnent**. Ce qui **ne marche pas
encore** : insertion dans l'app active (= le produit), raccourci global, tray,
notifications natives. Renvoi vers `docs/plan-portage-macos.md`.

### 2. Le socle de dispatch — `src/aparte/platform.py` (neuf)

Module minuscule, source unique de vérité pour l'OS :

```python
from __future__ import annotations
import sys

IS_MACOS = sys.platform == "darwin"
IS_LINUX = sys.platform.startswith("linux")


class UnsupportedPlatformError(RuntimeError):
    """Raised when a feature has no implementation for the current OS."""


def current_platform() -> str:
    if IS_MACOS:
        return "macos"
    if IS_LINUX:
        return "linux"
    return "unsupported"


def desktop_integration():
    """The OS-specific .desktop/autostart backend (the ``*_desktop.py`` family).

    Linux returns the existing module unchanged. macOS is planned for M1+ and
    raises with a clear message; every non-Linux OS (incl. Windows, explicitly
    out of scope) takes the same guarded path — no per-OS branch is written.
    """
    if IS_LINUX:
        from . import linux_desktop
        return linux_desktop
    raise UnsupportedPlatformError(
        "Desktop integration (launcher/autostart) is Linux-only for now. "
        "macOS support is planned (M1+); browser dictation already works today: "
        "run `aparte desktop`."
    )
```

### 3. Brancher au SEUL point d'accroche réel — `cli.py`

Pour que `platform.py` **ne soit pas du code mort spéculatif**, on le branche à
l'unique frontière `*_desktop.py` qui existe. `cli.py` cesse d'importer les cinq
noms depuis `linux_desktop` et passe par le sélecteur :

```python
from .platform import desktop_integration
...
def handle_install_desktop(args):
    desktop = desktop_integration()          # Linux: linux_desktop ; Mac: lève
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

Sur Linux : `desktop_integration()` rend `linux_desktop`, donc **comportement
identique au bit près**. L'exception `UnsupportedPlatformError` remonte au
`try/except Exception` déjà présent dans `main()` (cli.py:89) → `error: ...` +
code retour 1, propre. `install-hotkey` importe déjà `hotkey` en local (cli.py:451),
il reste Linux et n'est **pas** touché en M0 (le raccourci Mac est M5).

### 4. Packaging — `pyproject.toml`

- Extra **`[macos]`**, frameworks PyObjC **exacts** (pas le méta-paquet `pyobjc`),
  chacun marqué `darwin` pour que rien ne s'installe hors Mac :
  ```toml
  macos = [
    "pyobjc-framework-Quartz; sys_platform == 'darwin'",       # CGEvent (insertion, M3)
    "pyobjc-framework-Cocoa; sys_platform == 'darwin'",        # AppKit/run loop (M5)
    "pyobjc-framework-AVFoundation; sys_platform == 'darwin'", # permission micro (M2)
    "rumps; sys_platform == 'darwin'",                         # tray (M6)
    "quickmachotkey; sys_platform == 'darwin'",                # façade raccourci (M5)
  ]
  ```
  Vérif des wheels arm64 déférée au vrai Mac (impossible ici).
- Classifieur `"Operating System :: MacOS :: MacOS X"` **ajouté** ; le classifieur
  Linux est **gardé** (Linux d'abord).

### 5. Tests — `tests/test_platform.py` (neuf, `unittest`)

- `current_platform()` == `"linux"` sur cette machine ; `IS_MACOS is False`.
- `desktop_integration()` rend l'objet module `linux_desktop` quand
  `sys.platform` vaut `linux`.
- `desktop_integration()` lève `UnsupportedPlatformError` quand on force
  `aparte.platform.IS_LINUX = False` / `IS_MACOS = True` (monkeypatch des
  constantes, pas de `sys.platform` réel — voir « points sensibles »).

### 6. CHANGELOG

Entrée « Non publié » : socle de dispatch macOS + doc dictée navigateur.
**Pas de release** — M0 ne livre aucune fonctionnalité Mac.

## Points sensibles (honnêtes)

1. **`IS_MACOS`/`IS_LINUX` sont figées à l'import.** Elles lisent `sys.platform`
   une fois. Un test qui monkeypatche `sys.platform` après import ne changera pas
   les constantes → les tests doivent monkeypatcher **les constantes du module**
   (`aparte.platform.IS_LINUX`), pas `sys.platform`. C'est un choix : constantes
   simples et lisibles, au prix d'une testabilité par patch de constante. Une
   alternative serait de tout calculer dans des fonctions (`is_macos()`),
   re-testables par patch de `sys.platform`, mais plus verbeux pour un gain nul en
   prod. **Je penche pour les constantes ; à challenger.**

2. **Toucher `cli.py` est-il justifié en M0 ?** C'est le cœur du débat. Deux
   options :
   - **(A) Couture réelle** (ma proposition) : brancher le sélecteur dans
     `cli.py`. Avantage : `platform.py` est immédiatement utilisé et testé, la
     frontière `*_desktop.py` est réellement posée, M1 n'a qu'à ajouter la branche
     `macos_desktop`. Coût : ~1 import + 2 handlers réécrits (mécanique, Linux
     inchangé).
   - **(B) Détection pure** : livrer `platform.py` seul, sans toucher `cli.py`.
     Avantage : zéro risque sur le chemin Linux. Coût : `platform.py` devient du
     **code mort** que rien n'appelle (viole « rien de spéculatif »), et la vraie
     couture est repoussée à M1.
   Je choisis (A) : la couture n'existe que si elle a ses deux extrémités ; un
   module de détection que personne n'appelle n'est pas une couture, c'est une
   promesse. Et le risque Linux est nul (le sélecteur rend le même module).

3. **`current_platform()` renvoie `"unsupported"` pour Windows/BSD.** Volontaire :
   pas de logique Windows, juste un fourre-tout honnête. `desktop_integration()`
   lève pour tout ce qui n'est pas Linux — donc Windows obtient une erreur propre
   sans une ligne de code Windows.

4. **Le nom `platform.py` masque le module standard `platform`.** À l'intérieur du
   paquet `aparte`, les imports sont relatifs (`from .platform import ...`) et
   `import platform` (stdlib) resterait absolu — pas de collision réelle en
   Python 3 (imports absolus par défaut). Mais le nom peut gêner un lecteur.
   Alternatives : `platform_dispatch.py`, `osdetect.py`, `_platform.py`. **À
   challenger** — je penche pour `platform.py` (le plus lisible au point d'appel :
   `from .platform import desktop_integration`).

5. **Vérification packaging sans Mac.** On ne peut pas prouver que
   `pip install .[macos]` résout les wheels arm64 ici. On peut seulement prouver
   que le `pyproject.toml` **parse** et que `pip install -e .` (sans l'extra)
   marche toujours. La résolution réelle de l'extra est déférée au vrai Mac —
   assumé, documenté.

## Alternatives écartées

- **Couche `platform/base.py` + classes** : déjà écartée au consensus du plan
  global (sur-ingénierie pour 6 modules courts). On garde `*_desktop.py` + branche.
- **Brancher `clipboard`/`notify`/`audio` dès M0** : c'est M1. En M0 on ne pose
  qu'une couture (`*_desktop.py`) ; multiplier les branches maintenant, sans
  implémentation Mac derrière, serait du bruit.
- **Méta-paquet `pyobjc`** : tire des dizaines de frameworks pour trois besoins.
  Le plan l'interdit explicitement.
- **Extra `[macos]` nu (sans marqueur `darwin`)** : un `pip install .[macos]` par
  erreur sur Linux/Windows tenterait de compiler PyObjC. Le marqueur `darwin` rend
  l'extra inerte hors Mac — défense peu coûteuse.

## Question ouverte que je te soumets

La seule vraie décision de conception : **profondeur de la couture M0** — option
(A) brancher `cli.py` (couture réelle, testable, `platform.py` non mort) vs (B)
détection pure (zéro risque Linux mais code mort). Je défends (A). Convaincs-moi
du contraire si tu vois un piège, ou confirme.
