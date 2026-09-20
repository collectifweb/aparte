# CLAUDE.md — Aparté

## Ce qu'est le projet

Application de dictée vocale pour Linux, locale et privée : rien ne sort de la
machine. Capture le micro, transcrit avec Whisper, met le texte en forme, puis
l'insère dans l'application active — en ligne de commande, via un raccourci
clavier global, ou depuis une petite interface web locale.

**Positionnement, qui tranche tous les arbitrages : Linux d'abord, français
d'abord.** C'est la seule application de dictée qui soigne réellement la
typographie française. Une fonctionnalité qui sert le français ou l'intégration
Linux passe devant une fonctionnalité générique.

Projet indépendant, sans lien avec [Murmure](https://github.com/Kieirra/murmure)
(dictée en Rust/Tauri, moteur Parakeet) ni avec Wispr Flow.

## Pile

- **Python 3.10+**, sans framework. Paquet dans `src/aparte/`.
- **Transcription** : `faster-whisper` en premier choix, puis `openai-whisper`,
  puis `whisper.cpp`. Repli automatique GPU → CPU quand CUDA est inutilisable.
- **Mise en forme** : `polish.py`, heuristique locale par défaut, ou Ollama.
- **Interface** : `desktop.py` sert un serveur sur `127.0.0.1:8765` et des
  fichiers statiques depuis `src/aparte/assets/` — HTML/CSS/JS écrits à la main,
  **aucune étape de compilation, aucune bibliothèque**. C'est une contrainte à
  conserver : elle rend le projet contribuable sans chaîne de construction.
- **Config** : `~/.config/aparte/config.json`, variables `APARTE_*`.

## Avant de toucher à quoi que ce soit de visible

Deux fichiers font autorité, à lire **avant** de coder un écran, un composant ou
un libellé :

- **[PRODUCT.md](PRODUCT.md)** — qui s'en sert, ce que le produit promet, la
  personnalité, les anti-références, les cinq principes de conception, et le
  niveau d'accessibilité engagé (contrastes AA, vérifiés par calcul).
- **[DESIGN.md](DESIGN.md)** — le système visuel : jetons OKLCH des deux thèmes,
  échelles, composants de référence, règles nommées, do's and don'ts. Le sidecar
  `.impeccable/design.json` porte les rampes tonales et les extraits HTML/CSS de
  chaque composant.

Les trois règles qui tranchent le plus souvent :

- **Le projecteur.** Une seule chose a le droit d'être un aplat saturé : le
  bouton d'enregistrement, et seulement pendant que le micro est ouvert. C'est ce
  qui rend l'état lisible du coin de l'œil.
- **Les deux voix.** La sérif est réservée au texte dicté (l'éditeur). Le châssis
  reste en sans-serif système.
- **Le calcul.** Aucune couleur n'entre sans que son contraste ait été calculé
  contre les fonds où elle sera posée. Seuil 4,5:1, y compris à 12 px et sur un
  aplat.

## Mesurer une transcription

**Fixer la langue des deux côtés, sinon on mesure la détection de langue.** Sur
le même fichier, dans le même processus : **0,26 s avec `language="fr"`, 7,42 s
avec `language=None`.** Sans langue imposée, Whisper lance une détection, se
trompe sur un audio pauvre et déroule du texte dans une autre langue.

Ça a produit une conclusion fausse le 22/07 : une comparaison où le processus de
contrôle forçait le français et le serveur non donnait la délégation « cinq fois
plus lente », alors qu'elle est six fois plus rapide.

Deuxième piège de la même famille : **la première requête paie le chargement du
modèle** (environ 8 à 10 s à froid, 0,24 s ensuite). Toujours chauffer avant de
chronométrer.

## Lancer les tests

Il n'y a **pas de `.venv` ni de `pytest`** sur cette machine. Les tests sont
écrits en `unittest` :

```bash
python3 scripts/run-tests.py
```

Ce lanceur isole configuration, données et caches avant tout import. Il exécute
`PYTHONPATH=src python3 -m unittest discover -s tests -t tests`.
Le `-t tests` est nécessaire : `tests/` n'a pas de `__init__.py`, et sans lui
la découverte échoue avec « Start directory is not importable ».

**Un test qui passe par `current_settings()` doit poser `APARTE_CONFIG` sur un
fichier temporaire**, et pas seulement `APARTE_RUNTIME_DIR`. Sinon le serveur
lit la vraie configuration de l'utilisateur : si `history_persist` y est vrai,
le test écrit dans `~/.local/state/aparte/history.json`, c'est-à-dire dans son
vrai historique de dictées. C'est arrivé le 22/07 (`HistoryEndpointTest`).

**Un test qui appelle `install_desktop_entry()` doit isoler `XDG_DATA_HOME`
**et** `XDG_CONFIG_HOME`**, pas seulement le premier. La fonction appelle
`remove_legacy_entries()`, qui atteint `~/.config/autostart` : sans le second, le
test supprime en silence un vrai ancien `murmur.desktop` de l'utilisateur. Même
famille que `HistoryEndpointTest` ; vu le 23/07 sur un test de la couture macOS
(M0).

**Un test qui laisse un chemin natif macOS appeler le vrai `notify()` empoisonne
l'interpréteur** : `notify.py` importe `gi` (GTK), qui échoue ici (« Unable to
register enum ») et laisse le module cassé pour les tests suivants — erreurs en
cascade, invisibles en isolé, seulement en suite. Stubber `notify` (et les helpers
importés paresseusement par le worker, `deliver_transcript` **et**
`polish_for_delivery`) au niveau du module dans le `setUp`, comme
`test_macos_recording.py`. Sans stubber `polish_for_delivery`, le vrai polissage
tourne sur les réglages factices du test et casse. Vu le 24/07 (M4).

## Invariants à ne pas casser

### Reprise depuis l'ancien nom (Murmur → Aparté)

Le projet s'appelait Murmur. Ces garde-fous existent pour ne pas casser les
installations en place — les retirer casserait silencieusement un poste déjà
configuré :

- `migrate_legacy_config()` déplace `~/.config/murmur/config.json` au premier
  lancement, et **seulement** si rien n'existe déjà à la nouvelle adresse.
- `get_env()` lit `APARTE_*` puis retombe sur `MURMUR_*`.
- La commande `murmur` est conservée, dépréciée, dans `[project.scripts]` : un
  raccourci clavier lié à l'ancien binaire continue de fonctionner.
- `install_hotkey()` reconnaît un raccourci créé avant le renommage (commande
  contenant `murmur`, ou libellé `Murmur dictation`) : il réutilise le même
  emplacement et garde la touche déjà choisie, au lieu d'en créer un doublon.
- `remove_legacy_entries()` supprime l'ancien lanceur, l'ancienne icône et
  l'ancienne entrée de démarrage. Sans ça : deux icônes au menu, et deux
  serveurs qui se disputent le port à l'ouverture de session.

### Icônes SVG

Le commentaire d'un fichier SVG va **à l'intérieur** de la balise racine, jamais
au-dessus. `gdk-pixbuf` reconnaît un format en reniflant les 256 premiers octets :
un en-tête plus long y cache le `<svg`, le chargeur répond « format non reconnu »
et le panneau dessine un creux vide à la place de l'icône. `aparte-tray.svg` a
vécu ça — sa balise racine était à l'octet 403, donc l'icône de barre système
n'apparaissait que pendant l'enregistrement, qui utilise l'autre fichier.
`test_every_svg_declares_its_format_within_the_sniff_window` monte la garde.

### Hallucinations de Whisper

`hallucinations.py` retire les génériques de sous-titrage que Whisper invente sur
du silence — « Sous-titres réalisés par la communauté d'Amara.org » en tête. Le
filtre est appelé depuis `transcription.py`, **pas** depuis `polish.py` : il doit
couvrir `--no-polish`, le raccourci global et l'aperçu au fil de la parole.

Deux listes, et la distinction est la sécurité du module : `SIGNED` porte un nom
de domaine ou de diffuseur, donc se retire partout ; `GENERIC` est dictable
(« merci d'avoir regardé cette vidéo »), donc ne se retire que si c'est la
totalité du texte. Ne jamais mettre un fragment seul comme « Amara.org » dans
`SIGNED` : « je cite Amara.org » est une dictée légitime.

**Le silence se coupe avant le décodage, pas après.** `FasterWhisperTranscriber`
passe `vad_filter=True` : sans lui, une capture sans parole fait boucler Whisper
jusqu'à sa limite de jetons — deux minutes de calcul sur un Mac Intel, puis une
suite de symboles livrée à l'utilisateur, pendant que l'enregistreur reste bloqué
sur « transcription » et que le raccourci ne peut plus rien lancer (vu le 25/07).
`hallucinations.py` ne pouvait pas l'attraper : ce n'était pas un générique de
sous-titrage. L'argument est **retiré**, jamais mis à `False`, quand l'installation
le refuse — une version assez ancienne pour refuser le VAD refuse l'argument
lui-même — et le refus se retient pour le processus entier. Réservé à
`faster-whisper` : les autres moteurs n'ont pas d'équivalent.

Le remplacement se fait par **une espace, pas par rien** : le motif mange
l'espace des deux côtés, et retirer un générique au milieu recollerait les
phrases voisines.

### Dictée : livrer avant d'annoncer, et ne rien détruire

- **Une sortie vide ne touche à rien.** `paste_text` copie avant de coller, dans
  tous les modes — donc `paste_text("")` remplace par du vide ce que
  l'utilisateur gardait en réserve. `toggle_dictation` et `dictate_once` sortent
  sur `not output.strip()` avant toute copie, tout collage, tout historique.
  `.strip()` est le seuil du **vide structurel**, pas un jugement sur l'utilité
  du texte : ne pas y greffer de détecteur de charabia.
- **La notification de succès vient après l'insertion**, jamais avant.
  L'inverse annonçait « ✍️ Inséré » puis échouait, et l'erreur partait sur
  `stderr` — que Cinnamon jette pour un raccourci personnalisé. Un échec émet sa
  propre notification `critical`. L'historique s'écrit **avant** l'insertion :
  c'est le seul filet si le collage casse.

### Session d'enregistrement : la course qui laissait un micro ouvert

- **`_claim_session()` publie par `os.link()`**, qui est atomique *et* échoue si
  la cible existe. Ne jamais revenir à `write_text()` : il tronque puis écrit,
  donc le tray — qui sonde chaque seconde — pouvait lire un JSON coupé, ne pas
  le comprendre, et **supprimer la session d'un enregistrement bien vivant**.
- **Le perdant de la course arrête son propre `arecord`.** Deux appuis à
  quelques millisecondes passaient tous deux la vérification « déjà en cours »,
  lançaient deux enregistreurs, et le second fichier de session écrasait le
  premier : l'enregistreur oublié devenait inatteignable. Un fichier de 59 Mo,
  31 minutes, a été trouvé comme ça.
- **`_recorder_alive()` lit `/proc/<pid>/cmdline`, pas `os.kill(pid, 0)`.** Le
  noyau réattribue les PID libérés : un test d'existence répond vrai pour le
  processus de quelqu'un d'autre, et `killpg` enverrait un `SIGINT` à tout son
  groupe. Deux signatures : `arecord`, et le chemin du fichier — unique par
  session.
- **Un démarrage s'annonce quand la capture est prouvée, pas quand `Popen` rend
  la main.** `Popen` revient dès l'`exec` — 0,001 s mesuré — alors qu'un
  `-D plughw:` déjà tenu par une autre application ne fait sortir `arecord` qu'à
  0,02-0,05 s, et que le premier échantillon n'arrive qu'à 0,17 s. Contrôler la
  vivacité tout de suite annonçait donc « Dictée en cours » à un enregistreur
  déjà mort ; l'appui censé arrêter ne trouvait plus de session et **rouvrait le
  micro pour un enregistrement entier**, que plus rien n'arrêtait. Deux captures
  de 300 s, avec la voix de l'utilisateur dedans, ont été perdues comme ça le
  24/07. `_capture_confirmed()` attend le premier échantillon écrit, ou la mort du
  processus ; encore vivant au bout du délai, il garde le bénéfice du doute — un
  micro lent vaut mieux qu'une dictée refusée. Et l'échec **se notifie** depuis
  `toggle_dictation` : `main()` n'écrit que sur `stderr`, que Cinnamon jette.
- **Processus mort + audio ≥ 0,3 s = session à transcrire, pas session
  périmée.** Supprimer ce `.wav` détruirait l'enregistrement à la seconde même
  où l'utilisateur appuie pour le récupérer.
- **`_captured_seconds()` calcule sur la taille du fichier, jamais sur
  l'en-tête.** Sans durée imposée, `arecord` plafonne le WAV à 2 Gio et écrit un
  en-tête bouche-trou de `0x40000000` trames, corrigé seulement en sortant
  proprement. Mesuré sur la même capture de 2,88 s : `SIGINT` → en-tête juste ;
  `SIGKILL` → en-tête annonçant **67 108 s**. `_ARECORD_WAV_HEADER_BYTES = 44`
  n'est vrai que parce que `session.py` impose `-f S16_LE -c 1`.
- **Ce qui reste ouvert, et qu'il ne faut pas prétendre fermé** : un lanceur tué
  entre `Popen()` et son nettoyage peut encore laisser un `arecord` sans
  session. Le plafond `-d` borne ce résidu, il ne le rend pas transcrivable.
  **Ce résidu s'est produit quatre fois en quatre jours** (24/07 ×2, 25/07,
  27/07), chaque fois une capture de 9 600 044 octets — 300 s pile. Le micro
  étant ouvert en accès exclusif (`-D plughw:`), il refusait toute dictée
  jusqu'au plafond, en accusant « une autre application » : c'était Aparté. La
  cause exacte **n'est toujours pas établie** — le double appui a été écarté (dix
  essais, cinq intervalles), et le correctif du 25/07 (`_capture_confirmed`)
  était déjà installé le 27/07. Ne pas écrire qu'on l'a trouvée.
- **`_reap_forgotten_recorders()` ramasse ce résidu au démarrage d'une dictée**,
  et c'est ce qui rend la panne sans conséquence sans qu'on en connaisse
  l'origine. Trois règles :
  - Il ne tourne **que** faute de session active. Ce qu'une session suit encore
    est la dictée en cours, pas un oubli — et `cli.py` l'arrête, il ne redémarre
    pas.
  - **Deux secondes de grâce**, mesurées sur l'horodatage du nom du fichier. Un
    appui concurrent peut être entre son `Popen()` et son `_claim_session()` :
    son enregistreur a quelques centièmes de seconde et ne doit pas être tué.
  - **Le `.wav` reste sur le disque.** Il porte de la voix, et `/run` se vide à
    la déconnexion. Reconnaissance par le dossier d'exécution **et** le nom
    `toggle-<horodatage>.wav` : sans ce filtre, un `SIGINT` partirait vers
    l'`arecord` de n'importe qui.

### Typographie

- La typographie française s'applique **après** les remplacements et les
  raccourcis de `polish.py`. L'inverse casse leur correspondance par mot, parce
  que l'apostrophe courbe ’ n'est pas une frontière de mot.
- Espace insécable U+00A0, **pas** la fine U+202F : la fine est la règle
  stricte, mais elle s'affiche en carré blanc dans trop d'applications, et la
  dictée finit dans Slack ou un courriel.
- Ne jamais ajouter d'espace avant un `:` suivi de `/` ou d'un chiffre —
  sinon `https://` et `14:30` sont cassés.
- Les nombres (`numbers.py`) passent **avant** `_space_punctuation`, sinon la
  règle ci-dessus ne voit pas les chiffres qu'ils viennent d'écrire. Le module
  ne touche jamais une suite qu'il n'a pas su analyser : dans le doute, rien ne
  bouge. Français seulement.

### Interface

- Toute chaîne visible passe par `i18n.js`, en français **et** en anglais, y
  compris les `aria-label` et les `title` (via `data-i18n-aria` /
  `data-i18n-title`). Un libellé écrit en dur dans `index.html` est un bogue :
  un lecteur d'écran configuré en français annoncerait de l'anglais.
- Le panneau de diagnostic traduit chaque check **par clé** (`app.js` :
  `tKey("check." + c.key + ".detail", c.detail)`), et la clé i18n **gagne
  toujours** sur le texte du backend — ce dernier n'est qu'un repli si la clé
  n'existe pas. Donc un check dont le `detail` **varie** (selon l'OS ou selon un
  état) ne doit **pas** porter de clé i18n statique, sinon elle l'écrase en
  silence et peut contredire l'icône (« va autoriser » à côté d'un ✓). Le check
  `config` montre la convention : pas de `check.config.detail`, son chemin
  dynamique passe. Corollaire : deux OS ne peuvent pas donner deux textes à une
  même clé — un check partagé (`recorder`, `clipboard`) doit avoir un libellé
  neutre, vrai des deux côtés. Vu le 23/07 sur les diagnostics macOS (M2a).
- Le texte d'aide d'un champ se pose **hors** de son `<label>`, et se rattache
  par `aria-describedby`. Dans le label, il entre dans le **nom accessible** du
  contrôle : « Nombres dictés » s'annonçait suivi de ses trois phrases d'aide.
  Le patron est `<div class="field">` + `<label for>` + contrôle + `<small id>`.
- Une ligne de vocabulaire sans `=` n'est **jamais** avalée en silence. Dans
  « Corrections » elle est refusée en pointant son numéro ; dans « Raccourcis
  dictés » elle continue l'entrée précédente, parce qu'une signature tient sur
  plusieurs lignes — et n'est refusée que si aucune entrée n'a commencé. Les
  deux champs ne portent pas la même donnée, d'où deux règles.
- Une erreur qui survient dans un tiroir s'affiche **dans le pied du tiroir**
  (`#settings-error`), jamais par `status()` : la ligne d'état de la page est
  sous le voile modal, donc invisible au moment précis où elle compte.
- Un contrôle désactivé change de **teinte** (`--ink-disabled`), jamais
  d'opacité. `opacity` mélange le libellé au fond de la page et non à celui du
  contrôle : en thème clair, l'encre à 0,45 tombait à 1,69:1. Ça se voyait
  d'autant moins que l'état ne durait qu'une transcription — il est maintenant
  permanent tant que l'éditeur est vide.
- Le style de focus est **global et unique** (`:focus-visible` dans `app.css`).
  Ne pas le redéfinir par composant, et ne jamais y remettre un `border-radius` :
  ça déforme l'éditeur le temps du focus, l'outline suit déjà le rayon natif.
- Les tiroirs sont modaux au clavier : `Échap` ferme, `Tab` y reste enfermé, le
  focus revient au bouton déclencheur. La logique est dans le gestionnaire
  `keydown` global de `app.js` ; ajouter un tiroir suffit, il est pris en charge.
- Toute animation ajoutée doit avoir sa contrepartie dans le bloc
  `@media (prefers-reduced-motion: reduce)` en fin de `app.css`, en laissant
  l'état lisible à l'arrêt.
- L'espace vide sous la barre d'actions est **réservé**, pas oublié : c'est la
  place du panneau d'historique. Ses contraintes sont écrites dans `DESIGN.md`
  (§ Plan de travail) et dans `tasks/todo.md` (§ D6). Ne rien y poser d'autre
  sans les relire.

### Serveur

- `EDITABLE_FIELDS` dans `desktop.py` filtre les clés acceptées par
  `/api/config`. Un nouveau réglage absent de cette liste est ignoré en
  silence, côté lecture comme côté écriture. Il doit **aussi** figurer dans
  `DEFAULT_CONFIG` : `update_config()` jette toute clé qui n'y est pas. Et
  l'inverse est vrai aussi : `EDITABLE_FIELDS` **ne crée aucun contrôle**.
  `app.js` énumère chaque champ à la main, au chargement comme à la sauvegarde ;
  un réglage ajouté à la liste sans passer par `index.html`, `app.js` et
  `i18n.js` (français **et** anglais) n'est éditable nulle part.
  `max_recording_seconds` est délibérément hors de la liste : réglage de fichier.
- Le cache de transcripteurs de `handler_factory` est indexé sur **tout ce qui
  construit le transcripteur**, pas sur le seul nom de modèle.
  `_handle_save_config()` vide bien le cache, mais une configuration modifiée
  ailleurs — édition à la main, appel externe à `update_config()` — rendrait
  sinon un transcripteur périmé sans que rien ne le signale.
- `hotwords` (« Mes mots ») n'existe que dans `faster-whisper`. `build_transcriber`
  ne le passe qu'à ce moteur ; `openai-whisper` et `whisper.cpp` n'ont pas
  d'équivalent, et le réglage doit s'y effacer sans bruit plutôt que de promettre
  ce que le moteur ne peut pas tenir. Une liste vide se passe en `None`, pas en
  chaîne vide : une amorce vide entre quand même dans le décodeur.
- `_origin_is_ours()` garde toutes les routes POST : il faut que l'adresse par
  laquelle on nous a joints soit une des nôtres (`LOOPBACK_HOSTS`, ou celle sur
  laquelle le serveur écoute), **et** que l'`Origin` la nomme. Les deux
  conditions comptent : comparer `Origin` et `Host` entre eux ne prouve que leur
  accord, et une page dont le domaine a été réassocié à `127.0.0.1` arrive avec
  les deux à son nom. Une requête sans `Origin` passe : aucun navigateur n'en
  émet, c'est `curl` ou la ligne de commande — donc un processus local, qui
  pourrait de toute façon appeler `wtype` lui-même.
- `inference_lock` dans `desktop.py` sérialise les transcriptions. Le serveur est
  un `ThreadingHTTPServer` et le modèle Whisper est **un seul objet** gardé en
  cache : sans ce verrou, l'aperçu au fil de la parole et la transcription finale
  entrent dedans en même temps à la seconde où l'utilisateur arrête de parler.
  L'aperçu (`?preview=1`) prend le verrou **sans attendre** et rend
  `{"text": null, "busy": true}` s'il est occupé — le passer en bloquant ferait
  patienter la finale derrière une passe devenue inutile.
- `transcribe_via_running_app()` fait transcrire par l'application de bureau déjà
  lancée quand elle répond, au lieu de recharger un modèle dans un processus neuf
  (0,26 s contre 1,53 s, mesuré le 22/07). Trois règles à ne pas casser :
  **une chaîne vide est une réponse valide** (« aucune parole ») et seul `None`
  veut dire « je n'ai pas pu demander » — les confondre referait le travail pour
  rien ; **la délégation est désactivée dès qu'une surcharge `APARTE_*` de
  transcription est dans l'environnement** (`_ENV_OVERRIDES`), parce qu'elle
  n'existe que dans ce processus et que l'application relit le fichier de
  configuration ; **le repli local doit rester intact et testé**, c'est le chemin
  que personne n'exerce à la main et qui pourrirait sans qu'on le voie.
- `/api/update/apply` lance un `git merge --ff-only` puis `pip install`. Toute
  nouvelle route qui exécute une commande passe par la même porte, sans
  exception.
- **Sur Darwin, aucune route POST ne réalise d'effet système.**
  `_DARWIN_DISABLED_POST_ROUTES` (`desktop.py`) rend 404 `/api/paste`, `/api/copy`
  et `/api/update/apply` quand `is_macos()` — le serveur résident détient des
  permissions TCC qu'un navigateur n'a pas, une route qui les emploie serait un
  proxy de privilèges. Le critère est **« effet système déclenché par HTTP »**,
  pas « permission TCC » : toute route POST future à effet système (insertion,
  presse-papiers, commande, réglage système) doit rejoindre cet ensemble. Le garde
  est un test de route explicite dans `do_POST`, **après** l'Origin-check. Les
  actions natives Mac passent par la CLI, le raccourci in-process ou le tray.
  (M3, `docs/plan-portage-macos-m3.md`.)
- **Sur macOS, la capture active de la bascule vit en mémoire du serveur**
  (`macos_recording.py`, `RecordingController`), pas dans `session.py` (arecord,
  `/proc` — Linux only). Trois garde-fous que M5 ne doit pas casser : son
  `recording_lock` est **distinct** d'`inference_lock` (les mélanger bloque
  l'aperçu au fil de la parole) ; son `transcribe_fn` transcrit **en local** sous
  `inference_lock`, jamais par un appel HTTP à soi-même ; le module importe `cli`
  **paresseusement** (dans le worker), car `desktop → macos_recording → cli →
  desktop` cyclerait à l'import. Le contrôleur n'est **déclenché par aucune route
  HTTP** (invariant Darwin ci-dessus) : seul `GET /api/recording-state`, en lecture
  seule, l'observe ; son vrai déclencheur est le raccourci in-process (M5).
  Durcissement du 24/07 (contre-expertise) : le worker **polit** le texte brut via
  `polish_for_delivery` (partagé avec la CLI) avant de le livrer — le retirer livre
  du texte sans typographie française sur le chemin macOS principal ; le polissage
  vit dans le worker, **jamais** dans `transcribe_fn`/`_transcribe_capture`, qui
  reste une primitive de transcription pure. Chaque capture possède sa capsule
  (`_Capture`) et un callback en fermeture : un callback tardif ou un stream mal
  fermé ne peut pas contaminer la capture suivante (donc `_close_stream` reste
  best-effort). (M4, `docs/plan-portage-macos-m4.md` ;
  durcissement `docs/plan-portage-macos-m4-durcissement.md`.)
- **Sur macOS, le raccourci clavier global déclenche l'enregistrement
  in-process** (`macos_hotkey.py`, `macos_runloop.py`, M5). Les garde-fous :
  - **Une seule run loop AppKit sur le fil principal** ; le serveur HTTP passe sur
    un fil daemon (comme sous le tray GTK). `RegisterEventHotKey` (API Carbon, sans
    permission « Surveillance de l'entrée ») n'existe que si une run loop vivante
    lui livre ses événements, et `NSApplication` doit exister **avant**
    l'inscription — d'où le point d'accroche `on_ready()`, appelé une fois la
    boucle vivante, où l'inscription se fait (jamais avant).
  - **Le callback Carbon ne bloque jamais la run loop** : `HotkeyDispatcher`
    répartit **hors run loop** sur un **worker unique** et **filtre les répétitions
    à l'arrivée** de l'événement (horodatage sous son verrou, décision avant de
    réveiller le worker), **jamais à l'exécution**. Un fil par appui avait un vrai
    bug : `toggle()` garde son verrou pendant l'I/O de démarrage, donc un
    double-appui pouvait **arrêter l'enregistrement que le premier venait de
    lancer**. Ne pas y revenir ; une file de capacité 1 ne corrige pas non plus.
  - **`run_desktop()` possède le contrôleur** (rendu par
    `handler_factory(return_controller=True)`) : il câble le déclencheur et appelle
    `shutdown()`. Le handler HTTP ne fait qu'**observer** (`_recording_controller`,
    `hotkey_state`).
  - **Démontage : conserver avant de quitter.** `controller.shutdown()` ferme
    la capture et garantit une copie privée avant de laisser le tray, le
    raccourci, le dispatcher et le serveur se fermer. Si la sauvegarde échoue,
    le menu reste vivant pour réessayer ; une transcription bloquée déjà
    sauvegardée ne bloque pas la sortie. Aucun collage tardif après validation
    de la fermeture. Un arrêt forcé pendant la capture en RAM reste destructeur.
    `server.shutdown()` ne s'appelle jamais depuis le fil qui sert les requêtes.
  - **`Settings.hotkey` reste hors `EDITABLE_FIELDS` HTTP, dans `DEFAULT_CONFIG`.**
    Vide = aucun raccourci. Le menu natif « Configurer le raccourci… » inscrit
    puis sauvegarde la combinaison et garde l'ancienne si l'opération échoue.
    Une modification par la CLI/fichier exige encore un redémarrage. Format
    d'entrée `ctrl+opt+d`, sortie `⌃⌥D`. Un seul backend Carbon par processus
    conserve son callback et attribue des identifiants distincts ; les événements
    étrangers retournent `eventNotHandledErr`.
  - **L'état du raccourci s'observe, il ne déclenche aucun effet système** :
    `GET /api/hotkey-state` (lecture seule, autorisée sur Darwin) rend
    `{registered, configured_key, status, error}`. `serve_macos` **publie** cet état
    (`HotkeyState`) sur la classe du handler ; `doctor` le lit **in-process** (le
    handler le passe à `collect_diagnostics`), le `doctor` CLI l'auto-requête
    (borné 0,5 s) sinon repli statique lu dans la config. Le check `hotkey` a un
    **`detail` dynamique sans clé i18n** (le panneau web ne voit que des détails
    neutres — combi / OSStatus / commande ; la phrase de repli est CLI seule) et
    n'est **jamais essentiel**. Échec d'inscription au démarrage → notification
    `critical`, **serveur vivant**. (M5, `docs/plan-portage-macos-m5.md`.)
  - **`registered: true` veut dire « macOS a accepté l'inscription », jamais « le
    raccourci fonctionne ».** Mesuré en M8 sur Big Sur : `RegisterEventHotKey`
    accepte ⌘Espace que Spotlight détient, **et** accepte la même combinaison
    demandée par un second processus Aparté. Aucun OSStatus dans les deux cas. Un
    raccourci mort est donc indistinguable d'un raccourci vivant, et le chemin
    « échec → notification `critical` » garde une porte que macOS n'ouvre pas : il
    reste juste, il est inatteignable. Ne pas coder de vérification passive
    là-contre — il faudrait observer un vrai appui.
- **Sur macOS, l'icône de barre de menus tient la boucle** (`macos_tray.py`, M6).
  C'est le correctif du défaut d'usage de M8 : rien n'indiquait que le micro était
  ouvert. Les garde-fous :
  - **`rumps` devient la boucle quand un tray existe.** `rumps.App.run()` appelle
    `AppHelper.runEventLoop()` — exactement ce que fait `_appkit_run_loop`, et il n'y
    a qu'un fil principal. `MacTray.run_loop(on_ready, on_quit)` est donc le
    remplaçant direct du point d'injection de M5 ; `serve_macos` garde tout le reste
    (raccourci, état publié, démontage ordonné) et retombe sur `_appkit_run_loop`
    quand il n'y a pas d'icône.
  - **`quit_button=None` est obligatoire.** Sinon rumps ajoute son propre « Quit »,
    câblé sur `quit_application()` → `NSApplication.terminate_`, **qui ne revient
    jamais de `run()`** : le `finally` de `serve_macos` ne s'exécuterait pas. D'où un
    démontage **idempotent** (drapeau + `RLock`, chaque étape dans son `try`) passé à
    la boucle et appelé par « Quitter » **avant** de terminer.
  - **`recording_snapshot()` se lit sans verrou.** `RecordingController._lock` est
    tenu pendant `ensure_microphone_access()` — jusqu'à 30 s de fenêtre TCC — et le
    tray sonde depuis le fil principal : une lecture verrouillée figerait la barre de
    menus au pire moment. La cohérence tient à l'**ordre d'écriture** (`_started_at`
    posé avant `RECORDING`, effacé après `PROCESSING`) et à l'atomicité des lectures
    d'attributs. Ne pas y ajouter un état qui devrait être cohérent avec un autre.
    Même raison pour `controller.shutdown(timeout=2.0)`, borné au démontage.
  - **Le tray observe, il ne pilote pas.** Aucun article ne démarre ni n'arrête une
    dictée : c'est le raccourci in-process qui le fait, comme l'exige l'invariant
    Darwin (aucun effet système déclenché de l'extérieur du processus).
  - **La mise à jour du menu ne relance rien.** `os.execv` relancerait
    l'interpréteur, pas l'application responsable vue par TCC — question M7. D'où
    `_INSTALLED_PENDING_RESTART` dans `update.py` : drapeau **local au processus**,
    armé sur `DONE_MARKER`, qui fait rendre `restart_required` à `check_update()`
    **avant** git et avant le réseau — sans lui, `__version__` reste périmé et la même
    version serait reproposée indéfiniment. Le panneau web n'offre pas le bouton là
    où la route est refusée (`can_apply`), il renvoie à l'icône.
  - **Le check `doctor` s'appelle `menubar`, pas `tray`** : `tray` est celui du
    panneau GTK Linux et porte déjà `check.tray.detail` (PyGObject), qui écraserait un
    détail macOS. `detail` dynamique donc **sans clé i18n**, jamais essentiel.
  - **Le fait « l'icône existe » vit dans la mémoire du serveur**
    (`macos_tray._BUILD_OUTCOME`, local au processus). Le `doctor` CLI tourne **à
    côté** : il doit demander, par `GET /api/tray-state` (lecture seule, autorisée sur
    Darwin), et retombe sur ce qui est installé si personne ne répond. Sans cette
    question, il affichait « missing Menu-bar icon · start Aparté » **pendant que
    l'icône était dans la barre** — vu à la première validation native de M6, et
    exactement le défaut que M5 avait déjà corrigé pour le raccourci. Le panneau web
    ne demande jamais : il est servi par le processus qui a construit l'icône.
  - **Sous rumps, un SIGINT tue le processus net** — observé le 25/07 sur le Mac de
    validation : aucun `KeyboardInterrupt`, aucun démontage, exactement comme sous
    `_appkit_run_loop`. La contre-expertise supposait l'inverse (rumps réinstalle
    SIGINT par `installMachInterrupt()`, donc la main reviendrait) ; c'est faux. Sans
    dégât — tout est en mémoire — mais la **seule** sortie qui démonte est
    « Quitter ».
  - **Le démontage s'annonce** : « Stopping desktop server. » est imprimé en tête de
    `teardown()`, jamais sur la branche `KeyboardInterrupt`. Sans cette ligne,
    « Quitter a tout démonté » et « le processus est mort » sont indistinguables — ni
    processus survivant, ni port pris, dans les deux cas. La validation native de M6
    s'y est cassé les dents avant de la déplacer.
    (M6, `docs/plan-portage-macos-m6.md` ; journaux
    `.claude/mac-validation/journaux/m6-etape*.log`.)
- **Le micro macOS se demande explicitement, sinon on enregistre du silence.**
  Ouvrir un flux PortAudio **ne déclenche aucune fenêtre TCC** : le flux s'ouvre
  « sans erreur » pendant que le statut reste `not_determined`, et la capture ne
  contient que du silence — sur un Mac neuf, la première dictée ressemblait à une
  application cassée (M8). Seul AVFoundation demande. `ensure_microphone_access()`
  (`audio.py`) garde les **deux seuls** chemins de capture — `_record_wav_sounddevice`
  (CLI) et `_start_locked` (raccourci) — et **attend** la réponse, car elle arrive
  de façon asynchrone et repartir aussitôt capterait précisément ce silence. Un
  refus lève plutôt que de livrer du vide ; un sondage qui ne sait pas répondre
  (`"unknown"`) ne bloque **jamais** une dictée. Corollaire : une dictée dans le
  navigateur n'accorde le micro qu'à **Safari**, jamais à Aparté — le plan M8 le
  supposait et se trompait.
- **Le pont Carbon déclare toutes ses signatures ctypes.** Sans `restype` ni
  `argtypes`, ctypes suppose des entiers 32 bits : `GetApplicationEventTarget`
  rendait un pointeur amputé de sa moitié haute (`0x00007ffc9f816590` lu
  `-0x607e9a70`) et Carbon plantait dessus — `Segmentation fault` à la toute
  première exécution native (M8). `ItemCount` et `ByteCount` sont des
  `unsigned long` **64 bits**, pas des `UInt32`. Les classes de structures se
  construisent **une seule fois** : ctypes rapproche un argument de son `argtype`
  par identité de classe, donc une classe reconstruite à chaque appel serait
  rejetée par la signature déclarée pour elle.
- **Sur macOS le bip est le seul retour qui existe** (`_DEFAULT_BEEP = is_macos()`
  dans `config.py`) : pas d'icône de barre de menus avant M6, et une application
  « accessory » n'affiche rien. En M8, le testeur a cru que son appui n'avait rien
  fait, a réappuyé, et a arrêté l'enregistrement que le premier venait de lancer —
  alors que le filtre anti-répétition marchait parfaitement. Sous Linux l'icône du
  panneau fait déjà le travail, donc le défaut y reste à faux.
- **Une capture tuée entre son `.wav` et sa transcription laisse la voix de
  l'utilisateur sur le disque** : le `finally` qui supprime n'a pas lieu.
  `sweep_orphan_recordings()` balaye au démarrage du serveur, **seulement** les
  fichiers de plus d'une heure — jamais la capture vivante d'une autre instance —
  et sur un motif qui épargne les bips mis en cache (`aparte-<uid>-beep-*.wav`).
- **L'unité de mise à jour est un tag de version, jamais la pointe de la
  branche.** `update.py` compare `__version__` au plus haut tag `vX.Y.Z`
  accessible depuis la branche suivie, et avance jusqu'à **ce tag**. Compter les
  commits notifiait une mise à jour pour un `docs:` et faisait réinstaller
  l'application pour une virgule ; pire, ça pouvait livrer une fonctionnalité à
  moitié écrite. Être en avance sur le dernier tag se lit « à jour » : c'est
  voulu, du travail non publié n'est pas une mise à jour.
- Les tags se lisent avec **git, pas avec l'API d'un hébergeur**. L'installation
  est déjà un clone, les notes de version sont déjà dans `CHANGELOG.md` :
  interroger un service web ajouterait une dépendance réseau et un mode de panne
  pour une information que le dépôt porte déjà. Le `fetch` prend `--tags`, sinon
  les versions n'arrivent pas.
- **La version se déclare à deux endroits** : `src/aparte/__init__.py` et
  `pyproject.toml`. Les désynchroniser fait mentir le panneau de mise à jour,
  qui lit `__version__`.

### Installation macOS (M7, `macos_desktop.py`)

Plan : `docs/plan-portage-macos-m7.md`. Ce qui suit est établi ; ce qui attend
encore la mesure est nommé comme tel à la fin.

- **Distribution par une formula Homebrew, jamais un cask.** Homebrew a supprimé
  `--no-quarantine` (5.1, mars 2026) et **retire tous les casks qui échouent au
  contrôle Gatekeeper le 1er septembre 2026** — leur audit exige signature *et*
  notarisation. Un cask non signé installe une application que macOS annonce
  comme endommagée. Les formulas ne sont pas concernées. Ne pas rouvrir sans un
  fait nouveau daté.
- **La `.app` est construite sur la machine de l'utilisateur, jamais
  téléchargée.** C'est ce qui la garde hors de la quarantaine : l'attribut est
  posé par ce qui télécharge, et il n'y a rien à télécharger. Corollaire :
  aucun compte Apple prévu pour cette hypothèse de distribution locale. La CI
  macOS et une preuve interactive des autorisations restent nécessaires.
- **L'exécutable principal du bundle est un Mach-O, jamais un script.** Apple
  DTS (thread 678819) : *« TCC expects its bundled clients … to use a native main
  executable. … If your product uses a script as its main executable, you're
  likely to encounter TCC problems. »* C'est tout le bénéfice du lot qui en
  dépend — sans bundle valide, les fenêtres continuent de dire « Terminal ».
- **Le bundle ne change pas d'une version d'Aparté à l'autre.** Une signature
  ad-hoc n'a pas d'identité d'équipe : l'exigence TCC est attachée au `cdhash`.
  Un bundle qui change fait oublier les autorisations à macOS **en laissant la
  case cochée** dans les Réglages Système — la panne est donc silencieuse. Donc :
  ni la version d'Aparté, ni le code Python, ni un chemin qui bouge n'entrent
  dedans, et le lanceur nomme l'interpréteur par le chemin `opt` que Homebrew
  garde stable (jamais `Cellar`, qui disparaît au premier `brew upgrade`). Le
  lanceur porte sa **propre** version, fixe. Un test compare deux constructions
  faites sous deux `__version__` différents.
- **La compilation du C généré fait partie des tests.** La première version
  appelait `snprintf` sans `<stdio.h>` : un avertissement sous `gcc`, une
  **erreur** sous un `clang` récent — l'installation aurait échoué sur tout Mac à
  jour, et aucun test de chaîne ne l'aurait vu.
- **`CFBundleIdentifier` (`ca.collectifweb.aparte`) est définitif.** Le changer
  après diffusion créerait une seconde application aux yeux de macOS, et
  l'utilisateur devrait tout réautoriser sans comprendre pourquoi.
- **`codesign` est un prérequis dur**, jamais best-effort : un bundle mal signé
  présenté comme installé est pire que pas d'installation, et Apple Silicon
  refuse d'exécuter du code natif non signé.
- **La `.app` vit dans `~/Applications`, hors du préfixe Homebrew.** Dedans,
  `brew upgrade` la reconstruirait — donc un nouveau `cdhash` à chaque version.
  Le prix, assumé : `brew uninstall` la laisse en place, d'où `aparte
  uninstall-app` et sa mention dans les caveats.
- **Le `post_install` d'une formula ne peut pas créer le bundle** : les blocs
  d'installation sont sandboxés et `HOME` y est remplacé par un répertoire
  temporaire. D'où un parcours à **deux commandes** (`brew install`, puis
  `aparte install-app --open`) et non « installer → ouvrir ». Écrit tel quel dans
  la doc plutôt qu'arrondi.
- **Un LaunchAgent lance `/usr/bin/open`, jamais le lanceur directement** :
  exécuter le lanceur ferait de `launchd` le processus responsable et
  l'attribution TCC repartirait à zéro. `RunAtLoad` seul, **pas de `KeepAlive`**
  (le job sort tout de suite, il serait relancé en boucle), chemins absolus —
  `launchd` ne fait pas d'expansion, donc jamais de `~`.
- **Le modèle se télécharge à vue, et c'est l'application qui le déclenche**
  (`model_download.py`, M7f). Une route qui tirerait 500 Mo serait un effet
  système déclenchable depuis un navigateur — même critère que le reste de
  l'invariant Darwin. `GET /api/model-state` **observe** seulement, et rend 404
  tant que rien n'a été lancé dans ce processus. Trois règles :
  - **La progression somme tous les blocs du dépôt exact, pas seulement les
    `.incomplete`.** `huggingface_hub` télécharge dans `<sha>.incomplete` puis
    renomme : ne compter que les incomplets ferait **reculer** la barre à chaque
    fichier terminé.
  - **Taille totale inconnue = pas de pourcentage.** La barre passe en
    indéterminée et perd son `aria-valuenow` ; ce qui reste vrai, le nombre de
    mégaoctets arrivés, s'affiche quand même. Sous `prefers-reduced-motion` le
    fragment glissant **disparaît** au lieu de s'immobiliser : arrêté, il se
    lirait « 30 % téléchargés ».
  - **Déclenché sur Darwin seulement.** Sous Linux l'installation est un clone
    dont le README explique déjà cette récupération unique ; télécharger 500 Mo
    au lancement y serait un changement de comportement.
  Le fait vit dans la mémoire du processus qui télécharge, comme
  `macos_tray._BUILD_OUTCOME` : le `doctor` qui tourne à côté garde `model_ready`,
  lu sur le cache, comme vérité persistante.
- **Une installation Homebrew n'est pas un clone, et `update.py` le sait**
  (état `brew`, M7e). Sans lui, le menu répondait « Aparté ne tourne pas depuis
  un dépôt git » à quelqu'un qui avait installé exactement comme on le lui avait
  dit. La détection lit le chemin du module (`…/Cellar/<formule>/<version>/…`),
  pas la sortie de `brew` : prouvable sans Mac, et aucun processus ouvert à
  chaque vérification. L'état **s'ajoute** à `manual`, il ne le remplace pas — un
  clone garde son chemin, sous Linux comme sur le Mac d'un testeur — et
  `apply_update()` refuse de bouger des fichiers qui appartiennent à Homebrew.
- **Ce que M7-0 doit encore trancher, et qu'on ne devine pas** : `execv` contre
  processus enfant surveillé pour le lanceur, et signature ad-hoc contre
  certificat local auto-signé. Les deux se mesurent
  (`.claude/mac-validation/m7/`), comme M8 a mesuré le nombre d'événements par
  appui plutôt que de le supposer. **Tant que M7-0 n'a pas répondu, les lots M7c
  à M7h ne s'écrivent pas.** La demande explicite du 19 septembre autorise les
  correctifs du prototype et la CI ; elle ne tranche pas le lanceur, la signature
  finale, la formula ni le démarrage à la connexion.

### Fiabilisation du 19 septembre 2026

État actuel : [tasks/fiabilisation-macos.md](tasks/fiabilisation-macos.md).
L'audit est un instantané historique ; ce suivi distingue les corrections
exécutées sous Linux de ce qui exige encore un vrai Mac.

- `recovery.save_and_claim()` publie **et verrouille** la capture avant toute
  inférence native. Garder le verrou jusqu'à la livraison évite qu'une suppression
  concurrente efface la seule copie. Sauver le brut avant polissage ; supprimer
  après livraison réussie seulement. Le retry conserve sa source jusqu'à
  suppression explicite/expiration, même si la réponse HTTP est perdue.
- Captures de secours : fichiers privés, durée d'une heure, nettoyage périodique
  quand le serveur tourne ou à la prochaine utilisation. Aucun minuteur ne tourne
  après l'arrêt du processus. Historique temporaire Mac : fichier privé de 24 h,
  nettoyé à la prochaine lecture/écriture, pas de promesse de RAM ou de logout.
- Le cache modèle n'est prêt qu'avec les fichiers requis non vides du dépôt et
  de la révision exacts. Ce n'est pas une vérification de leur contenu. La capture
  native attend la préparation ; le navigateur observe, son inférence
  faster-whisper Mac utilise exclusivement le snapshot local vérifié. Changer le
  modèle exige de le préparer depuis le menu natif. Le sondage reprend après une
  erreur réseau transitoire ; aucun pourcentage sans taille totale connue.
- L'interface Mac utilise le presse-papiers du navigateur au clic. Aucune route
  native de collage/copie n'est réactivée. La langue des menus vient de Foundation,
  l'insertion Unicode compte les unités UTF-16 et garde les paires de surrogates.
- Installation du prototype : signature vérifiée avant et après publication,
  verrou interprocessus, construction sur le volume de destination, ancienne
  application conservée puis restaurée en cas d'erreur. Si la restauration échoue,
  ne jamais effacer la sauvegarde. Les ressources FR/EN sont toutes présentes,
  indépendantes de la locale de construction. Une première reconstruction de
  l'ancien bundle peut changer son empreinte et demander `--force` + réautorisation.

## Git

- Le remote s'appelle **`Murmur`**, pas `origin`. Ne pas supposer `origin`.
- Un `git pull` peut se déclencher pendant une session, mettre le travail de
  côté automatiquement et échouer à le remettre. Commiter tôt.
- Jamais de `Co-Authored-By: Claude` ni de mention d'IA dans les messages.
- Messages en Conventional Commits, en minuscules, avec une portée quand elle est
  évidente : `feat(transcription):`, `fix(ui):`, `docs:`. Le corps dit **pourquoi**,
  pas seulement quoi. Même règle écrite dans `CONTRIBUTING.md`.

## Suivi

Le plan de travail, les décisions et l'historique des lots sont dans
[tasks/todo.md](tasks/todo.md). Le lire avant de reprendre.
