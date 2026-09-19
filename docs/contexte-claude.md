# Contexte Claude repris pour les agents

Import du 19 septembre 2026, à la demande d'Alexandre. Les fichiers Claude
d'origine sont conservés. `AGENTS.md` relie désormais les consignes communes
aux agents qui travaillent sur ce dépôt.

## Sources examinées

| Source | Traitement |
| --- | --- |
| `CLAUDE.md` du dépôt | Consignes intégralement applicables par référence dans `AGENTS.md` ; aucune duplication. |
| `tasks/lessons.md`, `tasks/todo.md` | Leçons, choix d'usage et suivi conservés comme sources communes. |
| `PRODUCT.md`, `DESIGN.md`, `.impeccable/design.json`, `CONTRIBUTING.md` | Références produit, design et contribution déjà présentes ; leur lecture reste liée à la tâche. |
| `.claude/session-state.md` | Relais ancien consacré au Mac, daté du 25 juillet ; son « prochain lot » ne définit pas la tâche actuelle. |
| `.claude/mac-validation/` et `docs/archives/confront-*` | Preuves et explorations historiques, consultables quand le sujet le nécessite ; pas des instructions nouvelles. |
| `~/.claude/CLAUDE.md` et son import `~/.claude/RTK.md` | Préférences transposables reprises ci-dessous ; mécanismes propres à Claude distingués. |
| `~/.claude/projects/-home-alexandre-Apps-coding-Aparte/memory/MEMORY.md` et ses trois notes | Contexte des deux installations, de Syncthing et du Mac repris ci-dessous. |

Les transcriptions brutes de conversations ne sont ni recopiées ni élevées au
rang d'instructions. Elles peuvent contenir des décisions anciennes remplacées
par les fichiers du projet, ainsi que du contenu personnel.

## Préférences générales transposées

- Alexandre maîtrise le développement d'interface ; ne pas réexpliquer HTML,
  CSS ou JavaScript. Éviter les anglicismes et traduire les conséquences des
  notions techniques nécessaires. Les questions portent sur l'usage et les
  effets attendus, pas sur une accumulation de termes d'architecture.
- Réfléchir avant de coder, expliciter les hypothèses, choisir la solution
  simple qui résout le problème. Modifications ciblées, style existant,
  aucun nettoyage ou changement voisin sans nécessité.
- Vérifier avant d'affirmer, y compris dans un brouillon. Ne jamais présenter
  une lecture du code comme un test réel, une simulation comme un incident
  observé, ni une preuve d'un environnement comme une preuve d'un autre.
  Les proportions (« souvent », « la plupart ») exigent aussi une mesure.
- Déléguer les vérifications indépendantes et exiger fichiers, lignes et
  scénario. L'agent principal recoupe les conclusions.
- Toute création ou modification de design passe par le skill `impeccable`
  et les fondations du projet. Les audits peuvent employer le skill spécialisé.
- Pour un texte destiné à un client ou au public, la consigne Claude demande
  une passe `humanize`. Vérifier la disponibilité du skill au moment concerné ;
  ne pas prétendre l'avoir exécuté s'il manque. Le présent audit est un document
  de travail interne avec Alexandre.
- Avant de conclure qu'aucun navigateur automatisable n'est disponible, vérifier
  le cache `~/.cache/ms-playwright/`, les bibliothèques `playwright-core` et
  `/usr/bin/brave-browser`. Leur absence dans `PATH` ne suffit pas.
- Messages Git en Conventional Commits, sans attribution à une IA. Ne pas
  commiter automatiquement des changements sans rapport avec la tâche.
- À une reprise de session, conserver objectif, périmètre, autorisations,
  modifications, preuves et questions ouvertes ; ne pas réinitialiser le travail.

## Deux copies et synchronisation

Les notes Claude décrivaient `~/murmur` comme l'installation réelle d'un portable
et `~/Apps-coding/Aparte` comme l'arbre synchronisé. **Les deux copies et leur
rôle ont été confirmés sur le poste accessible le 19 septembre**, indépendamment
de l'étiquette « portable » de cette note :

- le processus résident et le raccourci `<Super>space` utilisent
  `~/murmur/.venv/bin/python -m aparte` ;
- le fichier d'installation éditable pointe vers `~/murmur/src` ;
- l'autostart pointe vers ce même environnement ;
- le clone installé est sur `main`, commit `721b098`, version déclarée `1.1.5` ;
- l'arbre de travail courant est sur `feat/portage-macos`, commit `c346b3e`,
  version déclarée `1.1.3` ; sa référence locale `main` est `ce56ce5`.

Ce sont des observations datées, à rafraîchir avant déploiement. L'historique
Claude explique que Syncthing propage les fichiers d'`Apps-coding` mais exclut
`.git`. Cette règle de synchronisation n'a pas été réauditée durant cette tâche.
Éviter un changement de branche ou une restauration globale dans l'arbre partagé.
En cas de réparation Git, diagnostiquer séparément fichiers et index ; ne pas
exécuter mécaniquement les anciennes recettes de `git reset`/`checkout`.

Les noms des remotes diffèrent : `Murmur` est le suivi courant du dépôt de
développement ; `origin` celui du clone installé. Ne pas généraliser la note
ancienne qui nommait le remote de développement `Aparte`.

## Contexte Mac conservé, hors périmètre actuel

Alexandre veut une installation Mac aussi simple que possible. Ce choix reste
pertinent si le portage reprend. La note mémoire ancienne posait encore le
compte Apple comme arbitrage ; `CLAUDE.md` et les plans M7 contiennent des
décisions ultérieures. Reprendre les faits actuels avant de rouvrir cette question.
Ne pas poursuivre M6/M7 parce qu'un ancien relais de session le propose.

## Mécanismes propres à Claude

Les hooks RTK, les noms de modèles Sonnet/Opus/Haiku/Fable, le protocole
`observer`, les titres ajoutés aux transcriptions Claude et ses emplacements
de mémoire ne sont pas des mécanismes Codex. Leur intention utile est reprise
ci-dessus ; leur exécution n'est pas simulée. Aucun hook, plugin, modèle ou
registre global n'a été installé ou modifié par cet import.

Les consignes de la session et les permissions de l'environnement restent
prioritaires sur les instructions importées. Les mémoires globales de Codex
n'ont pas été modifiées.
