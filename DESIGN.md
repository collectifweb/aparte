---
name: Aparté
description: Dictée vocale locale pour Linux, qui écrit un français correct
colors:
  bg-light: "oklch(1 0 0)"
  bg-dark: "oklch(0.190 0.010 15)"
  surface-light: "oklch(0.982 0.004 15)"
  surface-dark: "oklch(0.235 0.011 15)"
  surface-2-light: "oklch(0.960 0.006 15)"
  surface-2-dark: "oklch(0.282 0.012 15)"
  line-light: "oklch(0.902 0.007 15)"
  line-dark: "oklch(0.335 0.014 15)"
  ink-light: "oklch(0.235 0.014 15)"
  ink-dark: "oklch(0.955 0.005 15)"
  ink-soft-light: "oklch(0.455 0.016 15)"
  ink-soft-dark: "oklch(0.742 0.014 15)"
  ink-disabled-light: "oklch(0.550 0.014 15)"
  ink-disabled-dark: "oklch(0.620 0.014 15)"
  brand-light: "oklch(0.520 0.185 5)"
  brand-dark: "oklch(0.700 0.160 5)"
  brand-fill: "oklch(0.520 0.185 5)"
  on-brand: "oklch(1 0 0)"
  record-rest-light: "oklch(0.235 0.014 15)"
  record-rest-dark: "oklch(0.510 0.016 15)"
  ok-light: "oklch(0.500 0.100 155)"
  ok-dark: "oklch(0.760 0.130 155)"
  warn-light: "oklch(0.550 0.110 75)"
  warn-dark: "oklch(0.800 0.120 75)"
  danger-light: "oklch(0.480 0.170 28)"
  danger-dark: "oklch(0.660 0.170 28)"
typography:
  transcript:
    fontFamily: "Georgia, Liberation Serif, DejaVu Serif, Times New Roman, serif"
    fontSize: "18px"
    fontWeight: 400
    lineHeight: 1.65
  wordmark:
    fontFamily: "ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, sans-serif"
    fontSize: "18px"
    fontWeight: 700
    lineHeight: 1.2
    letterSpacing: "-0.01em"
  headline:
    fontFamily: "ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, sans-serif"
    fontSize: "18px"
    fontWeight: 700
    lineHeight: 1.3
  action:
    fontFamily: "ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, sans-serif"
    fontSize: "16px"
    fontWeight: 600
    lineHeight: 1.2
    letterSpacing: "0.01em"
  ui:
    fontFamily: "ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, sans-serif"
    fontSize: "14px"
    fontWeight: 400
    lineHeight: 1.4
  label:
    fontFamily: "ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, sans-serif"
    fontSize: "13px"
    fontWeight: 700
    lineHeight: 1.3
    letterSpacing: "0.05em"
  caption:
    fontFamily: "ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, sans-serif"
    fontSize: "12px"
    fontWeight: 400
    lineHeight: 1.4
  mono:
    fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace"
    fontSize: "13px"
    fontWeight: 400
    lineHeight: 1.5
rounded:
  sm: "6px"
  md: "10px"
  lg: "14px"
  full: "999px"
spacing:
  "1": "4px"
  "2": "8px"
  "3": "12px"
  "4": "16px"
  "5": "20px"
  "6": "24px"
  "8": "32px"
  "12": "48px"
components:
  record-button:
    backgroundColor: "{colors.record-rest-light}"
    textColor: "{colors.on-brand}"
    typography: "{typography.action}"
    rounded: "{rounded.full}"
    size: "168px"
  record-button-recording:
    backgroundColor: "{colors.brand-fill}"
    textColor: "{colors.on-brand}"
    typography: "{typography.action}"
    rounded: "{rounded.full}"
    size: "168px"
  editor:
    backgroundColor: "{colors.surface-light}"
    textColor: "{colors.ink-light}"
    typography: "{typography.transcript}"
    rounded: "{rounded.lg}"
    padding: "16px 20px"
  chip:
    backgroundColor: "{colors.surface-light}"
    textColor: "{colors.ink-light}"
    typography: "{typography.ui}"
    rounded: "{rounded.md}"
    padding: "8px 16px"
  chip-ghost:
    backgroundColor: "{colors.surface-light}"
    textColor: "{colors.ink-soft-light}"
    typography: "{typography.ui}"
    rounded: "{rounded.md}"
    padding: "8px 16px"
  button-primary:
    backgroundColor: "{colors.brand-fill}"
    textColor: "{colors.on-brand}"
    typography: "{typography.ui}"
    rounded: "{rounded.md}"
    padding: "9px 16px"
  button-ghost:
    backgroundColor: "{colors.surface-light}"
    textColor: "{colors.ink-soft-light}"
    typography: "{typography.ui}"
    rounded: "{rounded.md}"
    padding: "9px 16px"
  topbar-button:
    backgroundColor: "transparent"
    textColor: "{colors.ink-soft-light}"
    typography: "{typography.ui}"
    rounded: "{rounded.md}"
    padding: "7px 12px"
  drawer:
    backgroundColor: "{colors.surface-light}"
    textColor: "{colors.ink-light}"
    width: "460px"
  pill:
    backgroundColor: "transparent"
    textColor: "{colors.ink-soft-light}"
    typography: "{typography.caption}"
    rounded: "{rounded.full}"
    padding: "4px 12px"
---

# Design System: Aparté

<!-- Décrit l'interface livrée (src/aparte/assets/). Tous les couples texte/fond
     sont calculés, pas estimés : voir tasks/todo.md, section « Lot D ». -->

## 1. Overview — Vue d'ensemble

**Creative North Star : « L'aparté »**

Au théâtre, un aparté est ce qu'un personnage dit à voix basse, en se tournant
vers la salle, pendant que la scène continue. Trois choses en découlent, et
elles tiennent tout le système.

**La scène.** Une surface calme qui ne demande rien : blanc pur en thème clair,
brun très sombre en thème sombre, des filets de 1 px, aucune carte, aucune ombre
décorative. Au repos, le bouton d'enregistrement est un disque d'encre : présent,
massif, silencieux.

**Le projecteur.** Une seule couleur saturée, le carmin, et une seule chose a le
droit de la porter en grand : le bouton pendant que le micro est ouvert. C'est la
seule information que l'utilisateur cherche quand il jette un œil à l'écran, et
elle se lit en périphérie, sans lire. Ailleurs le carmin n'existe qu'à petite
échelle : l'anneau de focus, la case cochée, le bouton « Enregistrer », le logo.

**Le programme imprimé.** Le texte dicté est composé en sérif, pas dans la police
d'interface. C'est le produit fini et la seule vitrine de l'argument français : on
doit voir les `« »`, l'apostrophe courbe et l'espace avant `;` et `?`. Le châssis
reste en sans-serif système, invisible, natif.

Le registre est **produit** : l'interface sert la tâche, elle ne se vend pas. La
personnalité chaleureuse annoncée dans PRODUCT.md passe par les mots (tutoiement,
messages d'état), jamais par les formes. Ce système rejette explicitement le SaaS
générique à dégradé et l'utilitaire Linux austère, les deux anti-références de
PRODUCT.md : il n'a aucun dégradé, et il a exactement une couleur.

**Key Characteristics :**

- Un écran unique, sans navigation, où un seul élément domine : le disque de
  168 px, presque quatre fois la hauteur de tous les autres contrôles.
- Deux thèmes complets pilotés par `prefers-color-scheme`, sans bascule manuelle :
  l'application suit le thème du bureau, comme les autres applications Cinnamon.
- Deux familles, sur un axe de contraste : sérif pour le texte de l'utilisateur,
  sans-serif système pour l'interface. Plus une monospace pour les commandes.
- Aucune police d'affichage, aucune taille fluide, aucun `clamp()`. Tout tient
  entre 12 et 18 px.
- Colonne centrale de 680 px, tiroirs de 460 px ancrés à droite.
- Aucun assemblage : HTML, CSS et JS écrits à la main, servis en fichiers
  statiques. Toute proposition qui exige une étape de compilation, une
  bibliothèque ou une police distante est irrecevable.

## 2. Colors — Couleurs

Une palette **restreinte** : des neutres teintés vers le carmin, une seule
couleur de marque, trois couleurs d'état. Aucun dégradé nulle part.

### Primary

- **Carmin de scène** (`brand-fill`, `oklch(0.520 0.185 5)`) : l'aplat. Bouton
  d'enregistrement pendant l'enregistrement, bouton « Enregistrer », bouton
  « Copier » des blocs de commande, logo. **La même valeur dans les deux
  thèmes**, toujours avec du blanc dessus (6,11:1).
- **Carmin de texte** (`brand`, clair `oklch(0.520 0.185 5)` / sombre
  `oklch(0.700 0.160 5)`) : anneau de focus, cases cochées, tout carmin qui n'est
  pas un aplat. La variante sombre est éclaircie pour rester lisible sur le fond
  (6,41:1) ; elle ne doit jamais servir d'aplat.

### Neutral

- **Encre** (`ink`, clair `oklch(0.235 0.014 15)` / sombre `oklch(0.955 0.005 15)`) :
  tout le texte de premier plan, et les messages d'état. 16,7:1 en clair,
  16,2:1 en sombre.
- **Encre atténuée** (`ink-soft`, clair `oklch(0.455 0.016 15)` / sombre
  `oklch(0.742 0.014 15)`) : textes d'aide, légendes, en-têtes de groupe,
  placeholder, boutons fantômes au repos. Jamais sous 6,3:1, y compris à 12 px
  sur les blocs en creux.
- **Encre désactivée** (`ink-disabled`, clair `oklch(0.550 0.014 15)` / sombre
  `oklch(0.620 0.014 15)`) : le libellé d'un contrôle inactif, et rien d'autre.
  4,63:1 en clair, 4,56:1 en sombre — au-dessus du seuil, donc lisible, et
  franchement en dessous de l'encre atténuée (7:1), donc l'état se voit.
- **Fond** (`bg`, blanc pur en clair, `oklch(0.190 0.010 15)` en sombre) : la page.
  Le blanc est un vrai blanc, sans chaleur cachée.
- **Surface** (`surface`) : barre supérieure, tiroirs, éditeur, puces, champs.
- **Creux** (`surface-2`) : blocs de commande, survols, code en ligne.
- **Filet** (`line`) : bordures de 1 px, séparateurs.

Les neutres portent 0,004 à 0,016 de chroma vers la teinte 15, à mi-chemin du
carmin. Assez pour que le gris ne soit pas mort, trop peu pour se voir seul.

### Tertiary — états

- **Vert** (`ok`) : diagnostic conforme, pastille de santé au vert.
- **Ambre** (`warn`) : diagnostic non essentiel manquant, santé partielle.
- **Rouge orangé** (`danger`, teinte 28) : diagnostic essentiel manquant, badge
  « requis », messages d'erreur. Volontairement tenu à 23° du carmin (teinte 5) :
  l'un est froid et rosé, l'autre chaud et orangé, ils ne se confondent pas.

Le texte posé sur un aplat d'état suit `on-state` : blanc en clair, la couleur de
fond en sombre. Un `✓` blanc sur un vert clair de thème sombre serait illisible.

### Named Rules

**La règle du projecteur.** Une seule chose à l'écran a le droit d'être saturée à
grande échelle : le bouton d'enregistrement, et seulement pendant que le micro est
ouvert. Aucun autre bloc, aucune carte, aucun en-tête ne prend un aplat de
couleur, sous aucun prétexte. Si deux aplats saturés coexistent, l'information
« ça enregistre » est perdue.

**La règle du daltonien.** L'état d'enregistrement se lit sans la couleur : le
pictogramme passe du micro au carré d'arrêt, le libellé passe de « Parler » à
« Arrêter », l'anneau se met à pulser. Toute évolution de cet état conserve au
moins deux de ces trois signaux non chromatiques. Même règle pour la pastille de
santé, doublée d'un texte lu par les lecteurs d'écran.

**La règle de l'état éteint.** Un contrôle désactivé change de teinte, jamais
d'opacité. `opacity` mélange le libellé au fond de la **page**, pas à celui du
contrôle : en thème clair, une encre à 0,45 tombe à 1,69:1, illisible, et il
faudrait monter à 0,85 pour repasser le seuil — c'est-à-dire ne plus rien
éteindre du tout. `ink-disabled` fait les deux à la fois. Corollaire : un bouton
primaire désactivé rend son aplat carmin et redevient une surface neutre.

**La règle du calcul.** Aucune couleur n'entre dans le système sans que son
contraste ait été calculé contre les fonds sur lesquels elle sera posée. Le seuil
est 4,5:1, y compris à 12 px, y compris pour un libellé sur un aplat. « Ça a l'air
lisible » n'est pas une vérification.

## 3. Typography — Typographie

**Police du texte dicté :** `Georgia, "Liberation Serif", "DejaVu Serif",
"Times New Roman", serif`. Une pile système, donc aucun fichier à télécharger.

**Police d'interface :** `ui-sans-serif, system-ui, -apple-system, "Segoe UI",
Roboto, sans-serif`. Sous Cinnamon, Ubuntu ou Cantarell selon la distribution.

**Police monospace :** `ui-monospace, SFMono-Regular, Menlo, monospace`, pour les
commandes shell copiables et les tables `dit = écrit`.

**Police d'affichage :** aucune, et c'est délibéré. Un outil dans lequel on passe
la journée n'a pas de titre à déclamer.

**Caractère :** l'appariement est sur un axe de contraste franc, sérif contre
sans-serif géométrique-système. Ce n'est pas une décoration : c'est la seule
manière de rendre visible ce que l'application fabrique. Le châssis disparaît, le
texte apparaît.

### Hierarchy

- **Transcript** (400, 18 px, interligne 1,65, sérif) : contenu de l'éditeur.
  La colonne de 680 px maintient la ligne autour de 70 caractères.
- **Wordmark** (700, 18 px, `-0.01em`) : « Aparté ». Seul interlettrage négatif.
- **Headline** (700, 18 px) : titre de tiroir. Un seul par tiroir.
- **Action** (600, 16 px, `0.01em`) : libellé du bouton d'enregistrement.
  Le seul texte de 16 px de l'interface.
- **UI** (400, 14 px) : puces, boutons, champs, libellés de réglage, messages
  d'état, libellés de diagnostic (500). Le corps de travail de l'écran.
- **Label** (700, 13 px, majuscules, `0.05em`) : en-têtes de groupe des tiroirs
  et catégories de diagnostic.
- **Caption** (400, 12 px) : textes d'aide, détails de diagnostic, pastilles,
  badge « requis » (11 px).
- **Mono** (400, 13 px/1,5 en zone de texte, 12 px/1,4 en bloc de commande).

### Named Rules

**La règle des deux voix.** La sérif est réservée au texte de l'utilisateur :
l'éditeur, et rien d'autre. Un libellé de bouton, un titre de tiroir ou un message
d'état en sérif brouille la seule distinction que ce système fait vraiment — ce
que l'application dit, contre ce que l'utilisateur a dicté.

**La règle des 18 px.** Rien ne dépasse 18 px. Un nouvel écran qui a besoin d'un
titre plus gros a en réalité besoin d'être découpé autrement. Tailles fixes,
jamais fluides : l'utilisateur regarde toujours cet écran à la même distance.

**La règle des majuscules réservées.** Les majuscules espacées sont l'affaire des
en-têtes de groupe **à l'intérieur des tiroirs**, et de rien d'autre. Un sur-titre
en petites majuscules au-dessus d'une section de l'écran principal est interdit :
c'est le tic de mise en page des pages d'accueil.

## 4. Elevation — Élévation

Le système est **plat par défaut**. La profondeur est portée par la superposition
tonale (fond → surface → creux) et par des filets de 1 px. Une seule ombre,
`--shadow`, sur exactement deux éléments : le disque d'enregistrement, parce qu'il
doit se donner à presser, et le tiroir, parce qu'il survole réellement la page.

Le voile des tiroirs assombrit la page pendant qu'un tiroir est ouvert, dans les
deux thèmes.

Les plans sont nommés : barre supérieure `10`, voile `100`, tiroir `110`. Les
notifications et infobulles à venir se placent au-dessus de 110.

### Shadow Vocabulary

- **`--shadow`** (`0 8px 24px oklch(0.235 0.014 15 / 0.14)` en clair,
  `0 10px 30px oklch(0 0 0 / 0.45)` en sombre) : unique ombre du système.
- **`--scrim`** (`oklch(0.235 0.014 15 / 0.45)` en clair,
  `oklch(0.120 0.010 15 / 0.62)` en sombre) : voile des tiroirs.

### Named Rules

**La règle du champ à plat.** Une ombre portée sur un champ de saisie fait flotter
quelque chose qui est en creux dans la page. L'ombre appartient à ce qui survole,
jamais à ce qui reçoit du texte. L'éditeur n'en a pas.

**Test d'audit en une phrase.** Si un bloc a une ombre **et** une bordure **et**
un fond différent du fond de page, deux de ces trois signaux sont de trop.

## 5. Components — Composants

Chaque élément interactif porte : repos, survol, focus, désactivé. Le focus est le
même partout — `outline: 2px solid var(--brand)`, décalé de 2 px — et il n'est
jamais redéfini par composant, ni accompagné d'un `border-radius` qui déformerait
l'élément pendant le focus.

### Bouton d'enregistrement (composant signature)

Le seul élément mémorable du système, et le seul autorisé à l'être.

- **Forme :** disque de 168 px, sans bordure, pictogramme puis libellé en colonne.
- **Repos :** aplat `record-rest` — encre en thème clair, brun moyen en thème
  sombre, pour rester une forme distincte du fond dans les deux cas (3,1:1 au
  minimum). Micro de 52 px et libellé « Parler » en blanc, `--shadow`.
- **Survol :** `translateY(-2px)` en 120 ms. **Enfoncé :** retour à zéro.
- **Enregistrement :** aplat carmin, le micro cède la place à un carré blanc de
  30 px, le libellé passe à « Arrêter », l'anneau extérieur pulse de `scale(1)` à
  `scale(1.35)` en 1,6 s.
- **Traitement :** curseur `progress`, aucun pictogramme, l'anneau tourne à 0,8 s
  par tour, le libellé dit « Un instant… ». Les puces d'action passent en
  désactivé pendant ce temps.

### Puces d'action (`.chip`)

- **Style :** fond surface, filet 1 px, rayon 10 px, `8px 16px`, texte de 14 px.
- **Variante fantôme :** texte en encre atténuée, pour les actions secondaires.
- **Survol :** fond en creux, seulement si la puce n'est pas désactivée.
- **Désactivé :** libellé en `ink-disabled`, curseur `not-allowed`, pas de
  survol. Deux situations, et la seconde est la plus fréquente : pendant le
  traitement, et tant que l'éditeur est vide — Polir, Copier et Insérer n'ont
  alors rien sur quoi travailler. « Importer audio » reste active : c'est elle
  qui remplit l'éditeur.
- **Infobulle :** chaque puce porte un `title` traduit qui dit ce qu'elle fait,
  en particulier « Insérer », dont l'effet — écrire dans l'application de
  devant — ne se devine pas depuis le libellé.

### Boutons (`.btn`, `.ghost-btn`)

- **Primaire :** aplat carmin, texte blanc 600, rayon 10 px. Un seul par tiroir.
  Au survol, `brightness(1.08)`. Désactivé, il perd son aplat pour le creux :
  un carmin plein sur un contrôle inactif garderait sa force d'appel.
- **Fantôme (tiroir) :** fond surface, texte atténué, même géométrie.
- **Fantôme (barre supérieure) :** fond transparent, filet 1 px, `7px 12px`,
  pictogramme de 16 px ou pastille d'état de 9 px. Au survol, le texte passe en
  encre et le fond en creux.

### Champs (`#editor`, `select`, `textarea.kv`)

- **Éditeur :** fond surface, filet 1 px, rayon 14 px, `16px 20px`, sérif 18 px
  interligne 1,65, hauteur `min(38vh, 300px)`, redimensionnable verticalement,
  sans ombre. Le placeholder est explicitement en encre atténuée, jamais laissé
  au gris par défaut du navigateur.
- **Zones de correspondance (`.kv`) :** monospace 13 px, 96 px de haut minimum.
- **Sélecteurs et cases à cocher :** natifs, avec `accent-color` en carmin. La
  flèche reste celle du système — habiller un contrôle standard serait réinventer
  une affordance que l'utilisateur connaît déjà.
- **État vide d'un champ (`.field-empty`) :** quand un champ n'a rien à proposer
  — aucune entrée micro détectée, par exemple — une ligne de 12 px en **encre
  pleine** se glisse au-dessus du texte d'aide permanent, qui reste en encre
  atténuée. C'est ce qui l'en détache, sans couleur : la couleur est réservée
  aux états qui viennent avec un pictogramme.

### Tiroirs

- **Structure :** voile plein écran aligné à droite, panneau de
  `min(460px, 100vw)`, filet gauche, `--shadow`. En-tête / corps défilant / pied.
- **Entrée :** 20 px de translation et opacité 0,6 → 1 en 180 ms.
- **Clavier :** `Échap` ferme, `Tab` reste enfermé dans le tiroir tant qu'il est
  ouvert, le focus entre sur le premier contrôle et revient au bouton déclencheur
  à la fermeture. `aria-modal="true"` et `aria-labelledby` sur le titre traduit.
- **Groupes :** séparés par un filet, en-tête en majuscules 13 px atténuées.

### Liste de diagnostic

Le composant le mieux conçu du système, et le modèle des écrans à venir : il
répond à « qu'est-ce qui manque ? » et à « comment je le répare ? » sur la même
ligne.

- **Ligne :** pastille d'état de 18 px, libellé de 14 px/500, détail de 12 px
  atténué, filet de séparation.
- **Bloc de réparation :** fond creux, filet, rayon 6 px, commande en monospace
  12 px défilant horizontalement, bouton de copie carmin qui affiche « Copié »
  pendant 1,5 s.
- **Pastilles de résumé :** trois capsules, fond transparent, texte et filet
  colorés selon l'état, avec un `✓` ou un `✕` — jamais la couleur seule.

### Barre supérieure

- Logo de 28 px et mot-symbole à gauche ; sélecteur de langue, bouton
  « Configuration » avec pastille d'état, bouton « Réglages » à droite.
- La pastille de santé est doublée d'un texte masqué visuellement, rattaché au
  bouton par `aria-describedby`.

### Plan de travail (`.workspace`) et sa zone réservée

Colonne centrée de 680 px, `flex: 1`, contenu collé en haut : disque, sous-titre,
fil d'état, éditeur, barre d'actions. Il reste **250 à 350 px libres** sous la
barre d'actions sur un écran ordinaire.

**Cet espace est réservé, pas vide par accident.** Il accueillera le panneau
d'historique des dictées. Trois règles s'appliquent à ce qui viendra s'y poser :

- **C'est une liste, jamais une grille de cartes.** Filet de 1 px et fond en
  creux. Le modèle est la ligne de diagnostic : une ligne dit ce qu'elle est et
  porte son action, sans ouvrir de sous-écran.
- **Aucun aplat de couleur.** La règle du projecteur s'applique ici en premier :
  un panneau coloré sous l'éditeur ferait perdre au disque son monopole de la
  couleur, donc sa lisibilité en vision périphérique.
- **Elle reste sous la barre d'actions et ne repousse rien.** Le chemin
  principal — parler, relire, insérer — ne gagne pas d'étape visuelle. Si le
  contenu dépasse, c'est la liste qui défile, pas le document : le disque et
  l'éditeur restent visibles en permanence.

L'état vide de cette zone est la situation normale, pas l'exception : l'historique
vit en mémoire vive, il est donc vide à chaque ouverture de session. Il doit
enseigner plutôt qu'annoncer son propre vide. Deux choses manquent aujourd'hui à
l'interface et lui reviennent : le **raccourci clavier global**, que PRODUCT.md
désigne comme le chemin principal du produit alors qu'une demi-phrase seulement
le mentionne, et la mention **« rien ne sort de la machine »**, premier argument
du produit et aujourd'hui absent de l'écran.

### Motion

150 à 250 ms sur les transitions d'état, courbe `cubic-bezier(0.16, 1, 0.3, 1)`.
Le mouvement dit l'état : pression, pulsation d'enregistrement, rotation de
traitement, entrée de tiroir. Rien d'autre. `prefers-reduced-motion: reduce`
neutralise les quatre animations et laisse les états lisibles à l'arrêt : l'anneau
d'enregistrement reste affiché plein au lieu de pulser.

## 6. Do's and Don'ts

### Do:

- **Do** vérifier chaque couple texte/fond par calcul avant de l'adopter, seuil
  4,5:1, y compris à 12 px et sur les aplats. C'est l'engagement d'accessibilité
  du projet.
- **Do** garder un seul style de focus pour toute l'interface, sans jamais y
  mettre de `border-radius` : l'outline suit déjà le rayon natif de l'élément.
- **Do** écrire chaque nouvelle chaîne dans `i18n.js`, en français **et** en
  anglais, y compris les `aria-label` et les `title`. Un libellé écrit en dur dans
  `index.html` est un bogue.
- **Do** accompagner chaque réglage d'interface de sa commande équivalente, en
  monospace avec un bouton « copier », sur le modèle de `.diag-fix`.
- **Do** encadrer toute animation par `@media (prefers-reduced-motion: reduce)`,
  en laissant l'état lisible à l'arrêt.
- **Do** vérifier tout nouveau composant dans les deux thèmes. Un aplat d'état qui
  passe en clair peut devenir illisible en sombre : c'est le rôle de `on-state`.
- **Do** garder les contrôles natifs natifs. Les `select` et les cases à cocher du
  système sont le bon choix pour un outil de bureau.

### Don't:

- **Don't** utiliser un dégradé, nulle part. C'est l'anti-référence « SaaS
  générique à dégradé » de PRODUCT.md, et c'est ce que l'application portait avant
  juillet 2026 avec l'indigo et le turquoise par défaut de Tailwind.
- **Don't** poser un deuxième aplat saturé à l'écran. Voir « La règle du
  projecteur » : le carmin en grand veut dire que le micro est ouvert.
- **Don't** écrire un message informatif en couleur. Le texte se lit en encre ;
  la couleur qualifie un état et vient alors avec un pictogramme.
- **Don't** utiliser `brand-dark` comme aplat : c'est une valeur éclaircie pour du
  texte sur fond sombre, du blanc dessus tombe sous 4,5:1.
- **Don't** éteindre un contrôle avec `opacity`. Le libellé se mélange au fond de
  la page et tombe sous le seuil ; `ink-disabled` existe pour ça. Voir « La règle
  de l'état éteint ».
- **Don't** laisser une action cliquable quand elle n'a rien sur quoi agir. Une
  puce qui répond « Copié. » sur un éditeur vide ment — et celle-là vidait le
  presse-papiers en le disant.
- **Don't** laisser un placeholder au style par défaut du navigateur.
- **Don't** mettre d'ombre portée sur un champ de saisie.
- **Don't** empiler les cartes. Le système n'en a aucune : un filet de 1 px et un
  fond en creux séparent aussi bien. Le panneau d'historique à venir est une
  liste, pas une grille de cartes.
- **Don't** installer un sur-titre en petites majuscules espacées au-dessus des
  sections de l'écran principal.
- **Don't** composer l'interface en sérif, ni le texte dicté en sans-serif. Voir
  « La règle des deux voix ».
- **Don't** ajouter d'étape de compilation, de bibliothèque, de police distante ou
  de dépendance CDN.
- **Don't** glisser vers le gris sur gris de l'utilitaire système, deuxième
  anti-référence de PRODUCT.md. Il reste une couleur, et elle a un rôle précis.
- **Don't** faire porter une information par la couleur seule.
