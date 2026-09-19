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

**« Totalité » veut dire une ou plusieurs, bout à bout.** Sur du silence, Whisper
ne rend pas l'hallucination une fois : il la répète et en tronque les variantes.
Exiger qu'un seul motif couvre tout le texte laissait passer le cas le plus
courant — « Merci d'avoir regardé cette vidéo. Merci d'avoir regardé. » est
arrivé tel quel dans un historique le 01/08. La consommation se fait **pas à
pas** (`_is_only_generics`), jamais par un motif `(?:a|b|c)+` : les formules
partagent leurs débuts, et un `+` posé sur des alternatives ambiguës part en
retours arrière exponentiels dès quelques dizaines de répétitions, ce que Whisper
produit précisément dans ce cas. Dès qu'un mot dicté résiste à la consommation,
**rien** ne part : c'est la même règle que `numbers.py`, dans le doute on ne
touche à rien.

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

### États du micro et fermeture protégée

- Au raccourci, lorsqu'aucune capture n'existe, contrôler `is_processing()` sous
  la même transition que le démarrage et refuser avant bip/ouverture du micro.
  Une capture déjà active doit toujours pouvoir s'arrêter. Ce garde-fou n'est
  pas une file d'attente et n'interdit pas les autres commandes ou onglets.
- `lifecycle.get_dictation_state()` distingue `recording` (enregistreur vivant),
  `processing`, `recoverable`, `idle`. Les appelants exposent `unknown` si la
  lecture échoue ; ne jamais transformer une erreur de lecture en repos certain.
- Publier `processing_dictation()` avant de relâcher la transition d'arrêt,
  et le garder jusqu'à la livraison. Les marqueurs privés ne contiennent ni PID
  ni texte : le `flock` détenu prouve la vivacité, un marqueur abandonné se purge.
  Les routes HTTP enregistrent leur traitement avant de lire le corps ; cette
  lecture doit rester bornée pour qu'un client interrompu ne bloque pas Quitter.
- `prepare_shutdown()` garde la transition jusqu'à l'arrêt du serveur ou son
  remplacement par `exec`. Refuser pendant un traitement ; sinon arrêter la
  capture, sauvegarder sa récupération puis retirer l'original. Une panne laisse
  l'application ouverte et l'original suivi. Ne pas lancer de transcription ou
  de collage depuis Quitter. SIGINT/SIGTERM passent par ce même chemin.
- Le menu observe la capture du raccourci, pas les micros détenus par les
  navigateurs. Ne pas promettre que fermer Python arrête `getUserMedia`.
- Dans l'onglet, poser `opening`/`stopping` avant le premier `await` ; libérer les
  pistes avant d'attendre `AudioContext.close()`. La navigation invalide les
  permissions et réponses en vol, y compris après le décodage JSON. Une fermeture
  du contexte audio en erreur ne doit pas jeter les échantillons déjà capturés.

### Raccourci : diagnostic technique sans texte dicté

- `performance.operation` et `stage` mesurent le chemin réel, sans contourner
  `build_transcriber`. Identifiant aléatoire propagé par HTTP, contextes isolés
  par thread ; seule l'opération extérieure d'un contexte produit son total.
  `response_status` rend les erreurs HTTP traitées normalement visibles comme
  échecs. Les valeurs techniques et classes d'erreurs passent par des listes
  fermées dans `write_performance`, jamais du texte ni des chemins libres.
- Mesurer toute la consommation des segments Whisper. Lire le matériel effectif
  depuis le moteur, pas depuis la configuration `auto`. Un chargement CPU tardif
  reste inclus dans la transcription : ne pas sommer les étapes imbriquées ni
  les totaux CLI/HTTP corrélés. Voir [le guide](docs/mesures-performance.md).
- Les erreurs de mesure ne doivent jamais casser la livraison ni masquer
  l'exception d'origine. Les événements peuvent être perdus en contention ; les
  tests d'émission ne doivent pas exiger une trace disque complète en concurrence.

- Les commandes de raccourci utilisent `toggle --hotkey`. Ce mode est réservé
  à un processus CLI autonome : `technical_log.silence_process()` redirige
  définitivement stdout/stderr et les flux Python vers `/dev/null`. Ne pas
  restaurer les descripteurs à la sortie de `main` : les hooks `atexit` et les
  buffers natifs peuvent encore émettre du texte. Ne jamais appeler ce mode
  dans le processus du serveur ; ses tests s'exécutent dans des sous-processus.
- La CLI sans ce flag conserve ses sorties. Les options `--target stdout` et
  `--status` sont incompatibles avec `--hotkey`.
- `technical_log.write_event` n'accepte qu'une liste fermée d'événements et le
  nom de la classe d'erreur. Aucun message d'exception libre, texte transcrit,
  corps HTTP ou argument de collage. Seul le catch du démarrage d'enregistreur
  transmet le diagnostic borné de `RecordingStartError`.
- Le journal vit dans le dossier privé d'état `aparte/logs`, fichiers 0600 dès
  création, deux fichiers de 128 Kio au plus. Le verrou non bloquant porte sur
  le dossier stable ; une erreur ou contention peut perdre un événement, sans
  empêcher la dictée. Les chemins sensibles refusent les liens symboliques.
- Au démarrage du bureau, `migrate_hotkey_logging()` ne modifie que les commandes
  historiques reconnues de l'installation courante, jamais la touche ou le nom.
  Comparer les chemins d'interpréteur lexicalement : résoudre leurs symlinks
  confondrait deux venv distincts qui pointent vers le même Python système.
  La migration ne lit ni n'efface les anciens journaux.

### Réglages et historique : publier un fichier complet

- `config.py` verrouille toute fusion, initialisation et migration avec un
  `flock` sur un fichier stable, jamais effacé. Attente maximale de cinq secondes,
  puis erreur explicite ; les lecteurs voient l'ancienne ou la nouvelle version.
- Un chemin de configuration en lien symbolique est résolu pour partager le
  verrou de sa cible. Le verrou lui-même refuse liens et fichiers spéciaux.
  Ne pas écraser silencieusement un JSON invalide lors d'une mise à jour.
- `history.py` couvre lecture-modification-écriture et effacement avec son
  propre verrou stable. Attente plafonnée à 0,5 s : en cas de contention ou panne,
  l'opération d'historique peut être perdue, jamais la livraison bloquée par cette
  attente. Ce délai ne borne pas un système de fichiers lui-même bloqué.
- Les temporaires sont uniques, mode 0600 dès création, voisins de leur cible,
  synchronisés avant remplacement. Ne jamais tronquer la cible en place ni
  réutiliser un nom temporaire partagé. L'atomicité applicative ne promet pas la
  persistance du renommage après coupure électrique du répertoire.
- Après publication d'une migration Murmur, un retrait impossible de l'ancienne
  copie ne doit pas faire échouer la lecture de la nouvelle configuration.
  Les écritures externes et les anciennes versions sans verrou restent hors de
  cette coordination ; redémarrer le programme résident après mise à jour.

### Récupération des dictées en échec

- `recovery.py` conserve les captures dans le runtime privé pendant une heure,
  indépendamment de l'historique. Ne supprimer l'original qu'après sauvegarde
  réussie ; une panne du stockage conserve l'original hors expiration automatique.
- Le `flock` porte sur le dossier, y compris avant écriture des métadonnées.
  Réessai, suppression et purge s'excluent. Le fichier `lock` est uniquement un
  horodatage stable pour les sauvegardes incomplètes, pas un second verrou.
- L'expiration initiale ne se prolonge jamais. La purge tourne chaque minute
  dans le processus résident, et opportunément en CLI ; sans processus actif,
  l'effacement attend le prochain lancement. Une récupération engagée peut finir.
- L'API utilise directement le modèle partagé sous `inference_lock` ; jamais
  de délégation HTTP vers elle-même. Les captures finales du navigateur demandent
  `recover=1`, les aperçus et la délégation CLI ne le font pas.
- Sauvegarder le brut avant polissage. Le résultat navigateur reste séparé de
  l'éditeur ; son remplacement se confirme. Aucun collage automatique. Une
  réponse HTTP réussie ne détruit pas la capture, contrairement à une livraison
  CLI réussie : une réponse réseau peut se perdre.
- Valider aussi le Host des lectures HTTP privées. Libérer `inference_lock`
  même si la création, l'écriture ou la suppression du temporaire échoue.

### Session d'enregistrement : la course qui laissait un micro ouvert

- **La décision démarrer/arrêter est sous `toggle_session_transition()`** : verrou
  interprocessus non bloquant, libéré avant transcription. Ne jamais effacer le
  fichier de verrou (`flock` protège son inode). Les appels directs à start/stop
  prennent aussi ce verrou ; un arrêt non confirmé conserve la session.
- **Le diagnostic ALSA n'est plus jeté au démarrage.** Le fils hérite d'un fichier
  anonyme privé, pas d'une pipe qui perdrait son lecteur lorsque le lanceur quitte.
  La lecture d'erreur est plafonnée à 4 Kio ; le fichier lui-même n'est pas plafonné.
  `RecordingStartError.user_message` est destiné à la notification, `str(exc)`
  garde les détails techniques pour stderr. Ne pas afficher les 4 Kio à l'écran.
- **Toute exception après Popen nettoie le fils**, même une panne disque pendant
  publication. Les WAV possèdent maintenant un suffixe aléatoire après l'horodatage.
  Le ramassage doit reconnaître l'ancien et le nouveau format.

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

- Les valeurs de Corrections/Raccourcis sont du **texte littéral**. Toujours
  fournir une fonction de remplacement à `re.sub`, jamais directement la valeur
  utilisateur : une entrée `\s+` faisait échouer même les dictées qui ne la
  déclenchaient pas. Les vrais retours à la ligne restent autorisés.

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
  toujours** sur le texte du backend, qui n'est qu'un repli. Donc un check dont
  le `detail` **varie** ne doit pas porter de clé i18n statique : elle l'écraserait
  en silence et pourrait contredire l'icône. **Le `fix`, lui, n'est pas traduit** —
  `app.js` le rend tel quel dans un bloc à copier, parce que c'est une commande.
  C'est donc là que se pose une instruction qui dépend de l'état, sans toucher à
  la traduction. Le check `tray` s'appuie sur cette différence : sa phrase reste
  vraie des deux côtés, seule sa commande change.
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
- **Un serveur qui répond à l'API n'est pas un serveur vivant.** `already_running()`
  pose deux questions, et la seconde a coûté cher : l'API est-elle la nôtre, **et**
  la page d'accueil se sert-elle encore ? Un serveur laissé par une session ouverte
  avant le renommage Murmur → Aparté garde son code en mémoire, donc répond
  parfaitement à `/api/config` ; mais les fichiers statiques sont relus sur le
  disque **à chaque requête**, et le `git pull` de la mise à jour les a déplacés
  sous ses pieds. On lui passait la main, et l'utilisateur recevait une page 404
  après une installation annoncée réussie (vu le 31/07, un serveur du 25/07 encore
  en vie six jours plus tard). La page est le seul contrôle qui distingue les deux,
  parce qu'elle touche le disque.
  - **Détecter ne suffisait pas** : le port restait tenu, et repartir sur un port
    au hasard aurait cassé la dictée au raccourci, qui délègue au 8765 en dur.
    `stale_server.reclaim_port()` reprend le port, et c'est ce qui rend la panne
    sans conséquence.
  - **L'identité se prouve sur `/proc`, jamais sur le PID.** Même discipline que
    `_recorder_alive()` : deux signatures, la sous-commande `desktop` **et** le
    programme, cherché aux deux premières places d'`argv` seulement. L'installation
    vit dans `~/murmur` chez son auteur : un chemin qui contient « murmur » ne
    prouve rien, et un `SIGTERM` sur cette foi tuerait le processus d'un autre.
  - **La délégation, elle, ne demande que l'API** (`_api_responds()`). Transcrire
    n'a jamais eu besoin des fichiers de l'interface ; les confondre rechargerait
    Whisper pour rien — 1,53 s contre 0,26 s — au motif qu'une page HTML a bougé.
  - **Aucune escalade en `SIGKILL`.** Un serveur qui survit au `SIGTERM` le fait
    pour une raison qu'on ignore ; l'appelant repart sur un autre port.
- `/api/update/apply` lance un `git merge --ff-only` puis `pip install`. Toute
  nouvelle route qui exécute une commande passe par la même porte, sans
  exception.
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

### Installation Linux

- **PyGObject vient d'apt, jamais de pip.** Un venv créé sans
  `--system-site-packages` ne le verra donc **jamais** : pas d'icône de barre
  système, et `apt install` répond « déjà à la version la plus récente ». Deux
  conséquences qu'on a payées le 31/07 :
  - **L'installeur répare un venv existant**, il ne se contente pas d'en créer
    des bons. Son bloc de création est gardé par `if [[ ! -x ".venv/bin/python" ]]`,
    donc une installation d'avant le drapeau restait murée pour toujours. La
    réparation réécrit `pyvenv.cfg` sur place : recréer le venv réinstallerait des
    centaines de mégaoctets de Whisper et de CUDA pour une ligne.
  - **Le `doctor` distingue les deux pannes**, parce qu'elles demandent des gestes
    opposés (`walled_venv_config()`). Une icône absente peut vouloir dire « les
    paquets manquent » ou « le venv ne les voit pas » ; donner le mauvais conseil
    envoie tourner en rond, ce qui est arrivé. Seul le `fix` varie — voir la règle
    du `detail` et des clés i18n plus haut.

## Git

- Le dépôt est **`github.com/collectifweb/aparte`**. Il s'appelait `murmur` :
  GitHub redirige encore l'ancienne URL, donc un clone d'avant le renommage
  fonctionne sans rien dire, jusqu'au jour où la redirection tombera. Corriger
  avec `git remote set-url`.
- **Le nom du remote change d'une machine à l'autre** (`Murmur`, `origin`,
  `Aparte` selon le clone). Ne rien supposer : lire `git remote -v`.
- Un `git pull` peut se déclencher pendant une session, mettre le travail de
  côté automatiquement et échouer à le remettre. Commiter tôt.
- Jamais de `Co-Authored-By: Claude` ni de mention d'IA dans les messages.
- Messages en Conventional Commits, en minuscules, avec une portée quand elle est
  évidente : `feat(transcription):`, `fix(ui):`, `docs:`. Le corps dit **pourquoi**,
  pas seulement quoi. Même règle écrite dans `CONTRIBUTING.md`.

## Suivi

Le plan de travail, les décisions et l'historique des lots sont dans
[tasks/todo.md](tasks/todo.md). Le lire avant de reprendre.
