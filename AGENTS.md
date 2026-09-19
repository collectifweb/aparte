# Instructions des agents — Aparté

## Sources communes avec Claude

Lire et appliquer **[CLAUDE.md](CLAUDE.md) intégralement** : ses consignes de
projet valent aussi pour Codex et les sous-agents. Ce fichier reste la source
commune ; ne pas en maintenir une seconde copie qui divergerait.

Lire également :

- [tasks/lessons.md](tasks/lessons.md) pour les erreurs à ne pas répéter ;
- [tasks/todo.md](tasks/todo.md), surtout le lot concerné et « À ne pas reprendre » ;
- [docs/contexte-claude.md](docs/contexte-claude.md), qui reprend les préférences
  et le contexte auparavant conservés uniquement dans Claude ;
- [PRODUCT.md](PRODUCT.md) et [DESIGN.md](DESIGN.md) avant tout changement visible ;
- [CONTRIBUTING.md](CONTRIBUTING.md) pour les conventions et les tests.

Les archives de conversations et `.claude/session-state.md` constituent un
historique daté, pas un ordre de reprendre automatiquement leur tâche suivante.
Vérifier les affirmations d'état contre les fichiers et Git actuels.

## Périmètre et environnement

**Linux d'abord, français d'abord.** La demande du 19 septembre 2026 concerne
le produit Linux et ses défauts, malgré la branche `feat/portage-macos`.
Ne pas reprendre le portage macOS sans demande explicite.

Deux copies existent sur le poste vérifié le 19 septembre 2026 :

- `~/Apps-coding/Aparte` : arbre de développement, branche du portage ;
- `~/murmur` : installation Linux réellement utilisée par le raccourci et
  l'autostart, sur `main`, avec un environnement Python installé en mode éditable.

Ces chemins et branches doivent être revérifiés avant une intervention.
Modifier l'arbre de développement ne met pas à jour l'application utilisée.
Ne pas changer de branche dans l'arbre synchronisé par Syncthing pour examiner
`main` : employer `git show`/`git diff`, ou une copie isolée hors synchronisation.
Lire les remotes effectifs plutôt que supposer leur nom sur toutes les machines.

## Méthode de collaboration

- Alexandre préfère que l'agent principal conduise l'analyse et les décisions,
  et délègue les explorations et sous-tâches indépendantes à des sous-agents.
- Distinguer explicitement ce qui est **vérifié par exécution**, **lu dans le
  code ou la documentation**, et **supposé/rapporté**. Une simulation prouve
  son scénario, pas la cause d'un incident réel.
- Expliquer en français concret les conséquences et les choix d'usage.
- Pour un audit, produire des constats sourcés, priorisés et reproductibles.
  L'analyse n'autorise pas une modification de l'installation ni des réglages.
- Préserver les modifications préexistantes. Ne pas supprimer, écouter ou
  transcrire les captures personnelles pendant un diagnostic technique.
- Garder la langue « Auto » : le mélange français/anglais dans une même dictée
  est un choix informé d'Alexandre, documenté dans `tasks/todo.md`.
- Commiter les fichiers de la tâche à chaque étape validée, avec la documentation
  mise à jour dans le même jalon (demande du 19 septembre 2026). Sélectionner
  explicitement les fichiers ; ne pas embarquer les travaux préexistants.

## Vérification sans toucher aux données personnelles

Suite : `PYTHONPATH=src python3 -m unittest discover -s tests -t tests`.
Isoler `APARTE_CONFIG`, `XDG_CONFIG_HOME`, `XDG_DATA_HOME`, `XDG_STATE_HOME`,
`XDG_RUNTIME_DIR` et les caches dans des dossiers temporaires avant de lancer
une suite complète. Ne pas employer l'historique, le presse-papiers, le micro
ou les entrées de démarrage réels dans les tests.

Les tests macOS de libellés supposent actuellement une locale française :
la suite complète a été vérifiée avec `LC_ALL=fr_CA.UTF-8`. Ne pas imposer
globalement `APARTE_RUNTIME_DIR` au lanceur de la suite : cela masque le scénario
du test qui doit vérifier le repli de `XDG_RUNTIME_DIR`.

État des constats et suite proposée :
[audit Linux du 19 septembre 2026](docs/audit-linux-2026-09-19.md).
Mise en œuvre : [plan de fiabilisation Linux](tasks/fiabilisation-linux.md).
