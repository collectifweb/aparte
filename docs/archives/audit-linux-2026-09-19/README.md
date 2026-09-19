# Reproductions de l'audit Linux

Scripts d'investigation du 19 septembre 2026, avec données synthétiques.
Ils exposent les défauts observés, ce ne sont pas encore des tests de régression
attendant un fonctionnement corrigé. Ils peuvent cesser de reproduire après
un correctif. Exécuter depuis la racine du dépôt.

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 docs/archives/audit-linux-2026-09-19/micro-linux.py
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 docs/archives/audit-linux-2026-09-19/session-races.py
PYTHONDONTWRITEBYTECODE=1 python3 docs/archives/audit-linux-2026-09-19/backend.py .
node docs/archives/audit-linux-2026-09-19/interface.cjs
```

- `micro-linux.py` : faux refus de périphérique, fermeture du tray, état erroné,
  perte de capture sur erreur. Les enfants Python simulent seulement des
  processus d'enregistrement ; ils n'ouvrent pas de périphérique.
- `session-races.py` : double arrêt et enfant oublié si publication impossible.
- `backend.py <clone>` : hôte étranger, verrou conservé, configuration tronquée
  et concurrence d'historique. Handlers HTTP appelés directement, sans socket.
- `interface.cjs` : vrais gestionnaires JS, navigateur simulé ; accepte en
  second argument une copie d'une autre version de `app.js` pour comparaison.

Pour comparer avec la référence Git locale `main`, sans changer de branche :

```bash
aparte_main_js=$(mktemp /tmp/aparte-main-js.XXXXXX)
git show main:src/aparte/assets/app.js > "$aparte_main_js"
node docs/archives/audit-linux-2026-09-19/interface.cjs "$aparte_main_js"
```

Suite existante avec isolation des chemins utilisateur et locale française :

```bash
python3 docs/archives/audit-linux-2026-09-19/run-tests.py
```

Cette dernière commande nécessite des sockets localhost pour les tests du
serveur et une locale `fr_CA.UTF-8`. Elle place les résultats dans un dossier
`/tmp/aparte-audit-tests-*` dont elle affiche le chemin. Le passage vérifié durant
l'audit compte 597 tests, tous verts. Les scripts ne contiennent ni audio ni
transcription de l'utilisateur.
