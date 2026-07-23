# Round 1 — Plan : « rien ne sort » après une dictée

## 1. Contexte

### Le signalement

Aparté v1.0.0, poste Linux Mint / Cinnamon / X11. L'utilisateur dicte au
raccourci global (`<Super>End` → `python -m aparte toggle --target paste`) :

> « Ça fait les notifs et tout mais rien ne sort comme texte, ni auto-inséré,
> ni dans mon presse-papiers, ni dans l'historique. »

### Ce que j'ai mesuré sur la machine

Environnement (tout est présent, rien ne manque) :

| Élément | Valeur |
|---|---|
| Session | X11, Cinnamon, `DISPLAY=:0`, pas de Wayland |
| Presse-papiers | `xclip` présent ; `wl-copy`, `xsel` absents |
| Frappe | `xdotool` présent ; `wtype`, `ydotool` absents |
| `faster-whisper` | **1.2.1** — `WhisperModel.transcribe()` accepte bien `hotwords` |
| Serveur de bureau | PID 1938973, en vie depuis le **22/07 16:20**, soit ~19 h |
| Install | venv éditable pointant sur `/home/alexandre/murmur/src` |

Historique persistant (`~/.local/state/aparte/history.json`), le matin du 23/07 :

| Heure | Longueur | Contenu |
|---|---|---|
| 10:37:11 | 41 | `1.5cm x 2.5cm 2.5cm x 2.5cm 3.5cm x 2.5cm` |
| 10:56:09 | **13 762** | `ʕ ʔ ʔ ʕ ʔ ʕ ʔ ʔ ʔ ʔ ʔ ʕᴗᴗᴗᴗ …` |
| 11:06:23 | **2 049** | `Თთ თთ თთ ლეიეიიიიიიი ᵇ ᵔᵗᵘᵕᵗᶉᵗ …` (géorgien) |
| 11:06:23 | 68 | `Encore un test pour voir si ça marche adéquatement on dirait que non` |
| 11:07:43 | 34 | `Oh bah merde ça a marché super bien` |

Dossier runtime (`/run/user/1000/aparte/`) à 11:06, deux `.wav` abandonnés :

- `toggle-1784817155662.wav` — **59 244 054 octets**, soit **30 min 51 s** à
  16 kHz / 16 bit / mono
- `toggle-1784819010435.wav` — 216 054 octets, soit 6,75 s

L'écart entre les deux horodatages de nom vaut 1 854,8 s, exactement la durée du
gros fichier : le premier `arecord` a tourné sans discontinuer jusqu'au démarrage
du second.

### Deux reproductions directes

**(1) La langue n'est pas fixée.** `~/.config/aparte/config.json` porte
`"language": null`. J'ai enregistré 2 s de silence via le chemin réel du
raccourci. Sortie : `Thank you.` — en anglais, copié dans le presse-papiers.

**(2) Une dictée vide efface le presse-papiers.** Vérifié en exécutant le code
du projet :

```
presse-papiers rempli   : "TEXTE IMPORTANT DE L'UTILISATEUR"
après une dictée vide   : ''
```

### Le verdict de Codex sur ce même bogue, et pourquoi je l'écarte

Interrogé en amont, Codex a désigné une incompatibilité de version : `hotwords`
passé inconditionnellement à `WhisperModel.transcribe()`
([transcription.py:128-130](../../../src/aparte/transcription.py#L128-L130))
alors que [pyproject.toml:35](../../../pyproject.toml#L35) autorise
`faster-whisper>=1.0`, argument apparu seulement en 1.0.2.

**Ce n'est pas la panne observée** : la machine a 1.2.1 et `inspect.signature`
confirme que `hotwords` y est. Mais **la contrainte est bel et bien trop lâche**
et casserait une installation neuve résolue sur 1.0.0/1.0.1. Je retiens le
correctif, en le classant comme dette d'empaquetage et non comme cause.

---

## 2. Diagnostic

Je distingue ce que je prouve de ce que j'infère. C'est le point sur lequel
j'aimerais le plus être challengé.

### Prouvé

**P1 — `paste_text("")` détruit le presse-papiers.**
[clipboard.py:39](../../../src/aparte/clipboard.py#L39) copie systématiquement
avant de coller. [cli.py:333-338](../../../src/aparte/cli.py#L333-L338) appelle
`paste_text(output)` **même quand `output` est vide** : `_notify_inserted()`
affiche « 🤫 Rien à transcrire » puis `return`, mais ce `return` sort de la
fonction de notification, pas de `toggle_dictation()`. Une dictée sans parole
écrase donc ce que l'utilisateur avait en réserve. Même défaut dans
`dictate_once()` ([cli.py:284-289](../../../src/aparte/cli.py#L284-L289)).

**P2 — La notification promet avant d'agir.** Toujours
[cli.py:333-338](../../../src/aparte/cli.py#L333-L338), l'ordre est
`_notify_inserted()` → `history.record()` → `paste_text()`. « ✍️ Inséré (aussi
dans le presse-papier) » s'affiche donc **avant** toute tentative d'insertion. Si
`paste_text()` lève — `ClipboardError`, `CalledProcessError` de `xdotool`, écran
verrouillé — l'utilisateur voit un succès et n'a rien. L'exception remonte à
[cli.py:89-91](../../../src/aparte/cli.py#L89-L91) qui écrit `error: …` sur
`stderr` : **Cinnamon jette la sortie d'un raccourci personnalisé**. L'échec est
donc structurellement muet. C'est la description exacte du signalement.

**P3 — `"language": null` fait tourner la détection de langue à chaque dictée.**
Le piège est déjà écrit dans le [CLAUDE.md](../../../CLAUDE.md) du projet
(« se trompe sur un audio pauvre et déroule du texte dans une autre langue »),
mais `DEFAULT_CONFIG["language"]` vaut `None`
([config.py:25](../../../src/aparte/config.py#L25)) : le projet livre le piège
comme réglage par défaut. Les 13 762 caractères d'API phonétique, les 2 049 de
géorgien et mon `Thank you.` en sont la sortie.

**P4 — Aucun plafond de durée.**
[session.py:83-94](../../../src/aparte/session.py#L83-L94) lance `arecord` sans
`-d`. Rien, dans le code, ne borne un enregistrement. Un `arecord` oublié tourne
jusqu'à saturer le disque : 59 Mo constatés.

**P5 — Les `.wav` orphelins ne sont jamais ramassés.**
[session.py:69-72](../../../src/aparte/session.py#L69-L72) : quand le processus
est mort, `get_active_session()` supprime le fichier de session et rend `None` —
mais **laisse le `.wav`**. Le nettoyage n'existe que dans le `finally` de
`toggle_dictation()`, qui ne s'exécute que sur le chemin nominal.

### Inféré, non prouvé

**I1 — L'enchaînement qui a produit le symptôme.** Ma reconstruction : un
`arecord` part en vrille (cause inconnue) → 31 minutes de micro ouvert → à
l'arrêt, Whisper avale une demi-heure de quasi-silence avec détection de langue
→ plusieurs minutes de calcul pour 13 762 caractères de charabia → pendant ce
temps l'utilisateur réappuie, voit « ⏳ Transcription… », et rien ne revient
parce que `inference_lock`
([desktop.py:345](../../../src/aparte/desktop.py#L345)) sérialise les passes
derrière celle qui mouline, avec un `DELEGATE_TIMEOUT` de 300 s
([desktop.py:121](../../../src/aparte/desktop.py#L121)).

**Je ne sais pas pourquoi le premier `arecord` n'a pas été arrêté.** `killpg`
sur un `start_new_session=True` devrait fonctionner. Je propose de borner le
dégât sans prétendre connaître la cause — et je veux que ce point soit
attaqué.

**I2 — La panne s'est résorbée seule.** À 11:07 les dictées repassent. Cohérent
avec « la file s'est vidée », pas prouvé.

### Requalifié à la baisse (je m'étais trompé)

**R1 — Le cache du transcripteur.** J'avais annoncé à l'utilisateur que changer
la langue dans les Réglages restait sans effet jusqu'au redémarrage du serveur.
**C'est faux** : `_handle_save_config()`
([desktop.py:421](../../../src/aparte/desktop.py#L421)) appelle
`transcriber_cache.clear()` après chaque enregistrement. Le défaut réel est plus
étroit : `get_transcriber()`
([desktop.py:199-214](../../../src/aparte/desktop.py#L199-L214)) reçoit `active`
mais **ne l'indexe que par nom de modèle**. Une config modifiée hors de
l'interface — édition à la main, `APARTE_*`, futur point d'écriture — rend un
transcripteur périmé sans que rien ne le signale. C'est un piège latent, pas la
panne.

---

## 3. Approche

Le fil directeur : **une dictée qui échoue doit se voir et ne rien détruire.**
Aujourd'hui elle se tait et écrase.

Je ne cherche pas à deviner pourquoi Whisper hallucine ni à filtrer sa sortie —
`hallucinations.py` couvre déjà les génériques signés, et un détecteur de
charabia serait spéculatif et fragile. Je m'attaque aux quatre endroits où le
code **transforme une transcription ratée en perte silencieuse**.

Ordre d'exécution : A et B d'abord (ils règlent le symptôme décrit), puis C, D, E.

### A — Une sortie vide ne touche à rien

Dans `toggle_dictation()` et `dictate_once()`, sortir avant l'insertion quand le
texte est vide après `.strip()`. La notification « 🤫 Rien à transcrire » existe
déjà et reste. `history.record()` ignore déjà le vide
([history.py:54-56](../../../src/aparte/history.py#L54-L56)) — rien à y changer.

### B — Notifier après, et rendre l'échec visible

Réordonner : `history.record()` → insertion → notification de succès. Envelopper
l'insertion pour qu'un échec produise une notification `urgency="critical"`
disant que le texte est dans l'historique et récupérable par `aparte last`,
puis re-lever pour garder le code de retour non nul.

L'ordre historique-avant-insertion est délibéré : si le collage casse, le texte
reste rattrapable. C'est le seul filet quand `stderr` part à la poubelle.

### C — Plafonner l'enregistrement et ramasser les orphelins

Passer `-d <plafond>` à `arecord`. Nouveau réglage `max_recording_seconds`,
défaut **300 s**, ajouté à `DEFAULT_CONFIG`, `Settings` et `EDITABLE_FIELDS`
(l'invariant du projet exige les trois). `arecord -d` sort proprement et
finalise l'en-tête WAV.

Compléter `get_active_session()` : quand le processus est mort, supprimer aussi
le `.wav` en même temps que le fichier de session.

**Compromis assumé** : au plafond, l'audio est perdu — aucun processus n'est là
pour le transcrire. Je considère qu'une dictée de plus de 5 minutes perdue vaut
mieux qu'un disque saturé et une demi-heure de silence envoyée à Whisper. À
challenger.

### D — Fixer la langue

Deux volets :

1. `DEFAULT_CONFIG["language"] = "fr"` — le projet se dit « français d'abord »,
   il doit livrer le français, pas un piège documenté.
2. **Ça ne répare pas ce poste** : `load_config()` fusionne `DEFAULT_CONFIG` puis
   applique le fichier, et ce fichier porte `"language": null` explicitement.
   Une correction manuelle de `~/.config/aparte/config.json` est nécessaire, en
   plus du changement de défaut.

### E — Resserrer la dépendance

`faster-whisper>=1.0.2` dans `pyproject.toml`. Un `try/except TypeError` autour
de `hotwords` serait un contournement qui masque une contrainte fausse.

### F — Clé de cache honnête

Indexer `transcriber_cache` sur les champs qui construisent réellement le
transcripteur — `(transcriber, model, language, device, compute_type, whisper_cpp, hotwords)` —
au lieu du seul nom de modèle. `transcriber_cache.clear()` dans
`_handle_save_config()` devient redondant ; je propose de le garder quand même
(il libère la mémoire des modèles devenus inatteignables).

### Hors code — à signaler à l'utilisateur

- Le serveur qui tourne date du 22/07 16:20 : il faut le redémarrer.
- **Deux copies du dépôt** au même commit `ca253f8`, avec des remotes
  différents : `/home/alexandre/Apps-coding/Murmur` (remote `Murmur` →
  `collectifweb/aparte.git`) et `/home/alexandre/murmur` (remote `origin` →
  `collectifweb/murmur.git`). Le venv éditable pointe sur **la seconde**. Un
  correctif écrit dans la première ne s'applique pas au raccourci de
  l'utilisateur tant que les deux ne sont pas synchronisées.

---

## 4. Étapes d'implémentation

1. **A** — `cli.py` : sortie anticipée sur texte vide dans `toggle_dictation()`
   et `dictate_once()`.
2. **B** — `cli.py` : réordonner, envelopper l'insertion, notifier l'échec.
3. **C** — `session.py` : `-d` sur `arecord`, ramassage du `.wav` orphelin ;
   `config.py` : `max_recording_seconds` ; `desktop.py` : `EDITABLE_FIELDS`.
4. **D** — `config.py` : défaut `"fr"` ; + correction du fichier du poste.
5. **E** — `pyproject.toml` : `faster-whisper>=1.0.2`.
6. **F** — `desktop.py` : clé de cache complète.
7. **Tests** — `unittest`, via
   `PYTHONPATH=src python3 -m unittest discover -s tests -t tests` :
   - dictée vide → presse-papiers **intact**, aucune insertion tentée
   - échec d'insertion → notification émise, code de retour non nul, texte en
     historique
   - notification de succès émise **après** l'insertion
   - `-d` présent dans la commande `arecord` avec la valeur du réglage
   - session morte → `.wav` supprimé
   - clé de cache : deux langues différentes → deux transcripteurs
   - `APARTE_CONFIG` posé sur un fichier temporaire dans tout test passant par
     `current_settings()` (invariant du projet)
8. **Docs** — `CHANGELOG.md`, `CLAUDE.md` (invariants A, B, C), `README.md` pour
   `max_recording_seconds`.

---

## 5. Points sensibles

1. **Le plafond de 300 s est arbitraire.** Trop court pour une longue dictée,
   trop long pour éviter le disque plein. Et l'audio est perdu au plafond.
2. **Je ne connais pas la cause du `arecord` fou.** C dose le dégât sans traiter
   la cause. Si la cause est ailleurs — un `killpg` qui échoue silencieusement,
   `arecord` bloqué dans un `read()` ALSA insensible à SIGINT — le plafond
   masque un défaut plus profond.
3. **`DEFAULT_CONFIG["language"] = "fr"`** est une décision produit, pas
   technique. Elle ne casse rien pour les installs existantes, mais impose le
   français à toute nouvelle install, interface anglaise comprise.
4. **Re-lever après avoir notifié l'échec (B)** produit un `error:` sur `stderr`
   qui n'ira nulle part. Le code de retour non nul reste utile en ligne de
   commande. Est-ce que la notification suffit, ou faut-il journaliser sur
   disque ?
5. **Rien dans le plan n'empêche deux transcriptions de s'empiler** quand
   l'utilisateur réappuie pendant qu'une passe mouline. `inference_lock` les
   sérialise, jusqu'à 300 s d'attente. Faut-il un verrou côté raccourci, ou
   est-ce hors périmètre ?
6. **A et P1 supposent que `.strip()` suffit** à décider « rien à insérer ». Une
   transcription réduite à `...` ou `♪` passerait le test et écraserait quand
   même le presse-papiers.

---

## 6. Alternatives écartées

- **Filtrer le charabia** (script non attendu, ratio de caractères non latins,
  longueur disproportionnée par rapport à la durée). Écarté : spéculatif,
  fragile, et contraire à la règle du projet — « dans le doute, ne rien
  toucher ».
- **`try/except TypeError` autour de `hotwords`.** Écarté : masque une
  contrainte de version fausse au lieu de la corriger.
- **Watchdog surveillant `arecord`.** Écarté : `arecord -d` fait le travail avec
  un flag, sans processus ni fil supplémentaire.
- **Ne pas copier avant de coller** (pour régler P1 à la racine). Écarté : le
  passage systématique par le presse-papiers est un choix délibéré et documenté
  — c'est le filet quand le collage rate.
- **Supprimer la délégation au serveur** (`transcribe_via_running_app`).
  Écarté : elle vaut 0,26 s contre 1,53 s, mesuré, et n'est pas en cause.
- **Ne rien changer, puisque « ça remarche ».** Écarté : P1, P2, P4 et P5 sont
  toujours là et se redéclencheront.
