# Plan — renommage en Aparté + reprises inspirées de Murmure

Positionnement retenu : **application de dictée vocale pour Linux, centrée sur le
français**. Tout arbitrage se tranche avec ces deux mots-clés. Une fonctionnalité
qui sert le français ou l'intégration Linux passe devant une fonctionnalité
générique.

Source d'inspiration analysée : https://github.com/Kieirra/murmure (Tauri + React,
moteur Parakeet TDT 0.6B v3 en ONNX int8, processeur seulement).

---

## Lot 0 — Renommage (préalable à tout le reste)

- [x] Nom définitif : **Aparté** (nom affiché) / `aparte` (paquet, commande, dossiers)
- [x] Renommer le paquet `src/murmur/` → `src/aparte/`
- [x] Renommer la commande `murmur` → `aparte` (`[project.scripts]`)
- [x] Renommer le lanceur `packaging/linux/murmur.desktop` → `aparte.desktop`
- [x] Adapter les tests, le README, CONTRIBUTING.md, CHANGELOG.md
- [x] Variables d'environnement `MURMUR_*` → `APARTE_*`, avec lecture de secours
      des anciennes (sinon les scripts existants cassent en silence)
- [x] Config `~/.config/murmur/` → `~/.config/aparte/`, avec reprise automatique
      de l'ancien fichier au premier lancement
- [x] Garder une commande `murmur` dépréciée qui appelle la même chose, pour ne
      pas casser le raccourci clavier global déjà configuré dans Cinnamon
- [x] `install-hotkey` reconnaît le raccourci pré-renommage : il le réutilise et
      le renomme au lieu d'en créer un deuxième
- [x] Nettoyer l'ancienne entrée d'autostart, l'ancien lanceur et l'ancienne
      icône au moment d'installer les nouveaux
- [x] Tests verts (66)
- [x] Note dans le README : projet indépendant, sans lien avec Murmure (Kieirra)
      ni avec Wispr Flow, + section « Upgrading from Murmur »
- [x] Dépôt GitHub renommé en `collectifweb/aparte` par Alexandre, et l'adresse
      du remote local mise à jour (le remote s'appelle `Murmur`, pas `origin`)
- [ ] Optionnel : renommer le dossier local `Apps-coding/Murmur`

**Livré dans le commit `c924e57`** (renommage + socle français réunis : le sed du
renommage a touché les mêmes blocs que la typographie, un commit « renommage
seul » n'aurait pas tourné).

---

## Lot 1 — Le socle français (le vrai différenciateur)

Constat : le moteur de mise en forme applique les règles typographiques
**anglaises**. `_space_punctuation()` supprime l'espace avant `? ! : ;` — c'est
exactement l'inverse de la règle française. L'application se dit centrée français
et dégrade activement la typographie française.

- [x] Règles séparées par langue dans `polish.py`, choisies d'après le réglage
      `language` — et, quand il vaut `Auto`, d'après la langue détectée dans le
      texte lui-même (`resolve_language`)
- [x] Espace insécable (U+00A0) avant `? ! ;` et `:`, sans casser `https://`
      ni `14:30`. U+202F (fine) écartée : mal rendue dans trop d'applications
- [x] Guillemets français « » à la place des guillemets droits appariés
- [x] Apostrophe typographique ’ à la place de l'apostrophe droite
- [x] Retirer la règle `\bi\b → I` quand la langue est le français
- [x] Hésitations : seuls les mots réellement ambigus sont séparés par langue
      (`like`/`basically` en anglais, `ben`/`genre`/`tsé` en français, au niveau
      « élevé »). `euh` et `um` ne sont des mots dans aucune des deux langues,
      les séparer n'aurait rien apporté
- [x] Prompt Ollama rédigé en français quand la dictée est en français, règles
      typographiques explicitées
- [x] Réglage `nonbreaking_spaces` (défaut activé) + case à cocher dans les
      Réglages, groupe Mise en forme
- [x] Tests couvrant chaque règle française (80 tests au total)

## Lot 2 — Insertion du texte plus fiable

Révisé : le commit `12ca746`, arrivé pendant l'analyse, fait déjà l'essentiel —
`paste_text()` copie d'abord dans le presse-papiers puis envoie un seul Ctrl+V,
au lieu de taper le texte caractère par caractère.

- [x] Mode « presse-papiers + Ctrl+V » par défaut — fait en amont (`12ca746`)
- [ ] Mode « Terminal » (Ctrl+Shift+V) — les terminaux ignorent Ctrl+V, et
      aujourd'hui le README se contente de dire de coller à la main
- [ ] Remettre la frappe simulée en option « Direct », pour les applications qui
      bloquent le collage (LibreOffice, certaines applications Electron) : le
      repli a disparu avec `12ca746`
- [ ] Exposer le choix du mode dans les Réglages
- ~~Restaurer le presse-papiers après collage~~ : abandonné. Le choix inverse
  est désormais assumé — la dictée reste dans le presse-papiers pour servir de
  filet si le collage tombe à côté.

## Lot 2bis — Mise à jour depuis l'interface

Inspiré de Murmure, mais l'équivalent chez nous n'est pas le même travail : eux
téléchargent un binaire signé depuis leurs Releases GitHub ; nous, une mise à
jour c'est `git pull` + `pip install -e .`. Pas de signature à gérer, pas de
binaires à héberger, pas de serveur de mise à jour. En revanche il faut refuser
proprement les situations où le pull casserait.

**Prérequis — vérification de l'origine des requêtes.** Les routes POST du
serveur n'inspectent pas l'en-tête `Origin`. Le serveur n'écoute que sur
127.0.0.1, donc rien n'est joignable depuis le réseau, mais une page web ouverte
dans le navigateur peut poster vers `127.0.0.1:8765` en aveugle — et `/api/paste`
colle du texte dans l'application active. Ajouter une route qui lance
`pip install` sans cette vérification serait nettement plus grave.

- [x] Refuser les requêtes POST dont l'en-tête `Origin` n'est ni absent ni
      notre propre adresse (commit `19b5243`)
- [x] `GET /api/update/check` : nombre de commits de retard et titres des
      nouveautés — le `git fetch` seulement sur clic, jamais à l'ouverture
- [x] `POST /api/update/apply` : `git pull` puis `pip install -e .`, sortie
      renvoyée au fur et à mesure
- [x] Bloc « Mise à jour » dans le panneau Configuration & diagnostic : version
      installée, nouveautés disponibles, bouton, journal en direct
- [x] Refuser et expliquer, plutôt que tenter, quand :
      - le dépôt a des modifications locales non commitées (sinon le pull les
        met de côté en silence — c'est exactement ce qui est arrivé le 22/07)
      - la branche n'a pas de branche de suivi
      - le dossier n'est pas un dépôt git, ou l'installation n'est pas en mode
        modifiable : afficher « mise à jour manuelle » au lieu d'un bouton mort
- [x] Ne pas supposer que le remote s'appelle `origin` — lire la branche de
      suivi réelle (`@{u}`). Chez Alexandre le remote s'appelle `Murmur`.
- [x] Redémarrer le serveur à la fin (il se met à jour lui-même)
- [x] Tests : dépôt sale refusé, remote non standard, absence de git

**Livré** dans `src/aparte/update.py` (commit `a567048`), branche
`feat/update-from-ui`, posée sur la refonte `design/lot-d`. Deux points décidés
en cours de route, non prévus au plan :

- La réinstallation ne passe que les extras déjà présents (`whisper`,
  `recording`, `cuda` détectés par module). Passer une liste fixe téléchargerait
  plusieurs gigaoctets sur une installation qui s'en était volontairement passée.
- `_available_port()` pose `SO_REUSEADDR` avant de tester le port. Sans ça, le
  test échoue sur les connexions encore en `TIME_WAIT` et l'application revient
  d'une mise à jour sur un autre port que celui que le navigateur surveille.

Reste ouvert : après le redémarrage, le navigateur attend 3 s avant de sonder le
serveur, parce que rien ne distingue l'ancien processus du nouveau. Un identifiant
de démarrage renvoyé par `/api/config` rendrait l'attente exacte.

## Lot 3 — Le programme résident

**Débloqué** : l'initialisation `/impeccable` a livré `PRODUCT.md` (159 lignes)
et `DESIGN.md` (486 lignes : couleurs, typographie, élévation, composants, do's
and don'ts), plus un dossier `.impeccable/`. Les trois sont encore hors de git.
Les lire avant de coder quoi que ce soit de visible dans ce lot — icône de barre
système, panneau d'historique, carte de mise à jour.

Ce que le Lot D a déjà tranché pour ce lot :

- L'**icône de barre système** a ses deux états dans `DESIGN.md` : encre au
  repos, carmin quand le micro est ouvert, comme le disque de l'écran principal.
  `logo.svg` est désormais un aplat, donc lisible en 16 px.
- Le **panneau d'historique** va dans la zone vide sous l'éditeur (D4.6, laissée
  telle quelle exprès). C'est une **liste** — filet de 1 px et fond en creux —
  pas une grille de cartes.
- La **carte de mise à jour** (Lot 2bis) se place au-dessus du plan `110`.

Le serveur d'autostart tourne déjà en permanence : il ne manque que l'icône.

- [ ] Icône de barre système greffée sur le serveur desktop (pystray/AppIndicator)
- [ ] Deux états visuels : au repos / en train d'enregistrer
- [ ] Menu : Ouvrir Aparté · Copier la dernière dictée · Réglages · Quitter
- [ ] Historique des 5 dernières dictées, **en mémoire vive par défaut**,
      écriture sur disque seulement si l'utilisateur l'active explicitement
- [ ] Affichage de l'historique sur l'écran d'accueil, clic = copie
- [ ] Commande `aparte last --target paste` pour recoller la dernière dictée

## Lot 4 — Confort

- [ ] Bip sonore au début et à la fin de l'enregistrement (réglable)
- [ ] Choix du microphone dans les Réglages, avec rafraîchissement de la liste
- [ ] Espace final garanti, pour que deux dictées successives ne se collent pas
- [ ] Texte court : une dictée de moins de N mots ne reçoit ni majuscule ni point
      final (utile pour dicter dans un champ de recherche)
- [ ] Nombres en toutes lettres → chiffres, au-delà d'un seuil réglable, en français
- [ ] États vides actionnables et infobulles explicatives dans l'interface

## Lot 5 — Plus tard

- [ ] Aperçu au fil de la parole (re-transcription périodique d'une fenêtre
      glissante — la même technique qu'eux, mais nous avons le GPU et pas eux)
- [ ] Modes de reformulation multiples (traduction, courriel, notes) avec prompt
      par mode et raccourci dédié
- [ ] Mode Commande : transformer par la voix le texte actuellement sélectionné
- [ ] Statistiques d'usage (temps gagné, mots par minute)
- [ ] Import / export des réglages
- [ ] Fenêtre flottante pendant l'enregistrement

---

## À ne pas reprendre

- **La détection automatique de langue sans réglage.** C'est leur faiblesse
  principale : un seul modèle multilingue, aucun moyen de forcer une langue,
  bascule vers l'anglais quand l'audio est moyen. Notre réglage de langue
  explicite dans Whisper est exactement ce qui nous fait gagner sur le français.
- **L'exécution sur processeur seulement.** Nous avons le repli GPU/CPU.
- **La correction floue par distance de Levenshtein sur le dictionnaire.** Chez
  eux, elle peut faire basculer une phrase courte entière dans une autre langue.

---

## Review

### Lot 0 — renommage (fait, non commité)

31 fichiers renommés, 66 tests verts. Points de vigilance traités :

| Risque | Traitement |
|---|---|
| Perte des réglages | `migrate_legacy_config()` déplace l'ancien fichier au premier lancement, et seulement si rien n'existe déjà à la nouvelle place |
| Scripts qui exportent `MURMUR_*` | `get_env()` lit d'abord `APARTE_*`, puis l'ancien nom |
| Raccourci Cinnamon cassé | commande `murmur` conservée (dépréciée) + `install-hotkey` réutilise et renomme le slot existant au lieu d'en créer un doublon |
| Deux entrées de menu / deux serveurs au login | `remove_legacy_entries()` supprime l'ancien lanceur, l'ancienne icône et l'ancien autostart |

### Lot 1 — socle français (fait, non commité)

Avant / après, dictée « est-ce que tu viens demain point d'interrogation » :

| Avant | Après |
|---|---|
| `Est-ce que tu viens demain?` | `Est-ce que tu viens demain ?` (espace insécable) |
| `C'est l'ami de Paul.` | `C’est l’ami de Paul.` |
| `Il a dit "bonjour".` | `Il a dit « bonjour ».` |

Décisions prises en chemin :

- **U+00A0 plutôt que U+202F.** La fine insécable est la règle typographique
  stricte, mais elle s'affiche mal dans trop d'applications (carré blanc). Vu
  que la dictée part dans Slack, un courriel ou un champ de recherche, la
  robustesse prime sur la finesse.
- **Détection de langue depuis le texte** quand le réglage vaut `Auto`, plutôt
  que de faire circuler la langue détectée par Whisper. Un seul point de
  branchement, et ça couvre aussi le texte collé à la main dans l'éditeur.
- **Hésitations : ne séparer que l'ambigu.** Voir Lot 1 ci-dessus.
- La typographie française est appliquée **après** les remplacements et les
  raccourcis, sinon l'apostrophe courbe casse leur correspondance par mot.

### Incident git

Un `git pull` s'est déclenché pendant le travail
(fast-forward `41e7296` → `12ca746`), a mis les modifications de côté
automatiquement et n'a pas su les réappliquer. Le renommage a été refait à zéro
sur le code à jour plutôt que de résoudre les conflits — l'amont avait supprimé
`hotkey_guidance()` et une résolution manuelle l'aurait réintroduit. L'ancien
état reste dans `git stash` (`stash@{0}`), à supprimer une fois rassuré.

---

# Lot D — Design

**Statut : validé et appliqué le 22/07/2026.** 83 tests au vert, rendu vérifié
au navigateur dans les deux thèmes. Reste ouvert : **D4.6**, la zone vide sous
l'éditeur, documentée en **D6 — La zone réservée**. Elle appartient au Lot 3 et
c'est là que se posera le panneau d'historique.

Contexte stratégique dans `PRODUCT.md`, système visuel dans `DESIGN.md`
(régénéré sur le code livré). Toutes les valeurs ci-dessous sont calculées, pas
estimées à l'œil.

## D1 — Contrastes (le seul engagement d'accessibilité pris)

Mesures sur l'interface livrée :

| Élément | Actuel | Seuil | Verdict |
|---|---|---|---|
| « Parler » blanc sur le turquoise du dégradé | **2,49:1** | 4,5:1 | échec |
| Texte d'état (`#6366f1` sur `#f6f7f9`) | **4,17:1** | 4,5:1 | échec |
| Texte blanc sur bouton primaire indigo | **4,47:1** | 4,5:1 | échec |
| Bouton « Copier » du diagnostic (12 px blanc sur indigo) | **4,47:1** | 4,5:1 | échec |
| `--muted` sur `--panel-2`, thème clair | **4,35:1** | 4,5:1 | échec |
| `--muted` sur `--bg`, thème clair | **4,51:1** | 4,5:1 | passe d'un cheveu |
| Placeholder de l'éditeur | style navigateur | 4,5:1 | non défini |

- [x] D1.1 — Libellé blanc sur l'aplat carmin : **6,11:1** (était 2,49:1).
- [x] D1.2 — Messages d'état en encre (16,7:1). La classe `.status.error` porte
      les erreurs en `--danger`, qui n'était jamais utilisé pour ça.
- [x] D1.3 — Encre atténuée jamais sous **6,3:1**, y compris à 12 px sur les
      blocs en creux (était 4,35:1).
- [x] D1.4 — `::placeholder` explicite en `--ink-soft`, `opacity: 1`.

## D2 — Palette

Le dégradé turquoise → indigo est l'anti-référence n° 1 de `PRODUCT.md`, et
`#6366f1` / `#14b8a6` sont les couleurs par défaut de Tailwind.

**Direction : « L'aparté ».** La scène (surface calme), le projecteur (une seule
couleur saturée, qui n'apparaît que quand le micro est ouvert), le programme
imprimé (le texte traité comme le produit fini).

Le bouton d'enregistrement passe de « dégradé au repos → rouge en cours » à
**« encre au repos → carmin en cours »**. Le repos devient calme, l'état actif
devient le seul aplat saturé de l'écran. C'est le principe n° 2 de `PRODUCT.md`
rendu littéral.

### Thème clair

| Rôle | OKLCH | sRGB | Emploi |
|---|---|---|---|
| `bg` | `oklch(1 0 0)` | `#ffffff` | fond de page, blanc pur |
| `surface` | `oklch(0.982 0.004 15)` | `#fcf8f8` | tiroirs, barre supérieure |
| `surface-2` | `oklch(0.960 0.006 15)` | `#f6f0f0` | blocs en creux, survols |
| `line` | `oklch(0.902 0.007 15)` | `#e3dddd` | filets 1 px |
| `ink` | `oklch(0.235 0.014 15)` | `#241b1c` | texte principal, bouton au repos |
| `ink-soft` | `oklch(0.455 0.016 15)` | `#5f5354` | textes secondaires |
| `brand` | `oklch(0.520 0.185 5)` | `#b8245b` | carmin : état actif, focus, liens |
| `ok` | `oklch(0.500 0.100 155)` | `#2a7449` | diagnostic conforme |
| `warn` | `oklch(0.550 0.110 75)` | `#976712` | diagnostic partiel |
| `danger` | `oklch(0.480 0.170 28)` | `#a9231e` | destructif (historique à venir) |

### Thème sombre

| Rôle | OKLCH | sRGB |
|---|---|---|
| `bg` | `oklch(0.190 0.010 15)` | `#181212` |
| `surface` | `oklch(0.235 0.011 15)` | `#231c1c` |
| `surface-2` | `oklch(0.282 0.012 15)` | `#2f2727` |
| `line` | `oklch(0.335 0.014 15)` | `#3e3434` |
| `ink` | `oklch(0.955 0.005 15)` | `#f3efef` |
| `ink-soft` | `oklch(0.742 0.014 15)` | `#b4a8a8` |
| `brand-ink` | `oklch(0.700 0.160 5)` | `#ee6e91` (carmin **en texte** seulement) |
| `ok` | `oklch(0.760 0.130 155)` | `#65c98c` |
| `warn` | `oklch(0.800 0.120 75)` | `#ebb25f` |
| `danger` | `oklch(0.660 0.170 28)` | `#e86154` |

**L'aplat carmin `#b8245b` est le même dans les deux thèmes**, avec du texte
blanc à 6,11:1. Le `brand-ink` sombre ne sert qu'au texte, jamais en aplat.

Tous les couples vérifiés, tous dans le gamut sRGB, tous ≥ 4,5:1 :

```
ink / bg              16,75    ink sombre / bg sombre        16,21
ink-soft / bg          7,34    ink-soft sombre / bg sombre    8,03
ink-soft / surface-2   6,52    ink-soft sombre / surface-2    6,32
brand / bg             6,11    brand-ink / bg sombre          6,41
brand / surface-2      5,42    brand-ink / surface-2 sombre   5,04
blanc / brand (aplat)  6,11    ok 5,71 · warn 4,95 · danger 7,14
```

- [x] D2.1 — Les deux thèmes posés en OKLCH dans `:root`.
- [x] D2.2 — Bouton d'enregistrement : encre au repos, carmin en cours.
      Le repos du thème sombre est remonté à `oklch(0.510 0.016 15)` : à
      `0.400` le disque ne se détachait plus du fond (1,99:1, il en faut 3).
- [x] D2.3 — `--accent-grad` retiré. Plus aucun dégradé dans le projet.
- [x] D2.4 — `logo.svg` en aplat carmin, dégradé abandonné partout.

**Tranché :** le dégradé disparaît aussi du logo. Un logo à deux états lisible
en 16 px dans une barre système ne peut pas reposer sur un dégradé.

## D3 — Échelles

Aujourd'hui : 4, 5, 6, 7, 8, 9, 10, 12, 14, 16, 18, 20, 30, 36, 48 px
d'espacement, 7 tailles de texte, 8 rayons, 2 valeurs de `z-index`. Aucune
échelle.

- [x] D3.1 — Espacement : `4 · 8 · 12 · 16 · 20 · 24 · 32 · 48`.
- [x] D3.2 — Rayons : `6` · `10` · `14` · `999`.
- [x] D3.3 — Texte : `12 · 13 · 14 · 16 · 18`, tailles fixes, aucun `clamp()`.
- [x] D3.4 — Plans : `10` barre supérieure · `100` voile · `110` tiroir.
      Au-dessus de 110 pour les notifications et la carte de mise à jour.
- [x] D3.5 — Mouvement : `--dur-fast: 120ms`, `--dur: 180ms`,
      `--ease: cubic-bezier(0.16, 1, 0.3, 1)`.

Ces échelles n'ont d'effet visuel que là où on les applique. Les écrans à venir
peuvent les adopter tout de suite sans toucher à l'existant.

## D4 — Composants : états manquants

- [x] D4.1 — `:focus-visible` global, un seul style. Vérifié au navigateur avec
      une vraie touche Tab : un focus posé par script ne déclenche pas
      `:focus-visible`, c'est le comportement normal du navigateur, pas un bogue.
      **Piège rencontré** : mettre un `border-radius` dans la règle
      `:focus-visible` déforme l'élément le temps du focus. L'outline suit déjà
      le rayon natif — ne rien y mettre.
- [x] D4.2 — Puces désactivées pendant le traitement (`BUSY_CONTROLS`).
- [x] D4.3 — Le libellé dit « Un instant… » / « One moment… » au lieu de `…`.
- [x] D4.4 — `--shadow` retiré de `#editor`. Il ne reste que sur le disque et
      le tiroir, les deux seules choses qui survolent vraiment.
- [x] D4.5 — Écart de surfaces rétabli : fond blanc pur, surface `0.982`,
      creux `0.960`, plus un filet de 1 px.
- [ ] D4.6 — La zone sous l'éditeur reste vide. **Laissé tel quel
      volontairement** : c'est un espace réservé, pas un oubli. Voir « D6 — La
      zone réservée » ci-dessous.
- [x] D4.7 — `.hero` → `.workspace`, `.hero-sub` → `.workspace-sub`. Les clés
      i18n `hero.*` et l'id `#hero-sub` sont conservés : ce sont des
      identifiants internes, les renommer n'apporte rien et touche deux langues.

## D5 — Accessibilité, hors engagement initial

Ces points sortaient du choix « contrastes AA seulement ». Faits quand même :
ils coûtaient peu et retiraient de vrais défauts.

- [x] D5.1 — Bloc `@media (prefers-reduced-motion: reduce)` en fin de
      `app.css`. Les états restent lisibles à l'arrêt : l'anneau
      d'enregistrement s'affiche plein au lieu de pulser.
- [x] D5.2 — Tiroirs modaux au clavier : `Échap` ferme, `Tab` reste enfermé, le
      focus entre sur le premier contrôle et revient au bouton déclencheur,
      `aria-modal="true"` et `aria-labelledby` sur le titre déjà traduit.
      Le gestionnaire `keydown` est global : un tiroir ajouté est pris en charge
      sans code supplémentaire.
- [x] D5.3 — Nouvel attribut `data-i18n-aria`, traité par `applyI18n()`.
      Clés `nav.lang` et `btn.close` ajoutées dans les deux langues.
- [x] D5.4 — `aria-label="Talk"` **supprimé** plutôt que traduit : sans lui, le
      nom accessible du bouton est son libellé visible, qui suit déjà l'état.
      Un attribut de moins à maintenir.
- [x] D5.5 — La pastille de santé est doublée d'un texte masqué visuellement
      (`.sr-only`, rattaché par `aria-describedby`), mis à jour dans la langue
      courante via les clés `health.ok` / `health.warn` / `health.bad`.

## D6 — La zone réservée (le seul point laissé ouvert)

`.workspace` porte `flex: 1` et son contenu est collé en haut. Sur un écran de
900 px de haut, il reste donc **250 à 350 px vides** sous la barre d'actions.
C'est le seul endroit de l'interface qui ne fait rien, et le seul qui puisse
accueillir quelque chose sans rien déplacer : l'éditeur et le disque gardent
leur position, la zone pousse vers le bas.

Elle n'a pas été remplie dans le Lot D parce qu'elle appartient au Lot 3, et
qu'un panneau posé sans son contenu réel se conçoit mal. Les contraintes sont en
revanche déjà tranchées.

### Ce qui va dedans

Le **panneau d'historique** des dernières dictées (Lot 3), clic = copie.

### Ce qui est déjà décidé

- **Une liste, pas une grille de cartes.** Filet de 1 px et fond en creux
  suffisent à séparer. Voir le « Don't » correspondant dans `DESIGN.md`.
- **Aucun aplat de couleur.** La règle du projecteur tient : si l'historique
  prend de la couleur, l'état « ça enregistre » cesse d'être lisible du coin de
  l'œil. Au mieux, un filet ou un texte en carmin sur l'entrée survolée.
- **Elle reste sous la barre d'actions.** Elle ne s'intercale pas entre le
  disque et l'éditeur : le chemin principal (parler → relire → insérer) ne doit
  pas gagner une étape visuelle.
- **Elle ne défile pas la page.** Si l'historique dépasse, c'est la liste qui
  défile, pas le document — le disque et l'éditeur restent toujours visibles.
- **Le modèle est la ligne de diagnostic** : une ligne dit ce qu'elle est et
  porte son action, sans ouvrir de sous-écran.

### Ce que l'état vide doit faire

L'historique est **en mémoire vive par défaut** (Lot 3), donc il est vide à
chaque ouverture de session. Cet état vide est la situation normale, pas
l'exception : il doit enseigner, pas afficher « aucune dictée ».

Deux choses manquent aujourd'hui à l'interface et trouveraient leur place là :

1. **Le raccourci clavier global.** `PRODUCT.md` dit que c'est le chemin
   principal du produit, et l'interface n'en parle que dans une demi-phrase sous
   le disque. L'état vide peut afficher le raccourci réellement lié — le serveur
   le connaît déjà, `/api/doctor` renvoie `hotkey.bound_key_label` — ou la
   commande pour le lier s'il ne l'est pas, sur le modèle de `.diag-fix`.
2. **« Rien ne sort de la machine ».** C'est le premier argument du produit et
   il est invisible à l'écran (principe n° 5 de `PRODUCT.md`). Une mention
   discrète et permanente, pas un badge.

### Questions encore ouvertes

- L'historique s'affiche-t-il toujours, ou seulement quand il contient quelque
  chose ? Si la zone se vide et se remplit, la page saute à chaque dictée.
  Piste : réserver la hauteur, l'état vide occupant la même place.
- Cinq entrées (Lot 3) tiennent-elles dans la hauteur disponible sur un portable
  en 1366 × 768 ? À vérifier avant de figer le nombre.
- Que se passe-t-il quand la fenêtre est courte et que la zone n'existe plus ?
  L'interface ne doit pas se casser sous 600 px de haut.

## D7 — Ce qui est déjà bien fait

À ne pas casser en passant :

- `role="status"` + `aria-live="polite"` sur le fil d'état : correctement posé.
- Le bloc de diagnostic « ce qui manque + la commande qui le répare + un bouton
  copier » est le meilleur composant du produit et le modèle des écrans à venir.
- Deux thèmes complets suivant `prefers-color-scheme`, sans bascule manuelle.
- L'état d'enregistrement se lit déjà sans la couleur (pictogramme, libellé,
  pulsation).
- Aucune police d'affichage, aucune taille fluide : correct pour un outil.

## D8 — La sérif pour l'éditeur

- [x] Éditeur en `Georgia, "Liberation Serif", "DejaVu Serif",
      "Times New Roman", serif`, 18 px, interligne 1,65, colonne ramenée de 760
      à 680 px pour tenir autour de 70 caractères par ligne.

Vérifié au navigateur : les `« »`, l'apostrophe courbe et l'espace insécable
avant `;` et `?` se lisent à l'œil nu. C'est devenu la capture principale du
README, parce que c'est l'argument du produit rendu visible.

**Reste à confirmer sur ton poste.** La pile est système, donc le rendu dépend
des polices installées. Ici c'est Liberation Serif ou DejaVu Serif qui sort ;
si le résultat te déplaît sous Cinnamon, une seule ligne à changer :
`--font-text` dans `app.css`.

## D9 — Documentation et image du projet

- [x] `README.md` : encadré en tête qui dit « tu cherchais Murmur, tu l'as
      trouvé », avec le lien vers la section de migration. L'argument
      « local, et typographie française » remonte dans l'introduction.
- [x] Captures refaites : écran principal en clair (avec du texte français pour
      montrer la typographie), enregistrement en cours en sombre, les deux
      tiroirs. Anciennes captures « Murmur » remplacées.
- [x] `CLAUDE.md` : section « Avant de toucher à quoi que ce soit de visible »
      qui pointe vers `PRODUCT.md` et `DESIGN.md`, plus les invariants
      d'interface (i18n des `aria-label`, focus global, tiroirs modaux,
      mouvement réduit).
- [x] `CHANGELOG.md` : entrées sous `[Unreleased]`.

