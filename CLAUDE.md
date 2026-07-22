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
  silence, côté lecture comme côté écriture.
- `_origin_is_ours()` garde toutes les routes POST : il faut que l'adresse par
  laquelle on nous a joints soit une des nôtres (`LOOPBACK_HOSTS`, ou celle sur
  laquelle le serveur écoute), **et** que l'`Origin` la nomme. Les deux
  conditions comptent : comparer `Origin` et `Host` entre eux ne prouve que leur
  accord, et une page dont le domaine a été réassocié à `127.0.0.1` arrive avec
  les deux à son nom. Une requête sans `Origin` passe : aucun navigateur n'en
  émet, c'est `curl` ou la ligne de commande — donc un processus local, qui
  pourrait de toute façon appeler `wtype` lui-même.
- `/api/update/apply` lance `git pull` puis `pip install`. Toute nouvelle route
  qui exécute une commande passe par la même porte, sans exception.

## Git

- Le remote s'appelle **`Murmur`**, pas `origin`. Ne pas supposer `origin`.
- Un `git pull` peut se déclencher pendant une session, mettre le travail de
  côté automatiquement et échouer à le remettre. Commiter tôt.
- Jamais de `Co-Authored-By: Claude` ni de mention d'IA dans les messages.

## Suivi

Le plan de travail, les décisions et l'historique des lots sont dans
[tasks/todo.md](tasks/todo.md). Le lire avant de reprendre.
