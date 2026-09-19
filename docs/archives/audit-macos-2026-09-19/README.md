# Reproductions de l'audit macOS du 19 septembre 2026

Rapport : [audit macOS](../../audit-macos-2026-09-19.md).
Base auditée : `73b5317`, version `1.1.3`.

Ces probes démontrent des défauts dans des scénarios synthétiques. Les accès
micro, TCC, Quartz, presse-papiers et signature sont simulés. Aucun fichier
audio personnel n'est utilisé. Les fichiers `.txt` sont les sorties réelles
de leur exécution sous Linux pendant cet audit.

Depuis la racine du dépôt, sans variables `APARTE_*`/`MURMUR_*` héritées :

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests python3 docs/archives/audit-macos-2026-09-19/runtime.py
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests python3 docs/archives/audit-macos-2026-09-19/model-http.py
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 docs/archives/audit-macos-2026-09-19/install-replacement.py
node docs/archives/audit-macos-2026-09-19/watch-model.cjs
PYTHONDONTWRITEBYTECODE=1 python3 docs/archives/audit-linux-2026-09-19/backend.py .
node docs/archives/audit-linux-2026-09-19/interface.cjs
```

- `runtime.py` : capture perdue, débordement ignoré, fermeture pendant traitement,
  argument Unicode et langue sans environnement POSIX.
- `model-http.py` : branche Darwin, hôte étranger, verrou après erreur disque,
  caches incomplets, capture native pendant préparation du modèle.
- `install-replacement.py` : erreur de copie pendant remplacement d'une fausse
  application, dans un dossier temporaire.
- `watch-model.cjs` : vraie fonction de sondage JS, réseau simulé.
- `backend.txt` et `interface.txt` : scénarios partagés rejoués depuis les
  scripts du précédent audit. La concurrence d'historique peut perdre une ou
  deux entrées suivant l'ordonnancement ; ce n'est pas une mesure de fréquence.
- `unittest.log` : 597 tests verts, Python 3.12, locale `fr_CA.UTF-8`, configuration
  et dossiers XDG isolés ; comprend `test_stale_server.py` préexistant non suivi.

La suite complète se relance avec le lanceur d'isolation existant :

```bash
python3 docs/archives/audit-linux-2026-09-19/run-tests.py
```

Elle requiert l'autorisation d'ouvrir des sockets localhost pour ses serveurs
temporaires. Aucun serveur personnel n'est utilisé. Ces preuves ne remplacent
pas la validation sur matériel Mac du lanceur, des permissions et de l'insertion.
