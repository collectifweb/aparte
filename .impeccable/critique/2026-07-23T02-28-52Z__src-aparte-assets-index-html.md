---
target: tiroir des Réglages
total_score: 20
p0_count: 0
p1_count: 3
timestamp: 2026-07-23T02-28-52Z
slug: src-aparte-assets-index-html
---
⚠️ DEGRADED: single-context (les sous-agents sont interdits par la consigne de session ; Assessment A et B ont été menés en séquence dans le même contexte)

## Santé du design — 20/40, « Acceptable »

| # | Heuristique | Note | Problème principal |
|---|---|---|---|
| 1 | Visibilité de l'état | 2 | L'enregistrement se confirme, mais aucun champ ne dit s'il a été compris. Une ligne de vocabulaire mal écrite disparaît sans un mot. |
| 2 | Langage de l'utilisateur | **1** | « Calcul », « Moteur de polish », « Snippets », « Remplacements », « Nettoyage », « Texte court » : six libellés sur quinze nomment le mécanisme, pas l'intention. |
| 3 | Contrôle et liberté | 3 | Échap ferme, Annuler existe, le focus est piégé proprement. Mais Annuler jette quarante lignes de dictionnaire sans demander. |
| 4 | Cohérence | 2 | Tout est en contrôle natif, sauf le vocabulaire — deux zones de texte à syntaxe maison. Et les groupes pèsent de 1 à 7 champs. |
| 5 | Prévention des erreurs | **1** | `textToKv` ignore toute ligne sans `=` (app.js:354). Écrire « cloud : Claude » perd l'entrée, sans erreur, sans trace. |
| 6 | Reconnaître plutôt que se souvenir | 2 | La convention « slash nom » ne se rappelle nulle part au moment de dicter. Il faut rouvrir les Réglages et relire sa propre liste. |
| 7 | Souplesse et efficacité | 3 | Clavier complet, et la zone de texte permet de coller une liste entière d'un coup — vraie qualité pour qui en a beaucoup. |
| 8 | Sobriété | 2 | Visuellement propre, mais quinze contrôles de poids identique dans une seule colonne, dont un groupe de sept. |
| 9 | Récupération d'erreur | **1** | En cas d'échec d'enregistrement, le message brut s'écrit dans la ligne d'état de la page — c'est-à-dire **derrière le tiroir ouvert**. |
| 10 | Aide et documentation | 3 | Le vrai point fort : presque chaque champ porte une aide concrète, avec exemple chiffré. Au-dessus de la moyenne du genre. |
| **Total** | | **20/40** | **Acceptable — des améliorations sérieuses avant que l'utilisateur soit content** |

## Verdict anti-patterns

**Analyse déterministe** : `detect.mjs` sur `index.html` ne remonte **rien** (sortie 0, tableau vide). Aucun dégradé, aucun sur-titre en petites majuscules, aucune grille de cartes, aucun texte en dégradé. Le système visuel du projet tient.

**Analyse humaine** : ça ne ressemble pas à de l'IA. Le tiroir est sobre, les contrôles sont natifs, les textes d'aide sont écrits par quelqu'un qui connaît le produit. Le problème n'est pas esthétique — il est d'organisation et de vocabulaire.

**Navigateur** : pas d'inspection visuelle. Aucun outil d'automatisation de navigateur n'est installé sur ce poste, et en installer un pour cette revue n'était pas justifié. Le diagnostic repose donc sur la source et sur l'analyse déterministe.

## Impression générale

Un panneau bien fait qui a grandi sans plan. Chaque réglage a été ajouté correctement, avec son aide, à l'endroit qui semblait logique **au moment où il a été ajouté**. Le résultat cumulé est une liste de quinze contrôles de poids égal, où le plus personnel — le dictionnaire — est tout en bas, et où le plus dangereux — « Calcul » — est à hauteur d'yeux.

La plus grande occasion tient en une phrase : **ces quinze réglages ne sont pas de même nature, et les traiter comme s'ils l'étaient est la racine de tout le reste.**

## Ce qui marche

**Les textes d'aide.** « vingt-deux personnes » devient « 22 personnes ». « Les terminaux ignorent Ctrl+V. » « Deux sons courts : un aigu quand le micro s'ouvre. » Concrets, avec exemples, sans langue de bois. C'est rare et il ne faut rien en perdre dans la restructuration.

**L'état vide du micro.** Quand aucune entrée n'est détectée, le champ le dit, explique la conséquence exacte (« le bouton Parler fonctionne quand même, le raccourci global non ») et pointe vers le diagnostic. C'est le modèle à suivre pour les autres champs.

**Le clavier.** Échap ferme, Tab reste enfermé, le focus revient au bouton déclencheur. Fait, et bien fait.

## Problèmes prioritaires

### [P1] « Remplacements » nomme le mécanisme, pas l'intention

Les entrées réelles d'Alexandre disent toutes la même chose : `cloud = Claude`, `bobbi = Bobby`, `play right = Playwright`, `way land = Wayland`, `mail poète = Mailpoet`, `CPI = CPA`. Aucune n'est un « remplacement » au sens général. Toutes sont le même geste : **Whisper a mal entendu un nom propre, je lui apprends l'orthographe.**

C'est un dictionnaire personnel — le mot qu'Alexandre a employé lui-même. « Remplacements » et « dit = écrit » obligent l'utilisateur à penser en substitution de chaîne alors qu'il pense « Aparté écrit *cloud* alors que je dis *Claude* ».

**Correctif** : renommer en **Dictionnaire**, et remplacer la syntaxe `clé = valeur` par deux colonnes avec de vrais en-têtes — **« Aparté entend »** → **« Écris plutôt »**. Le sens devient directionnel et ne s'explique plus.

### [P1] Une ligne mal écrite est perdue en silence

`textToKv` (app.js:354) fait `if (i === -1) continue`. Une ligne sans `=` n'est ni sauvée, ni signalée. L'utilisateur ferme le tiroir en croyant avoir ajouté un mot, et découvre trois dictées plus tard que rien n'a changé — sans jamais pouvoir relier les deux.

**Correctif** : refuser l'enregistrement en pointant la ligne fautive, ou passer à des champs par entrée où la question ne se pose plus.

### [P1] « Snippets » est un anglicisme dans une interface française

Le projet interdit les anglicismes ; « Snippets » en est un, en toutes lettres, dans le libellé. Et « nom = texte, dit "slash nom" » demande de deviner trois choses à la fois : qu'il faut prononcer le mot « slash », que « nom » est un mot qu'on choisit, et que le texte peut faire plusieurs lignes.

**Correctif** : **Raccourcis dictés**, avec la phrase complète en en-tête de colonne — « Quand je dis **slash …** » → « … écris ceci ».

### [P2] Quinze contrôles de poids égal, dont un groupe de sept

Le groupe « Mise en forme » porte sept champs d'affilée, très au-delà des quatre que la mémoire de travail retient. Six failles sur huit à la grille de charge mentale : pas de foyer unique, pas de découpage, pas de hiérarchie visuelle, pas de dévoilement progressif.

Et le classement dessert l'usage : on choisit son micro une fois dans sa vie, on enrichit son dictionnaire toutes les semaines. C'est le micro qui est en haut.

**Correctif** : classer par fréquence d'usage réelle, et replier ce qui ne se touche presque jamais dans un `<details>` natif — pas d'onglet maison, pas de JavaScript, le clavier et le lecteur d'écran fonctionnent gratuitement.

### [P2] « Nettoyage » ne dit pas ce qu'il nettoie

`cleanup_level` supprime les hésitations — « euh », « heu », « um », « uh », et davantage au niveau élevé (polish.py:154). Le mot « Nettoyage » avec « Léger / Moyen / Élevé » ne le laisse deviner à personne, et il n'y a pas de texte d'aide sous ce champ, contrairement à ses voisins.

**Correctif** : **Suppression des hésitations**, et une aide qui donne l'exemple, comme les autres champs le font déjà.

### [P3] Un échec d'enregistrement s'affiche derrière le tiroir

Le gestionnaire de « Enregistrer » fait `status(String(err), "error")`. La ligne d'état est dans la page principale, sous le voile du tiroir modal. Un utilisateur qui échoue à sauver reste devant un tiroir qui ne réagit pas, avec le message caché derrière.

**Correctif** : afficher l'erreur dans le pied du tiroir, à côté du bouton qui vient d'échouer.

## Signaux par persona

**Jordan, qui découvre.** Ouvre les Réglages, lit « Calcul : Auto (GPU si dispo, sinon CPU) » en troisième position et se demande s'il doit y toucher. Arrive en bas sur « Snippets », un mot anglais, une syntaxe à deviner, aucun exemple visible dans le champ vide — et referme sans rien poser. La fonctionnalité la plus utile du panneau ne lui sera jamais accessible.

**Riley, qui teste les bords.** Tape `cloud : Claude` avec deux-points. Enregistre. Aucune erreur. Rouvre : la ligne a disparu. Recommence avec une flèche : pareil. Conclut que le champ est cassé, alors qu'il attend simplement un signe égal que rien n'annonce dans un champ vide.

**Sam, au lecteur d'écran.** Le tiroir est correct — rôle de dialogue, titre lié, focus piégé, Échap actif. Mais les deux zones de vocabulaire s'annoncent « Remplacements, zone de texte » : ni la syntaxe attendue, ni le format, ni un exemple ne sont rattachés au champ. L'aide est dans un `<small>` voisin, pas dans un `aria-describedby`.

## Observations mineures

- « Modèle par défaut » et le sélecteur de modèle de la page principale portent des noms différents pour deux choses liées ; l'aide de la page l'explique, celle des Réglages non.
- Les groupes « Insertion » et « Historique » ont un champ chacun : deux titres pour deux lignes.
- Aucun champ n'indique sa valeur par défaut. Après avoir tout changé, on ne sait pas comment revenir.
- Le pied du tiroir dit « Annuler / Enregistrer » alors que rien n'indique qu'une modification est en cours. Le bouton « Enregistrer » est actif même quand rien n'a bougé.

## Questions à se poser

- Et si le dictionnaire n'était pas dans les Réglages du tout, mais accessible depuis l'éditeur — au moment précis où on voit Aparté écrire un mot de travers ?
- Est-ce que « Calcul », « Modèle » et « Moteur de mise en forme » ont leur place devant quelqu'un qui vient dicter, ou est-ce que leur vraie maison est le panneau Diagnostic, qui parle déjà d'installation ?
- Combien de ces quinze réglages Alexandre a-t-il changés depuis juin ? Ceux qu'on n'a jamais touchés ne méritent pas la même hauteur d'écran que le dictionnaire.
