# Plan : la dictée qui ne sort pas

## Contexte

Sur un poste Linux Mint / Cinnamon / X11, une dictée au raccourci global affiche
ses notifications normalement puis ne produit rien : ni texte inséré, ni
presse-papiers, ni historique visible. Le matériel est complet — `xclip`,
`xdotool`, `arecord`, `notify-send` présents, `faster-whisper 1.2.1` installé.

Trois défauts se combinent.

### Un enregistrement peut devenir intouchable

`start_toggle_recording()` vérifie qu'aucune session n'est active, **puis** lance
`arecord`, **puis** écrit le fichier de session. Deux appuis rapprochés sur le
raccourci passent tous deux la vérification.

Reproduit en lançant deux fois la commande du raccourci coup sur coup :

```
A: Recording started: …/toggle-1784821369272.wav
B: Recording started: …/toggle-1784821369273.wav

arecord vivants     : 1  →  celui de A
toggle-session.json : absent
.wav qui grossit    : celui de A, que plus rien ne référence
```

Le micro est un périphérique ALSA exclusif : le second `arecord` meurt aussitôt,
silencieusement (`stderr=DEVNULL`). Mais il a écrit la session en dernier, donc
elle pointe vers un PID déjà mort. Le tray, qui sonde chaque seconde, voit ce PID
mort et **supprime le fichier de session**. Le premier `arecord` n'est plus
référencé : aucun appui ne peut l'arrêter. Un fichier de 59 Mo — 30 min 51 s — a
été constaté.

Un second chemin mène au même résultat : `Path.write_text()` tronque puis écrit,
donc un lecteur peut tomber sur un JSON coupé, et `get_active_session()` supprime
le fichier sur **toute** erreur de lecture.

Pendant qu'un enregistrement fantôme tourne, chaque nouvel appui repart sur un
micro déjà occupé, et les transcriptions en cours se sérialisent derrière
`inference_lock`. L'utilisateur voit « Transcription… » et rien ne revient.

### Une dictée vide efface le presse-papiers

`_notify_inserted()` affiche « Rien à transcrire » puis `return` — mais ce return
sort de la fonction de notification, pas de l'appelant. `paste_text("")` est donc
appelé, et il commence par `copy_text(text)` dans tous les modes. Vérifié :

```
presse-papiers rempli   : "TEXTE IMPORTANT DE L'UTILISATEUR"
après une dictée vide   : ''
```

### La notification promet avant d'agir

L'ordre est `_notify_inserted()` → `history.record()` → `paste_text()`. La
notification de succès s'affiche avant toute tentative d'insertion. Si
l'insertion échoue, l'erreur part sur `stderr` — que Cinnamon jette pour un
raccourci personnalisé. Succès annoncé, rien livré, aucune trace.

### La langue n'est pas fixée

`DEFAULT_CONFIG["language"]` vaut `None`, donc Whisper détecte la langue à chaque
dictée. Sur un audio pauvre il se trompe : 13 762 caractères d'API phonétique et
2 049 caractères de géorgien dans l'historique du poste, et un `Thank you.` rendu
sur deux secondes de silence français.

---

## Approche

**Une dictée qui échoue doit se voir et ne rien détruire.** Aujourd'hui elle se
tait et écrase.

Le plan ne cherche pas à filtrer les hallucinations de Whisper —
`hallucinations.py` couvre déjà les génériques signés, et un détecteur de
charabia serait spéculatif. Il ferme les endroits où le code transforme une
transcription ratée en perte silencieuse, et la course qui rend un enregistrement
intouchable.

---

## Étapes d'implémentation

### A — Une sortie vide ne touche à rien

`cli.py`, dans `toggle_dictation()` et `dictate_once()` : sortir avant
l'insertion quand `not output.strip()`. La notification « Rien à transcrire »
reste. `history.record()` ignore déjà le vide.

`.strip()` est le seuil du **vide structurel**, pas un jugement sur l'utilité du
texte. Ne pas y greffer de filtre sémantique.

### B — Notifier après l'action, rendre l'échec visible

Nouvel ordre : `history.record()` → insertion → notification de succès.
L'historique passe en premier délibérément : si le collage casse, le texte reste
récupérable par `aparte last`. C'est le seul filet quand `stderr` part à la
poubelle.

À l'échec de l'insertion : notification `urgency="critical"`, formulée sans rien
promettre — `history.record()` peut échouer silencieusement par conception :

> « Aparté a tenté de le garder dans l'historique ; essaie `aparte last` »

Puis propager l'exception, pour garder un code de retour non nul en ligne de
commande.

### C1 — Prise de session atomique et exclusive

`session.py` : `_claim_session()` publie le fichier de session par `os.link()`.
Le lien échoue avec `FileExistsError` si la cible existe, et rend le contenu
visible d'un seul coup.

```python
def _claim_session(session: RecordingSession) -> bool:
    path = get_session_path()
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps({...}), encoding="utf-8")
    try:
        os.link(temporary, path)
        return True
    except FileExistsError:
        return False
    finally:
        temporary.unlink(missing_ok=True)
```

Le perdant de la course **nettoie derrière lui** : il arrête son enregistreur et
supprime son `.wav`. Ne rien faire, c'est exactement l'orphelin de 31 minutes.

Le motif `tmp` + rename est celui de `history.py` ; `link()` au lieu de
`replace()` parce qu'ici on veut *échouer* si la cible existe, pas l'écraser. Le
temporaire est dans le même répertoire, donc le même système de fichiers.

Nettoyage opportuniste des `toggle-session.json.*.tmp` au début de
`start_toggle_recording()` : un processus tué entre l'écriture et le `finally`
en laisse.

### C2 — Trois états au lieu de deux

`get_active_session()` :

| État | Décision |
|---|---|
| Enregistreur vivant | session active — l'appui suivant arrête et transcrit |
| Mort, `.wav` ≥ 0,3 s capté | **terminée, à transcrire** — l'appui suivant la traite |
| Mort, `.wav` absent ou < 0,3 s | périmée — nettoyer la session **et** le `.wav` |

La durée se calcule sur la **taille du fichier**, jamais sur l'en-tête :

```python
_ARECORD_WAV_HEADER_BYTES = 44   # vrai parce que session.py impose -f S16_LE -c 1
MIN_TRANSCRIBABLE_SECONDS = 0.3


def _captured_seconds(session: RecordingSession) -> float:
    try:
        payload = session.audio_path.stat().st_size - _ARECORD_WAV_HEADER_BYTES
    except OSError:
        return 0.0
    return max(0.0, payload / (session.sample_rate * 2))
```

`arecord` sans durée explicite plafonne le WAV à 2 Gio et écrit un en-tête
bouche-trou de `0x40000000` trames, corrigé seulement à la fermeture propre.
Mesuré, même capture de 2,88 s :

| Fin de `arecord` | Taille disque | Durée réelle | En-tête |
|---|---|---|---|
| `SIGINT` (l'arrêt normal) | 92 048 o | 2,88 s | 2,88 s |
| `SIGKILL` | 92 044 o | 2,88 s | **67 108,86 s** |

Lire l'en-tête laisserait donc passer dix millisecondes de bruit — précisément
les miettes que le seuil doit rejeter.

### C3 — Plafonner la durée

`arecord -d <max_recording_seconds>`. Réglage dans `DEFAULT_CONFIG` et
`Settings`, **hors** `EDITABLE_FIELDS` : `app.js` énumère chaque champ à la main,
donc l'exposer sans contrôle ne servirait à rien, et ajouter le contrôle demande
`index.html`, `app.js` et `i18n.js` en français **et** en anglais — une tâche de
conception à part.

Défaut 300 s. **Repli sur 300 dès que `positive_int()` rend ≤ 0** : pas de
« 0 = illimité », sinon une faute de frappe rouvre le bogue qu'on corrige. Qui
veut deux heures écrit `7200`.

Grâce à C2, le plafond ne perd plus rien : `arecord` sort proprement, l'appui
suivant trouve une session terminée et transcrit ce qui a été capté. C'est une
troncature, pas une disparition.

### C4 — Ne pas signaler un PID recyclé

Le noyau réattribue les PID libérés : `os.kill(pid, 0)` répondrait vrai pour le
processus de quelqu'un d'autre, et `killpg()` enverrait un `SIGINT` à **tout son
groupe**.

```python
def _recorder_alive(session: RecordingSession) -> bool:
    try:
        cmdline = Path(f"/proc/{session.pid}/cmdline").read_bytes()
    except OSError:
        return False
    return b"arecord" in cmdline and os.fsencode(session.audio_path) in cmdline
```

Deux signatures : le binaire, et le chemin du fichier — unique par session, donc
il distingue même deux `arecord` simultanés. Remplace `_process_exists()` partout
où `session.py` décide qu'une session vit.

Contrôle de vivacité **juste après** avoir gagné le `link()` : sans lui, celui
qui gagne la course avec un enregistreur déjà mort annoncerait une dictée qui n'a
jamais commencé. Dans ce cas — micro occupé, `arecord` qui refuse — supprimer la
session, supprimer le `.wav`, et lever une erreur **visible**. Aujourd'hui
`stderr=DEVNULL` avale cet échec.

### D — Fixer la langue

`DEFAULT_CONFIG["language"] = "fr"`. Le produit se dit « français d'abord » ; il
doit livrer le français, pas un piège documenté dans son propre `CLAUDE.md`.

**Ne répare pas un poste existant** : `load_config()` applique le fichier
par-dessus les défauts, et un fichier portant `"language": null` explicitement
garde `null`. Corriger aussi le fichier du poste.

### E — Resserrer la dépendance

`faster-whisper>=1.0.2` dans `pyproject.toml`. `hotwords` n'existe qu'à partir de
cette version, alors que la contrainte actuelle autorise `>=1.0`. Dette
d'empaquetage, pas la panne locale — mais une installation neuve résolue sur
1.0.0 casserait.

### F — Clé de cache honnête

`desktop.py` : indexer `transcriber_cache` sur
`(transcriber, model, language, device, compute_type, whisper_cpp, hotwords)`
plutôt que sur le seul nom de modèle. Garder `transcriber_cache.clear()` dans
`_handle_save_config()` : il libère les modèles devenus inatteignables.

Cas réellement atteignables à documenter : édition manuelle du fichier de
configuration, appel externe à `update_config()`, synchronisation par un tiers.
**Pas** les variables `APARTE_*` — un serveur déjà lancé ne les voit pas changer,
et `transcribe_via_running_app()` coupe justement la délégation quand une
surcharge de transcription est présente.

---

## Tests

`PYTHONPATH=src python3 -m unittest discover -s tests -t tests`

- deux `_claim_session()` concurrents : un seul gagne ;
- démarrage concurrent : **aucun `arecord` vivant sans session le référençant** ;
  le perdant a supprimé son `.wav` ; la session du gagnant est intacte ;
- `link()` gagné mais enregistreur mort : session supprimée, `.wav` supprimé,
  erreur levée ;
- `_recorder_alive()` : PID d'un processus étranger vivant → faux ;
- `_captured_seconds()` : en-tête bouche-trou `0x40000000` sur un fichier court →
  durée calculée sur la taille. Ce test verrouille la décision : un retour à
  `wave.open()` le fait tomber ;
- PID mort + 1 s captée → session rendue, `.wav` **conservé** ;
- PID mort + 0,05 s captée → `None`, session et `.wav` nettoyés ;
- `stop_toggle_recording()` sur session morte : aucun `killpg` émis ;
- `-d` présent avec la valeur du réglage ; `0` et une valeur illisible → 300 ;
- `.tmp` orphelin nettoyé au démarrage ;
- A/B en simulant `paste_text`, `copy_text`, `notify` et `history.record` :
  quels appels, dans quel ordre, avec quels arguments. **Ne pas** tester l'état
  réel du presse-papiers — trop dépendant de `xclip` et de la session X11.

Les deux tests existants de `StartRecordingTest` simulent `Popen` avec le PID
4242 : ils casseront sur le contrôle de vivacité de C4 et doivent simuler
`_recorder_alive()`.

---

## Points de vigilance

**Ne pas promettre plus que ce qui est fermé.** Les deux courses observées sont
fermées. Un lanceur tué entre `Popen()` et son nettoyage peut encore laisser un
`arecord` sans session ; le plafond `-d` borne ce résidu, sans le rendre
transcrivable puisqu'aucune session ne le référence.

**`_ARECORD_WAV_HEADER_BYTES = 44` n'est vrai que pour ce chemin.** Il tient
parce que `session.py` impose `-f S16_LE -c 1`. Un futur enregistreur qui
écrirait des chunks supplémentaires le rendrait faux. Le nom et le commentaire
doivent rester attachés au WAV `arecord` du toggle.

**Le tray reste sur « enregistrement »** entre l'expiration du plafond et l'appui
suivant. Inexact au sens strict — le micro est fermé — mais afficher « au repos »
alors qu'une dictée de cinq minutes attend d'être transcrite serait pire.

**`aparte last --target paste`** garde le `stderr` invisible si l'utilisateur y
lie une touche. Hors de ce correctif, à noter.

**Deux copies du dépôt** au même commit, avec des remotes différents :
`/home/alexandre/Apps-coding/Murmur` (`Murmur` → `collectifweb/aparte.git`) et
`/home/alexandre/murmur` (`origin` → `collectifweb/murmur.git`). Le venv éditable
pointe sur la **seconde**. Un correctif écrit dans la première ne s'applique pas
au raccourci tant que les deux ne sont pas synchronisées.

**Le serveur de bureau doit être redémarré** : celui qui tourne date d'avant la
1.0.0 et garde son modèle Whisper en mémoire.

---

## Décisions explicitement écartées

- **Filtrer le charabia** (script inattendu, ratio de caractères non latins,
  longueur disproportionnée). Spéculatif et fragile, contraire à la règle du
  projet : dans le doute, ne rien toucher.
- **`try/except TypeError` autour de `hotwords`.** Masque une contrainte de
  version fausse au lieu de la corriger.
- **Watchdog surveillant `arecord`.** `arecord -d` fait le travail avec un
  drapeau, sans processus ni fil supplémentaire.
- **Quarantaine d'un fichier de session illisible.** Une fois l'écriture rendue
  atomique, un JSON illisible n'est plus un état transitoire normal : le
  supprimer **est** la récupération. Le garder bloquerait toute dictée future.
- **`has_insertable_text()`** pour traiter les invisibles type `U+200B`.
  Abstraction pour un usage unique, sur un cas que personne n'a rencontré.
- **Ne pas copier avant de coller.** Le passage systématique par le
  presse-papiers est un choix délibéré et documenté : c'est le filet quand le
  collage rate.
- **Supprimer la délégation au serveur.** Elle vaut 0,26 s contre 1,53 s, mesuré,
  et n'est pas en cause.
