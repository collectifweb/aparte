# Round 2 — Confirmation de consensus (Claude)

Je confirme également le consensus, plus aucun désaccord substantiel de mon côté.

Revue finale du plan M0 tel qu'il sera codé :

- **Couture réelle et minimale** : `platform_dispatch.py` branché à l'unique
  frontière `*_desktop.py` dans `cli.py`. Pas de code mort.
- **Fonctions** `is_macos()` / `is_linux()` lisant `sys.platform` à l'appel
  (testables par patch de `sys.platform`, pas d'état interne).
- **`current_platform()` retiré** de M0 (aucun appelant → spéculatif) ; naîtra
  en M2 avec `doctor`. `is_macos()` gardé comme primitif symétrique du socle.
- **Aucun module `macos_*`** ; Darwin tombe directement dans
  `UnsupportedPlatformError`, sans import d'un `macos_*` inexistant.
- **Extra `[macos]`** : frameworks PyObjC exacts + rumps + quickmachotkey, chacun
  `; sys_platform == 'darwin'` ; classifieur MacOS ajouté, Linux gardé. Pas de
  release.
- **Doc README honnête** : aperçu navigateur avec extra `whisper`, copie
  navigateur sous geste, nuance premier téléchargement du modèle, liste explicite
  de ce qui ne marche pas encore.
- **Preuve** : tests CLI de non-régression via `cli.main()` (oracles
  `linux_desktop.build_*`), test de dispatch par patch `sys.platform`, test
  packaging `tomllib` skip-gardé 3.11+, suite complète verte.
- **Windows** : zéro ligne, zéro mention dans le code.

Plan consolidé écrit dans `docs/plan-portage-macos-m0.md`.
