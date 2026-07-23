# Product

## Register

product

## Users

**Le développeur front-end québécois qui dicte toute la journée.**

Il travaille sous Cinnamon, en français, et parle plus vite qu'il ne tape. Sa
journée est faite d'allers-retours entre Slack, sa boîte de courriels et son
éditeur de code. Aparté vit dans une petite fenêtre ou un onglet à côté, ouverte
du matin au soir, qu'il ne regarde que deux secondes à la fois : une fois pour
vérifier que le micro est bien ouvert, une fois pour relire trois phrases avant
de les insérer.

Il connaît le terminal, il n'a pas peur d'une ligne de commande, mais il ne veut
pas y retourner pour changer un réglage. Une commande affichée dans l'interface
avec un bouton « copier » lui convient. Un réglage qui n'existe que dans un
fichier JSON, non.

Ce qu'il essaie de faire : **passer de sa voix à du texte français correct,
inséré dans l'application qu'il a sous les yeux, sans quitter cette
application.** Le raccourci clavier global est le chemin principal ; l'interface
web sert à régler, diagnostiquer et relire.

Cette phrase est un arbitrage, pas une description : **ce qui n'existe que dans
la page web ne sert pas le public principal.** L'aperçu au fil de la parole est
dans ce cas depuis le 22/07 — il ne s'affiche qu'en regardant la page, donc
jamais pendant l'usage normal. C'est ce déséquilibre que le Lot 5B (fenêtre
flottante) doit corriger, et c'est le test à passer avant de poser quoi que ce
soit de nouveau dans la page seule.

Deuxième public, plus rare mais décisif pour le projet : le contributeur qui
ouvre `src/aparte/assets/` pour la première fois. Il n'y a ni compilation ni
bibliothèque, donc il peut modifier un fichier et rafraîchir la page. Cette
contrainte est un choix de produit, pas une limite technique subie.

## Product Purpose

Aparté transforme la parole en texte français **juste**, en local, et l'insère
dans l'application active.

Trois promesses, dans cet ordre :

1. **Rien ne sort de la machine.** Whisper tourne en local, la mise en forme
   aussi (heuristique ou Ollama local). Aucune requête réseau, aucun compte,
   aucune clé d'API.
2. **La typographie française est traitée sérieusement.** Espaces insécables
   avant `? ! ; :`, guillemets `« »`, apostrophe courbe. C'est le seul argument
   qui distingue vraiment Aparté de la concurrence : ce n'est pas l'application
   de dictée la plus riche, c'est celle qui écrit correctement le français.
3. **Linux d'abord.** Presse-papiers Wayland et X11, notifications natives,
   raccourci global posé par l'application elle-même, lanceur de bureau. Pas un
   portage, une cible.

Le succès ressemble à ça : l'utilisateur cesse de remarquer Aparté. Il appuie
sur son raccourci, parle, et le texte arrive correct dans Slack. Il n'ouvre
l'interface que pour changer un réglage ou comprendre pourquoi quelque chose ne
marche pas.

Ce que le produit n'est pas : un assistant conversationnel, un éditeur de texte
complet, un enregistreur audio, un service en ligne.

## Brand Personality

**Chaleureux, humain, accessible, amusant, drôle.**

Voix : le tutoiement, déjà en place dans les textes de l'interface
(« Appuie pour parler »). Phrases courtes. On parle à quelqu'un, pas à un parc
de machines. Jamais de vouvoiement institutionnel, jamais de ton d'assistant IA
enjoué.

L'humour est **dans les mots, jamais dans le décor**. Les messages d'état, les
états vides, les libellés de diagnostic ont le droit d'avoir de l'esprit. Les
formes, les couleurs et les animations n'ont pas ce droit : c'est un outil, il
doit disparaître derrière la tâche. Une interface qui fait de l'humour avec ses
pixels devient fatigante à la centième dictée de la journée.

Émotions visées : la confiance tranquille (« ça va marcher, et rien ne part
ailleurs ») et le soulagement (« je n'ai pas à repasser derrière pour corriger
la ponctuation »).

## Anti-references

**Le SaaS générique à dégradé.** Le violet-indigo en dégradé, les cartes à ombre
portée, le gros chiffre avec sa petite étiquette. Ce que produit n'importe quel
générateur d'interface en 2026. C'est actuellement l'anti-référence la plus
proche du produit livré : `#6366f1` et `#14b8a6` sont l'indigo et le turquoise
par défaut de Tailwind, et le dégradé entre les deux occupe le bouton principal
et le logo. Une application dont l'argument est « nous soignons ce que les
autres bâclent » ne peut pas porter la palette que tout le monde a par défaut.

**L'utilitaire Linux austère.** Le gris sur gris, la densité de panneau de
configuration système, l'esthétique GTK brute. Fonctionnel et rebutant. Sortir
du dégradé générique ne veut pas dire tomber dans le noir et blanc froid : il
faut qu'il reste de la chaleur et au moins une couleur qui existe vraiment.

**L'assistant IA.** Bulles de conversation, étincelles, halos animés, ton
enjoué et complice. Aparté transcrit et met en forme, il ne cause pas.

**Le studio d'enregistrement.** VU-mètres, formes d'onde animées, esthétique
table de mixage. L'audio est un moyen ; le produit fini est du texte.

## Design Principles

**1. Le français est la fonctionnalité, donc il doit se voir.**
Chaque arbitrage se tranche par « est-ce que ça sert la justesse du texte ? ».
Le corollaire visuel : là où le texte de l'utilisateur s'affiche, la typographie
doit être visiblement soignée. Si les `« »` et les apostrophes courbes rendent
mal dans l'éditeur, l'argument de vente est démenti par sa propre vitrine.

**2. Un seul état compte : le micro est-il ouvert ?**
C'est la seule information que l'utilisateur cherche quand il jette un œil à
l'écran, et il la cherche en périphérie de son champ de vision, pendant une
seconde. Elle doit être lisible sans lire. Tout le reste de l'interface s'efface
pour qu'elle porte.

**3. L'humour est dans les mots, jamais dans le décor.**
La personnalité passe par les messages d'état, les états vides et les libellés.
Les formes restent des formes standard. C'est ce qui permet d'être drôle sans
devenir fatigant.

**4. Zéro retour au terminal, sans mépriser le terminal.**
Tout réglage, tout diagnostic, toute mise à jour se fait depuis l'interface. Mais
la commande équivalente reste affichée et copiable, parce que l'utilisateur type
sait la lire et qu'un contributeur en aura besoin. Le panneau de diagnostic fait
déjà exactement ça ; c'est le modèle à suivre pour les écrans à venir.

**5. « Rien ne sort de la machine » doit être visible, pas seulement vrai.**
La confidentialité est le premier argument du produit et elle est aujourd'hui
invisible dans l'interface : rien à l'écran ne dit que tout tourne en local. Une
mention discrète et permanente vaut mieux qu'un badge tapageur, mais l'absence
totale est une occasion manquée.

## Accessibility & Inclusion

**Engagement pris : les contrastes au niveau WCAG AA.** Tout couple texte/fond
atteint 4,5:1, y compris les textes secondaires, les textes d'aide en 12 px et
les libellés posés sur un aplat de couleur. Les valeurs de la palette sont
vérifiées par calcul, pas à l'œil.

Deuxième exigence, propre au produit : **l'état d'enregistrement ne doit jamais
reposer sur la couleur seule.** Un utilisateur daltonien doit pouvoir répondre à
« est-ce que ça enregistre ? » par la forme, le libellé et le mouvement. C'est
déjà partiellement le cas (le pictogramme passe du micro au carré d'arrêt, le
libellé change) et il faut le conserver. Même règle pour le point de santé de la
barre supérieure, qui ne porte aujourd'hui son information que par sa couleur.

**Écarts refermés au Lot D** — gardés ici pour l'historique, plus rien à faire :
le style de focus est global et unique, `prefers-reduced-motion` a son bloc en
fin de `app.css`, les tiroirs se ferment avec Échap et retiennent le focus, et
les `aria-label` passent par `i18n.js` comme le reste. Les règles qui en
découlent sont dans `CLAUDE.md` § Interface — les rouvrir serait une régression.

**Inclusion linguistique.** L'interface est bilingue français/anglais via des
attributs `data-i18n`, et bascule sur la langue du navigateur au premier
lancement. Tout texte ajouté à l'interface passe par `i18n.js` dans les deux
langues, sans exception. Un libellé écrit en dur est un bogue.
