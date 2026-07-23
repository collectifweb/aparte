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
PYTHONPATH=src python3 -m unittest discover -s tests -t tests
```

Le `-t tests` est nécessaire : `tests/` n'a pas de `__init__.py`, et sans lui
la découverte échoue avec « Start directory is not importable ».

**Un test qui passe par `current_settings()` doit poser `APARTE_CONFIG` sur un
fichier temporaire**, et pas seulement `APARTE_RUNTIME_DIR`. Sinon le serveur
lit la vraie configuration de l'utilisateur : si `history_persist` y est vrai,
le test écrit dans `~/.local/state/aparte/history.json`, c'est-à-dire dans son
vrai historique de dictées. C'est arrivé le 22/07 (`HistoryEndpointTest`).

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
- `/api/update/apply` lance `git pull` puis `pip install`. Toute nouvelle route
  qui exécute une commande passe par la même porte, sans exception.

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
