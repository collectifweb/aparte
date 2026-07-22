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
- [ ] **À faire par Alexandre** : renommer le dépôt GitHub `collectifweb/murmur`
      → `collectifweb/aparte` (GitHub laisse une redirection), et le dossier
      local `Apps-coding/Murmur` si voulu

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

- [ ] Refuser les requêtes POST dont l'en-tête `Origin` n'est ni absent ni
      `http://127.0.0.1:<port>` (à faire avant le reste, ~10 lignes)
- [ ] `GET /api/update/check` : `git fetch`, puis nombre de commits de retard et
      titres des nouveautés
- [ ] `POST /api/update/apply` : `git pull` puis `pip install -e .`, sortie
      renvoyée au fur et à mesure
- [ ] Carte « Mise à jour » dans le panneau Configuration & diagnostic : version
      installée, nouveautés disponibles, bouton, journal en direct
- [ ] Refuser et expliquer, plutôt que tenter, quand :
      - le dépôt a des modifications locales non commitées (sinon le pull les
        met de côté en silence — c'est exactement ce qui est arrivé le 22/07)
      - la branche n'a pas de branche de suivi
      - le dossier n'est pas un dépôt git, ou l'installation n'est pas en mode
        modifiable : afficher « mise à jour manuelle » au lieu d'un bouton mort
- [ ] Ne pas supposer que le remote s'appelle `origin` — lire la branche de
      suivi réelle (`@{u}`). Chez Alexandre le remote s'appelle `Murmur`.
- [ ] Redémarrer le serveur à la fin (il se met à jour lui-même)
- [ ] Tests : dépôt sale refusé, remote non standard, absence de git

## Lot 3 — Le programme résident

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
