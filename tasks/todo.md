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
- [x] Mode « Terminal » (Ctrl+Shift+V) — les terminaux ignorent Ctrl+V, et
      aujourd'hui le README se contente de dire de coller à la main
- [x] Remettre la frappe simulée en option « Direct », pour les applications qui
      bloquent le collage (LibreOffice, certaines applications Electron) : le
      repli a disparu avec `12ca746`
- [x] Exposer le choix du mode dans les Réglages — nouveau groupe « Insertion »
      dans le tiroir, réglage `paste_mode`, variable `APARTE_PASTE_MODE`

Les trois modes copient dans le presse-papiers avant d'insérer : le filet vaut
pour la frappe simulée autant que pour le collage. Un mode inconnu retombe sur
Ctrl+V plutôt que de refuser.
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

**Fait, sans dépendance** — l'historique (`src/aparte/history.py`) :

- [x] Historique des 5 dernières dictées, **en mémoire vive par défaut**,
      écriture sur disque seulement si l'utilisateur l'active explicitement
      (réglage `history_persist`, fichier en 0600 sous `~/.local/state/aparte`)
- [x] Affichage de l'historique sur l'écran d'accueil, clic = copie
- [x] Commande `aparte last --target paste` pour recoller la dernière dictée

Décision d'architecture : l'historique est un fichier dans le dossier d'exécution
(`XDG_RUNTIME_DIR`, tmpfs, effacé à la déconnexion) et non la mémoire d'un
processus. Le raccourci clavier lance un processus court, le serveur en est un
autre, `aparte last` un troisième — un fichier en tmpfs les réunit sans serveur
à joindre ni port à deviner, tout en restant « en mémoire vive ».

Les trois questions ouvertes du D6 sont tranchées : la zone garde une hauteur
réservée de 116 px même vide (la page ne saute pas) ; la liste défile
elle-même au-delà de 30 % de la hauteur de fenêtre, donc cinq entrées tiennent
sur un portable ; sous 700 px de haut, la hauteur réservée est rendue plutôt que
de pousser l'éditeur hors de l'écran.

**L'icône de barre système** (`src/aparte/tray.py`) :

- [x] Icône de barre système greffée sur le serveur desktop — bindings système
      PyGObject + AyatanaAppIndicator3, **aucune dépendance pip ajoutée**
- [x] Deux états visuels : au repos / en train d'enregistrer
- [x] Menu : Ouvrir Aparté · Copier la dernière dictée · Réglages · Quitter

Choix : les bindings système plutôt que `pystray`, qui aurait ajouté deux
dépendances pip et serait retombé sur XEmbed (X11 seulement, ancien) faute de
`gi`. Conséquence assumée : `install-linux.sh` crée désormais le venv avec
`--system-site-packages`, sans quoi le venv ne voit pas PyGObject. **Un venv déjà
créé doit être supprimé et refait** pour que l'icône apparaisse.

Les deux états se distinguent par la forme — trois barres au repos, un disque
plein pendant l'enregistrement — et non par la couleur : la règle du daltonien de
`DESIGN.md` s'applique à 22 px comme au reste. L'aplat carmin est gardé dans les
deux états, parce qu'un panneau peut être clair ou sombre et qu'une icône neutre
disparaîtrait sur l'un des deux.

Sans les bindings, `build_tray()` renvoie `None` et le serveur démarre exactement
comme avant ; le diagnostic gagne une ligne « Icône de barre système » qui dit
quoi installer.

À vérifier de visu, je n'ai pas pu le faire : la lisibilité des deux icônes dans
le panneau Cinnamon, et le fait que l'état passe bien au disque plein pendant une
dictée lancée au raccourci clavier. L'état d'enregistrement suit le fichier de
session du raccourci global ; une dictée lancée depuis le bouton de la page web
n'en crée pas, donc l'icône ne change pas dans ce cas.

## Correctifs d'installation (22/07, hors lots)

Trouvés en installant Aparté par-dessus l'ancienne installation `~/murmur` :

- [x] Entrée de bureau invalide (`desktop-file-validate`) : `Audio` exige
      `AudioVideo` à côté, et trois catégories principales faisaient apparaître
      l'application **trois fois** au menu. Passé à `Utility;Accessibility;`,
      avec deux tests qui passent les entrées au validateur (`2355ac8`)
- [x] Le lanceur du menu démarrait un **second serveur** — port au hasard,
      deuxième icône — puisque l'autostart en tient déjà un. `aparte desktop`
      sonde le port et rend la main à l'instance en cours (`2ad4784`)

Migration réalisée : `~/murmur` mis à jour de 11 commits, distribution `murmur`
désinstallée au profit d'`aparte`, `include-system-site-packages = true` dans
`pyvenv.cfg` (plutôt que de refaire le venv et retélécharger Whisper et CUDA),
raccourci `Super+Fin` réutilisé sans doublon, et les deux fichiers de
configuration divergents fusionnés (14 remplacements, sauvegarde dans
`~/.config/aparte-backup-20260722/`).

## QA de l'interface (22/07, hors lots)

Passe de vérification demandée après le Lot 4, mesurée au navigateur sans tête
(brave headless + CDP, script gardé en scratchpad) plutôt qu'à l'œil :

- [x] **Le panneau des dictées ne faisait pas la largeur de la colonne.** Le plan
      de travail est un conteneur flex centré et `.recent` n'avait pas de largeur
      propre : avec deux dictées courtes il tombait à 188 px flottant au milieu,
      son filet réduit à un moignon, quand l'éditeur au-dessus fait 680 px.
      `width: 100%` (`0b19d0c`)
- [x] **Défilement latéral sous 560 px de large** : les deux boutons de la barre
      supérieure débordaient. La barre passe à la ligne (`0b19d0c`)
- [x] **L'application ne tenait pas sur un écran.** Il fallait 984 px de hauteur
      utile — exactement ce qu'un écran 1080p laisse une fois les barres du
      navigateur déduites, d'où le bas coupé. Marge basse 48 → 24 px et plafond
      de l'éditeur 360 → 300 px : le seuil tombe à 900 px. Écarté : rendre
      l'éditeur élastique (casse `resize: vertical`) et supprimer la hauteur
      réservée du panneau (la page sauterait à chaque dictée)
- [x] **Un test écrivait dans le vrai historique de l'utilisateur** :
      `HistoryEndpointTest` posait `APARTE_RUNTIME_DIR` mais pas `APARTE_CONFIG`,
      donc le serveur lisait la vraie config, où `history_persist` est vrai.
      Invariant ajouté dans `CLAUDE.md` § Lancer les tests

## Icône de barre système (22/07, hors lots)

Signalée à l'usage : l'icône n'apparaissait que pendant la dictée et laissait un
creux d'un millimètre au repos.

- [x] **Cause racine : le commentaire en tête du fichier SVG.** `gdk-pixbuf`
      reconnaît un format en reniflant les **256 premiers octets**. Dans
      `aparte-tray.svg`, l'en-tête français poussait la balise racine à l'octet
      **403** : le chargeur répondait « format non reconnu » et le panneau
      n'avait rien à dessiner. `aparte-tray-recording.svg`, commentaire plus
      court, tombait à l'octet 215 — dans la fenêtre — et s'affichait. D'où le
      symptôme exact. Les deux fichiers portent maintenant leur commentaire à
      l'intérieur de la balise racine (`0cef71a`)
- [x] **Chaîne vérifiée maillon par maillon avant de toucher au code**, plutôt
      que de deviner : l'indicateur publiait bien `aparte-tray` et le bon
      dossier sur DBus, et le pont `xapp-sn-watcher` avait résolu le nom vers le
      vrai fichier. La recherche marchait ; seul le rendu échouait. Deux fausses
      pistes écartées au passage — le cache négatif de `GtkIconTheme` (il se
      réinvalide) et une collision entre plusieurs indicateurs (un seul était
      enregistré).
- [x] **Garde-fou** : `test_every_svg_declares_its_format_within_the_sniff_window`
      vérifie la règle sur tous les SVG du dossier `assets/`, pas seulement les
      deux du moment. Invariant écrit dans `CLAUDE.md` § Icônes SVG.
- [x] **Deux processus `python -m murmur desktop`** d'avant le renommage
      tournaient encore (démarrés à 15:20 et 15:21), sur du code qui n'existe
      plus sur le disque. Ils n'avaient pas le port mais occupaient la mémoire,
      et `CLAUDE.md` prévient du risque de deux serveurs qui se le disputent à
      l'ouverture de session. Arrêtés.

## Lot 4 — Confort

- [x] Bip sonore au début et à la fin de l'enregistrement (réglable) — deux tons
      synthétisés à la volée dans `audio.py`, aucun fichier son livré. Le bip
      d'ouverture est joué **avant** que le micro s'ouvre, sinon il s'enregistre.
- [x] Choix du microphone dans les Réglages, avec rafraîchissement de la liste —
      `arecord -L` filtré aux entrées `plughw:` (les seules qui rééchantillonnent
      vers le 16 kHz de Whisper). Le nom ALSA choisi part en `-D` vers arecord,
      côté raccourci global comme côté terminal ; le bouton Parler enregistre
      dans le navigateur et garde donc le micro du navigateur. Un micro
      débranché reste dans la liste, marqué, plutôt que d'être remplacé en
      silence.
- [x] Espace final garanti, pour que deux dictées successives ne se collent pas
      — `trailing_space`, décoché par défaut, appliqué par les deux polisseurs.
- [x] Texte court : une dictée de moins de N mots ne reçoit ni majuscule ni point
      final (utile pour dicter dans un champ de recherche) — `short_text_words`,
      désactivé par défaut. Le seuil est strict : « moins de 3 mots » laisse
      passer trois mots. Les remplacements et snippets s'appliquent quand même.
- [x] Nombres en toutes lettres → chiffres, au-delà d'un seuil réglable, en français
      — voir le plan ci-dessous, livré avec les heures et les pourcentages
- [x] États vides actionnables et infobulles explicatives dans l'interface
      - [x] **Éditeur vide → Polir, Copier et Insérer s'éteignent.** Elles
            annonçaient leur succès sans rien faire, et « Copier » allait plus
            loin : il remplaçait le presse-papiers par du vide. « Importer
            audio » reste active, c'est elle qui remplit l'éditeur.
      - [x] **« Coller » devient « Insérer ».** Le bouton n'insère pas dans
            l'éditeur, il écrit dans l'application de devant — ce que les
            Réglages appelaient déjà « Insertion ». Les messages d'état suivent
            (« Insertion… », « Inséré. »).
      - [x] **Infobulles** (`title` traduit) sur les quatre puces, le sélecteur
            de modèle et « Polir auto ».
      - [x] **Aucun micro détecté → une ligne le dit** sous le champ, en encre
            pleine, et renvoie vers Configuration.
      - [x] **Diagnostic qui n'a pas répondu** : une phrase traduite au lieu de
            l'erreur JavaScript brute, l'erreur restant affichée en dessous.
      - [x] **L'état désactivé passe de l'opacité à une teinte calculée.**
            `opacity: 0.45` mélangeait le libellé au blanc de la page :
            **1,69:1 en thème clair**, illisible, et il aurait fallu monter à
            0,85 pour repasser le seuil — donc ne plus rien éteindre. Nouveau
            jeton `ink-disabled` (4,63:1 clair, 4,56:1 sombre). Le défaut
            existait déjà mais ne durait que le temps d'une transcription ;
            c'est maintenant l'état de repos de la page. Un bouton primaire
            désactivé rend aussi son aplat carmin.
      - Pas touché : l'état vide du panneau des dictées, qui enseigne déjà le
        raccourci global et la mention « rien ne sort de la machine ».

### Plan — les nombres en français

**Pourquoi.** Whisper écrit déjà des chiffres une fois sur deux. L'enjeu n'est pas
de tout convertir, c'est de rendre le résultat prévisible : une dictée ne doit
pas donner « vingt-deux » un jour et « 22 » le lendemain.

**Où.** Un module à part, `numbers.py` — l'analyse d'un nombre français fait une
centaine de lignes et n'a rien à faire dans `polish.py`, qui l'appelle.

**Quand, dans le tuyau.** Juste après `_replace_spoken_punctuation` et **avant**
`_space_punctuation`. Deux raisons : la règle qui protège `14:30` et `https://`
doit voir les chiffres pour faire son travail, et les remplacements par mot
n'ont pas encore tourné.

**Français seulement**, comme les guillemets et l'apostrophe. L'anglais est un
autre chantier, et « français d'abord » tranche.

- [x] `numbers.py` : cardinaux de zéro à quelques milliards
      - [x] unités, dizaines, la série 11-16, « soixante-dix », « quatre-vingts »,
            « quatre-vingt-dix », les traits d'union et les « et » (« vingt et un »)
      - [x] « cent », « cents », « mille », « million(s) », « milliard(s) »
      - [x] le piège de l'article : « un chien » reste en lettres, « vingt et un
            chiens » devient « 21 chiens ». Un « un » isolé ne se convertit jamais.
      - [x] les faux amis : « pour cent », « cent pour cent », « des mille et des
            cents », « un million de fois » — vérifiés par des tests dédiés
- [x] Seuil `numbers_from` : en dessous, le nombre reste en lettres (la règle
      typographique française écrit en toutes lettres jusqu'à dix)
- [x] Câblage : `config.py`, `EDITABLE_FIELDS`, `PolishOptions`, le groupe
      « Mise en forme » des Réglages, `i18n.js` en FR et EN
- [x] `tests/test_numbers.py` : la table des cas ci-dessus, plus les non-régressions
      (une dictée sans nombre doit ressortir identique)
- [x] README + CHANGELOG

**Décidé en cours de route.** Les heures et les pourcentages sont finalement
inclus, et ils ignorent le seuil : une heure s'écrit toujours en chiffres.
« deux millions » garde son mot — « 2 millions », pas « 2000000 ». Le séparateur
de milliers ne commence qu'à cinq chiffres, sinon une année deviendrait
« 2 026 ».

**Restés hors périmètre :**

- les décimales (« trois virgule cinq ») : « virgule » est déjà consommé par la
  ponctuation dictée avant que les nombres passent
- les ordinaux (« premier » → « 1er ») : trop risqué, « premier ministre »
- l'anglais

## Lot 5 — Plus tard

- [x] Aperçu au fil de la parole (re-transcription périodique d'une fenêtre
      glissante — la même technique qu'eux, mais nous avons le GPU et pas eux)
      → fait le 22/07, détail en **Lot 5A** ci-dessous
- [ ] Modes de reformulation multiples (traduction, courriel, notes) avec prompt
      par mode et raccourci dédié → **même mur qu'en dessous** : traduire ou
      retourner un texte en courriel demande Ollama. Sans lui, seul le mode
      « notes » (mise en liste à puces) serait faisable, et c'est trop peu.
- [ ] Mode Commande : transformer par la voix le texte actuellement sélectionné
      → **écarté le 22/07, pas abandonné.** Comprendre une consigne libre
      (« traduis en anglais », « raccourcis ça ») demande un modèle de langage :
      Ollama n'est pas installé sur la machine et `polish_backend` vaut
      `heuristic`. La plomberie, elle, est vérifiée : en X11, `xclip -o
      -selection primary` lit la sélection courante et `xdotool` colle par-dessus.
      À reprendre le jour où Ollama entre dans la boucle. Une variante sans
      modèle reste possible — appliquer la mise en forme française d'Aparté à
      n'importe quelle sélection, sans voix.
- [ ] Statistiques d'usage (temps gagné, mots par minute)
- [ ] Import / export des réglages
- [ ] Fenêtre flottante pendant l'enregistrement → **repris et planifié le 22/07,
      voir Lot 5B.** Écartée en son temps comme faisant doublon avec l'icône de
      barre système ; l'aperçu au fil de la parole lui donne un vrai travail.

## Lot 5A — Aperçu au fil de la parole (fait, 22/07)

**Le manque.** Dans l'interface, on parle dans le vide : rien ne s'affiche tant
que l'enregistrement n'est pas arrêté. Sur une dictée d'une minute, c'est long.

**La technique.** Le navigateur accumule déjà l'audio en mémoire — le tableau
`chunks` de `startWavRecording()`. On lui ajoute un `snapshot()` qui encode en
WAV **ce qui a été capté jusqu'ici**, sans interrompre l'enregistrement. Toutes
les ~1,2 s, cet instantané part vers `/api/transcribe?preview=1` et le résultat
s'écrit dans l'éditeur, en provisoire. À l'arrêt, la transcription finale
l'écrase. On re-transcrit tout depuis le début à chaque passe : Whisper n'a pas
d'état à reprendre, et c'est ce qui lui permet de corriger ses propres erreurs.

**Le budget, mesuré le 22/07 sur la machine d'Alexandre** (GTX 1070, modèle
`small`, `int8`, en passant par `build_transcriber` donc avec le préchargement
CUDA de `transcription.py`) : 10 s d'audio se transcrivent en **0,24 s**. Une
dictée de deux minutes coûterait environ 3 s par passe. Sur processeur seul, la
même seconde d'audio coûte six fois plus (1,56 s pour 10 s) — d'où les deux
garde-fous ci-dessous.

**L'auto-régulation.** Jamais deux aperçus en vol. Le suivant n'est programmé
qu'au retour du précédent, plus un délai minimum. Sur une machine lente il y a
simplement moins d'aperçus ; rien ne s'empile, et aucun réglage de cadence n'est
à inventer.

**Le serveur est multi-fils.** `ThreadingHTTPServer` : un aperçu et la
transcription finale peuvent tomber en même temps sur le **même** modèle Whisper
gardé en cache. Un verrou les sépare. L'aperçu tente de le prendre **sans
attendre** et passe son tour s'il est occupé ; la finale, elle, attend son tour.
Sans ça, arrêter l'enregistrement fait entrer deux inférences concurrentes dans
un objet qui n'est pas prévu pour.

**Ce qui ne bouge pas :** l'historique ne s'écrit toujours qu'à la fin (il est
déjà côté navigateur, dans `transcribeBlob`) ; « Polir auto » ne s'applique qu'à
la fin, l'aperçu reste brut ; le bouton d'enregistrement garde son rôle de
projecteur, l'aperçu ne doit rien allumer d'autre.

- [x] `snapshot()` dans `startWavRecording()` — encode `chunks` sans fermer le flux
- [x] Boucle d'aperçu auto-régulée dans `app.js`, annulée à l'arrêt
- [x] Verrou de transcription dans `desktop.py` + `?preview=1` qui passe son tour
- [x] Réglage `live_preview` (vrai par défaut) : `config.py`, `EDITABLE_FIELDS`,
      groupe **Transcription** des Réglages, `i18n.js` FR et EN. Ce n'est pas du
      spéculatif : sans GPU, l'aperçu occupe un cœur en permanence, et le repli
      processeur est un chemin que le projet documente déjà.
- [x] Style du texte provisoire — passe `/impeccable`, encre atténuée, jamais
      d'opacité (voir l'invariant du 22/07 dans `CLAUDE.md`)
- [x] `i18n.js` : `st.preview` + le libellé du réglage, FR et EN
- [x] `tests/test_desktop.py` : un aperçu passe son tour pendant qu'une
      transcription tourne ; la finale attend et rend bien son texte
- [x] CHANGELOG, README, `DESIGN.md`, `CLAUDE.md`, `.impeccable/design.json`

**Risques assumés.** Le texte bouge pendant qu'on parle : Whisper révise sa
propre transcription d'une passe à l'autre, c'est inhérent à la technique. La
cadence de 1,2 s est un premier choix, à ajuster à l'usage.

### Décidé en cours de route

**Le réglage est allé dans le groupe Transcription, pas Mise en forme.** Il est
voisin de « Calcul », qui est exactement l'arbitrage dont il dépend.

**Les puces d'action s'éteignent pendant l'aperçu.** `syncActionState()` compte
désormais l'aperçu comme un traitement en cours. Sans ça, « Copier » pendant la
dictée rendait une version que la passe suivante allait réécrire — le même piège
que l'éditeur vide corrigé plus tôt dans la journée.

**Le provisoire ne repose pas sur la couleur seule.** Trois signaux simultanés :
l'encre recule à `ink-soft`, la ligne d'état (`role="status"`, donc annoncée)
dit « Aperçu — le texte se corrige jusqu'à l'arrêt », et les puces sont éteintes.

**Aucun nouveau jeton.** `ink-soft` existait et convient : 6,96:1 en clair,
7,26:1 en sombre sur le fond de l'éditeur, calculés. En ajouter un dont la valeur
double un jeton existant aurait été du bruit.

### Gain masqué

La première passe d'aperçu charge le modèle Whisper **pendant** que l'utilisateur
parle, au lieu de le faire attendre à l'arrêt. Mesuré à froid : 9,87 s pour la
première requête, 0,24 s ensuite. Le temps total ne change pas, mais il se paie à
un moment où personne n'attend.

### Vérifications passées

| Niveau | Ce qui a été prouvé |
|---|---|
| 175 tests unitaires | dont 3 neufs : l'aperçu cède son tour pendant une transcription, transcrit quand la voie est libre, et `live_preview` fait l'aller-retour par `/api/config` |
| Serveur réel sur le port 8799 | la page sert la case à cocher, `/api/config` expose `live_preview`, un aperçu lancé pendant la finale reçoit bien `{"text": null, "busy": true}` et la finale rend son texte |
| `app.js` chargé dans Node avec un faux DOM | 12 vérifications sur la boucle : une seule passe en vol, une réponse « occupé » ne touche pas à l'éditeur, un aperçu vide ne le vide pas, plus aucune passe après l'arrêt, l'encre et les puces reviennent à la fin |

Le harnais Node est resté hors du dépôt : le projet n'a pas d'outillage de test
JavaScript, et en installer un pour cette seule fonctionnalité aurait coûté plus
cher que ce qu'il garde.

### Suite immédiate, signalée à l'usage (22/07)

**Le générique inventé.** Deux dictées sur cinq finissaient par « Sous-titres
réalisés par la communauté d'Amara.org ». Corrigé le jour même, voir la section
« Hallucinations de Whisper » de `CLAUDE.md` et `hallucinations.py`.

**Rien ne s'affiche au raccourci clavier.** Attendu — l'aperçu vit dans la page.
Planifié en **Lot 5B** ci-dessous.

## Lot 5B — Fenêtre flottante au raccourci clavier (planifié le 22/07, pas commencé)

**Le manque.** L'aperçu du Lot 5A ne se voit que dans la fenêtre d'Aparté. Au
raccourci clavier, `aparte toggle` lance `arecord` en tâche de fond et rend la
main : entre les deux appuis, **aucun processus Aparté ne tourne**. Il n'y a ni
page, ni fenêtre, ni éditeur — rien sur quoi dessiner. Ce n'est pas un réglage à
activer, il faut créer la surface.

**Ce qui rend le chantier plus petit qu'il n'en a l'air.** Le serveur de bureau
tourne déjà au démarrage de session, et il possède déjà tout ce qu'il faut :

| Déjà là | Où |
|---|---|
| La boucle GTK sur le fil principal | `tray.run()` — c'est elle qui oblige le serveur HTTP à passer sur un fil de fond |
| La détection de l'enregistrement au raccourci | `Tray._refresh`, qui interroge `get_active_session()` chaque seconde pour changer l'icône |
| Le chemin du wav en cours et sa fréquence | le fichier de session, écrit par `start_toggle_recording()` |
| Le modèle Whisper chargé et gardé en cache | `handler_factory`, `transcriber_cache` |

Conséquence : **aucune nouvelle route HTTP, aucune modification de `toggle`,
aucun nouveau processus.** La fenêtre se greffe sur le sondage qui existe déjà.

**Mesuré le 22/07, et ça supprime une couche entière.** Un wav qu'`arecord` est
en train d'écrire se lit tel quel : `decode_audio` rend **tout ce que le fichier
contient réellement**, quoi qu'annonce l'en-tête. Un fichier dont l'en-tête
déclare 10 s alors qu'il n'en contient que 5 décode exactement 5 s, complet, sans
erreur ; un en-tête à `0xFFFFFFFF` passe aussi. Pas besoin de reconstruire
l'en-tête ni de recopier le fichier : on pointe le transcripteur dessus.

**Reste à vérifier quand on s'y mettra** (30 secondes, mais ça demande le micro,
donc pas fait) : à quel moment `arecord` écrit réellement son en-tête et s'il
tamponne ses écritures. Si un premier aperçu tombe sur un fichier encore vide, il
n'aura rien à afficher — le même cas que le silence de début côté navigateur, qui
est déjà traité en ne touchant pas à l'affichage.

### Forme envisagée

- Nouveau module `overlay.py`, **optionnel par construction comme `tray.py`** :
  sans PyGObject, `build_overlay()` rend `None` et rien ne change.
- Une `Gtk.Window` sans décoration, ancrée en bas au centre, au-dessus des autres.
- Le sondage de `Tray._refresh` gagne un second effet : session apparue → montrer
  la fenêtre et lancer la boucle d'aperçu ; session disparue → la cacher.
- La boucle tourne sur un **fil de fond** — une transcription sur le fil principal
  gèlerait GTK — et remonte le texte par `GLib.idle_add`, parce que GTK ne se
  touche que depuis le fil principal.
- Même auto-régulation que dans le navigateur : une seule passe en vol, la
  suivante programmée au retour de la précédente.
- Le style passe par `/impeccable` : c'est du GTK, pas du CSS de la page, donc il
  faut un fournisseur de style GTK qui reprenne les jetons de `DESIGN.md`. Mêmes
  règles : sérif pour le texte dicté, encre atténuée tant que c'est provisoire,
  pas d'aplat saturé — le projecteur reste le bouton d'enregistrement.

### Risques identifiés

1. **Le vol de focus, et c'est le risque numéro un.** Une fenêtre qui prend le
   focus fait perdre le curseur dans l'application cible, et le collage final
   atterrit ailleurs — ça casserait la fonction principale du produit pour un
   confort d'affichage. `set_accept_focus(False)` et `set_focus_on_map(False)`
   dès la première ligne, et c'est la première chose à tester.
2. **Wayland.** Positionner une fenêtre et la garder au-dessus n'y est pas
   garanti : il n'y a pas d'équivalent fiable à `set_keep_above`. Alexandre est en
   X11, donc ça marche chez lui ; ailleurs il faudra dégrader proprement.
3. **Deux modèles Whisper en mémoire.** L'aperçu tournerait dans le serveur, avec
   son modèle en cache ; la transcription finale, elle, tourne dans le processus
   `aparte toggle`, qui charge le sien. Les deux tiennent sur 8 Go, mais ils se
   disputent le GPU au moment précis où l'utilisateur arrête de parler.
4. **Serveur éteint** = pas de fenêtre, comportement d'aujourd'hui. Acceptable,
   mais à dire dans la documentation plutôt qu'à laisser deviner.

### Question tranchée le 22/07 : oui, et faite tout de suite

Le raccourci passe désormais par l'application déjà lancée quand elle répond.
**0,26 s contre 1,53 s** sur dix secondes d'audio, trois essais chacun. Le risque
n° 3 ci-dessus (deux modèles sur le GPU) disparaît donc avant même qu'on
construise la fenêtre. Fait dans `transcribe_via_running_app()`, câblé au point
d'entrée unique `transcribe_path()` de `cli.py`. Le repli local est intact et
couvert par `DelegationFallbackTest` — c'est le chemin que personne n'exerce à la
main, donc celui qui pourrirait en silence.

**Mesure ratée, et pourquoi la noter.** La première comparaison donnait la
délégation cinq fois **plus lente** (8 s contre 1,5 s). L'erreur était dans le
protocole, pas dans le code : le processus de contrôle forçait `language="fr"`
tandis que le serveur, sur une configuration par défaut, avait `language: null`.
Sans langue imposée, Whisper part en détection, se trompe sur du bruit de
synthèse et déroule du texte dans une autre langue. Le même fichier, dans le même
processus : **0,26 s en français imposé, 7,42 s sans**. À conditions égales, la
délégation gagne. Toute mesure de transcription doit fixer la langue des deux
côtés, sinon elle mesure la détection de langue.

**À creuser, séparément.** La configuration d'Alexandre porte `language: null`.
Les 7,42 s ci-dessus sont un pire cas sur du bruit — sur de la vraie parole
française, la détection trouve juste et coûte peu. Mais c'est exactement le
réglage que `À ne pas reprendre` désigne comme la faiblesse principale du
concurrent : « un seul modèle multilingue, aucun moyen de forcer une langue,
bascule vers l'anglais quand l'audio est moyen ». Lui proposer de mettre
« Français » dans les Réglages.

## Lot 5C — Les Réglages : le dictionnaire, puis la restructuration (planifié le 22/07, pas commencé)

Déclenché par Alexandre à l'usage : « le glossaire, c'était un réglage qu'il y
avait déjà dans Murmur et je le trouvais vraiment cool, ça permettait de mettre
un genre de dictionnaire personnel. Dans Aparté ça semble être plutôt ce qui est
dit versus ce qui est à écrire. Et ça, c'est peut-être un petit peu difficile à
comprendre pour tout le monde. D'ailleurs toute la partie réglage serait
certainement à revoir, restructurer et organiser. »

Critique complète : `.impeccable/critique/2026-07-23T02-28-52Z__src-aparte-assets-index-html.md`.
**20/40**, trois problèmes P1. Le détecteur automatique ne remonte rien : le
système visuel tient, le problème est d'organisation et de vocabulaire.

### Le diagnostic en une phrase

Un panneau bien fait qui a grandi sans plan. Dix-sept contrôles de poids égal
dans une colonne, où le plus personnel — le dictionnaire — est tout en bas, et le
plus dangereux — « Calcul » — à hauteur d'yeux. **Ces dix-sept réglages ne sont
pas de même nature, et les traiter comme s'ils l'étaient est la racine du reste.**

### Les trois défauts prouvés, pas supposés

| Où | Quoi |
|---|---|
| `app.js:354` | `if (i === -1) continue` — une ligne de vocabulaire sans `=` est **jetée en silence**. « cloud : Claude » se perd sans erreur, sans trace. |
| `polish.py:154` | `cleanup_level` supprime les **hésitations** (« euh », « heu »). Le libellé « Nettoyage / Léger / Moyen / Élevé » ne le dit à personne, et c'est le seul champ du groupe sans texte d'aide. |
| `index.html` | « Snippets » est un anglicisme en toutes lettres dans l'interface française, ce que les règles du projet interdisent. |

Plus un quatrième, de comportement : un échec d'enregistrement s'écrit dans la
ligne d'état de la page principale, c'est-à-dire **derrière le tiroir modal**.

### Le dictionnaire : la question d'Alexandre, et la réponse

Il a posé le vrai dilemme : faire saisir **un seul mot** (simple, mais il faut
espérer que l'application recoupe) ou **les deux** (précis, mais il faut avoir
observé l'erreur et savoir la reproduire — « toute une éducation à donner »).

**La prémisse est fausse, et c'est vérifié le 22/07 :** `faster-whisper` 1.2.1
expose `hotwords` **et** `initial_prompt`, tous deux acceptés de bout en bout sur
cette installation. On peut donner une liste de mots à Whisper **avant** qu'il
transcrive ; il penche alors vers eux quand le son est ambigu. La liste simple
n'est donc pas une version dégradée du couple entendu/écrit — **c'est un outil
différent, qui agit plus tôt.**

D'où deux réglages distincts, aux consignes distinctes :

1. **Mes mots** — une simple liste, passée en `hotwords`. Clients, outils,
   prénoms de collègues. La consigne tient en une phrase : « écris les mots que
   tu emploies et qu'un inconnu écrirait mal ». Aucune erreur à observer.
2. **Corrections** — entendu → écrit. Le filet pour ce qui passe quand même.

**Et la correction ne se saisit plus dans les Réglages.** Alexandre a mis le
doigt dessus : réécrire de mémoire l'erreur de l'application est absurde, puisque
l'application la connaît — elle est à l'écran, dans l'éditeur, au moment où elle
se produit. La capture se fait donc **depuis l'éditeur**, quand l'utilisateur
corrige le mot. Les Réglages ne servent plus qu'à relire et à supprimer.

**Expérience à faire avant de construire « Mes mots », et c'est Alexandre qui
l'a en main.** Le paramètre est vérifié, le gain ne l'est pas : le mesurer demande
de la vraie parole avec son vrai vocabulaire. Dicter deux fois « je travaille
avec Playwright et Wayland », avec et sans la liste. **Si le gain n'est pas net,
on ne construit pas « Mes mots »** et on garde uniquement la capture depuis
l'éditeur.

### La restructuration proposée

Classée par fréquence d'usage réelle, pas par architecture interne. Ce qui ne se
touche presque jamais part dans un `<details>` — l'élément **natif** de dépliage :
zéro JavaScript, clavier et lecteurs d'écran gratuits, et ça respecte la règle du
projet de garder les contrôles natifs natifs. Pas d'onglets maison.

**Visible d'emblée** (quatre champs maximum par groupe, contre sept aujourd'hui)

- **Dictée** — Langue · Aperçu pendant la dictée · Style · **Suppression des hésitations** *(ex-« Nettoyage »)*
- **Mon dictionnaire** — **Mes mots** *(neuf)* · **Corrections** *(ex-« Remplacements »)* · **Raccourcis dictés** *(ex-« Snippets »)*
- **Typographie française** *(ex-« Mise en forme » — c'est la signature du produit, elle mérite son nom)* — Espaces insécables · Nombres dictés · Espace à la fin · **Dictées très courtes** *(ex-« Texte court »)*

**Replié par défaut**

- **Matériel** — Microphone · Bip · Manière d'insérer
- **Avancé** — Modèle par défaut · Calcul · **Moteur de mise en forme** *(ex-« Moteur de polish »)* · Historique

### Ordre de bataille quand on s'y mettra

- [ ] L'expérience `hotwords` d'Alexandre — elle décide si « Mes mots » existe
- [ ] La perte silencieuse d'`app.js:354` : refuser en pointant la ligne, ou passer à une saisie par entrée
- [ ] Capture d'une correction **depuis l'éditeur**, pas depuis les Réglages
- [ ] Les six renommages, `i18n.js` en FR **et** en EN, `aria` compris
- [ ] Le reclassement des groupes et les deux `<details>`
- [ ] L'erreur d'enregistrement ramenée dans le pied du tiroir
- [ ] `aria-describedby` sur les champs de vocabulaire — leur aide est aujourd'hui dans un `<small>` voisin, non rattaché
- [ ] Passe `/impeccable` sur le rendu, puis re-critique pour voir bouger le 20/40

### Ne pas perdre en route

Les textes d'aide actuels sont le point fort du panneau — concrets, avec exemples
chiffrés (« vingt-deux personnes » devient « 22 personnes »). Et l'état vide du
micro est le modèle à suivre : il dit ce qui manque, la conséquence exacte, et où
aller. La restructuration doit les garder, pas les réécrire.

---

## À ne pas reprendre

- **La détection automatique de langue sans réglage.** C'est leur faiblesse
  principale : un seul modèle multilingue, aucun moyen de forcer une langue,
  bascule vers l'anglais quand l'audio est moyen. Notre réglage de langue
  explicite dans Whisper est exactement ce qui nous fait gagner sur le français.

  **Nuance apportée par l'usage réel, 22/07.** La faiblesse du concurrent est
  de ne pas avoir **le choix**, pas d'offrir la détection. Alexandre laisse
  volontairement « Auto » et le rapporte comme très fiable : il alterne français
  et anglais **à l'intérieur d'une même dictée** — des mots anglais au milieu
  d'une phrase française — et le taux d'erreur reste très faible. Forcer le
  français casserait ce cas d'usage. Ne pas lui reproposer de basculer sur
  « Français » : c'est un choix informé, pas un oubli. Ce qui compte, c'est que
  le réglage existe pour qui en a besoin.
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

