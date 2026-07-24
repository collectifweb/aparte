# Round 1 — Découpage d'exécution du Lot M3 (insertion macOS)

## Contexte

**Projet** : Aparté, dictée vocale Linux, locale et privée. Portage macOS mené
comme un **compagnon** — « Linux d'abord, français d'abord » tranche tout
arbitrage. La machine de dev est sous Linux : **le code macOS ne s'exécute pas
ici**, il est écrit dormant et couvert par des tests **mockés**, la vraie
validation se fera sur un vrai Mac (M8, smoke suite manuelle).

**Ce qui est déjà livré et poussé** sur `feat/portage-macos` :
- **M0** : couture `platform_dispatch.is_macos()/is_linux()`, extra `[macos]`
  (frameworks PyObjC marqués `sys_platform == 'darwin'`), classifieurs.
- **M1** : branches darwin triviales — `pbcopy` (`copy_text`), notifs natives,
  `afplay`, micros PortAudio (`sounddevice`), `record_wav` mac.
- **M2a** : diagnostics macOS + `macos_permissions.py` (1er module natif PyObjC :
  statut micro AVFoundation, `AXIsProcessTrusted` **passif**). Tout dégrade en
  « inconnu », jamais de crash. 265 tests verts.

**Ce plan ne rejoue PAS** le plan global `docs/plan-portage-macos.md`, qui a
atteint le consensus le 23/07. Il ne concerne **que la tranche M3** : l'insertion.

**Contraintes non négociables :**
- Comportement Linux **inchangé**, tests verts (`PYTHONPATH=src python3 -m
  unittest discover -s tests -t tests`).
- Le plus simple d'abord, modifications chirurgicales.
- macOS dormant + tests mockés seulement.
- Windows hors périmètre (zéro ligne).

## Ce que dit déjà le plan global sur M3

- **Cmd+V d'abord** (`pbcopy` + Cmd+V simulé via CGEvent), **frappe Unicode
  directe** (`CGEventKeyboardSetUnicodeString`) en repli/mode spécialisé.
- On **écarte** `osascript/System Events keystroke` (invite Automatisation en
  plus d'Accessibilité ; `keystroke` massacre ’ « » U+00A0 — rédhibitoire FR).
- Cmd+V s'aligne sur `paste_mode="clipboard"` **déjà existant** (copie puis colle).
  Le mode `terminal` Linux devient le mode « frappe Unicode » mac, secondaire.
- **Sécurité (règle du plan)** : « sur Darwin, **aucune route HTTP** ne réalise
  une action à effet système ou privilégiée ». `POST /api/paste` est listé
  **désactivée (404)** ; `/api/copy` et `/api/update/apply` aussi.
- Invariants repris à l'identique : sortie vide → ni copie ni collage ni
  historique ; historique **avant** insertion ; notif de succès **après** ;
  échec → texte récupérable, pas de succès prématuré.

## État du code (vérifié)

- Les invariants sont **déjà** dans du code partagé, OS-agnostique, dans `cli.py` :
  - `dictate_once()` (l.263) et `toggle_dictation()` (l.330) : `if not
    output.strip()` → `_notify_nothing_heard()` et `return` **avant** toute
    copie ; `history.record(...)` **avant** `_deliver(...)`.
  - `_deliver()` (l.294) : `try: paste_text(...) except Exception: notify(
    "⚠️ Dictée non insérée", f"{exc} …", urgency="critical"); raise` puis
    `_notify_inserted()`. Donc **si le mac branch de `paste_text` lève, la notif
    d'échec part déjà, le succès n'est jamais annoncé, et le texte reste dans
    l'historique + le presse-papiers.**
- `paste_text` est appelé par : `cli.py` (l.60, 303, 369) et `desktop.py` (l.301,
  la route `/api/paste`). Les appelants CLI (`aparte dictate`, `aparte toggle`)
  sont donc **vivants** sur Mac dès M3.
- `clipboard.copy_text` a **déjà** le branch mac `pbcopy` (M1). `paste_text` est
  **encore Linux-only** (wtype/xdotool).
- `pyproject.toml [macos]` porte **déjà** `pyobjc-framework-Quartz` (CGEvent, M3)
  → **aucun changement d'empaquetage nécessaire pour M3**.
- `macos_permissions.py` expose `accessibility_trusted()` (passif) et documente
  explicitement que le **prompt** (`AXIsProcessTrustedWithOptions` + ouverture des
  Réglages) est « an M3 concern ».

## Approche proposée (7 points)

### 1. `src/aparte/macos_insert.py` (module natif neuf)
Jumeau de `macos_permissions.py`. Importé **seulement** dans le mac branch de
`paste_text`. Deux fonctions :
- `insert_via_paste()` — Cmd+V synthétique via Quartz : `CGEventCreateKeyboardEvent`
  (keydown V avec `kCGEventFlagMaskCommand`, puis keyup), `CGEventPost` sur
  `kCGHIDEventTap`. Chemin **principal**.
- `type_unicode(text)` — `CGEventKeyboardSetUnicodeString` sur un event clavier,
  posté par blocs. **Repli** (mode `direct`), correct pour ’ « » U+00A0.
- Contrat : **jamais de no-op silencieux**. Framework absent, échec de post, ou
  event `None` → `raise` (remonte en `ClipboardError` côté appelant). Ne
  s'exécute pas ici → tests mockés (Quartz injecté via `sys.modules`).

### 2. `clipboard.paste_text` — mac branch
Sur `is_macos()` : `copy_text(text)` **d'abord** (le pbcopy de M1 ; texte préservé
même si le collage échoue), puis :
- `mode == "direct"` → `macos_insert.type_unicode(text)`
- sinon (`clipboard`, `terminal`) → `macos_insert.insert_via_paste()`
- Le mode `terminal` (Ctrl+Shift+V Linux) **n'a pas d'équivalent Mac** → Cmd+V
  aussi. Pas de branche spéciale.
- **Accessibilité manquante** → `ClipboardError` avec message d'aide (voir §4).
  Le contrat exact que `_deliver()` attend déjà.

### 3. `macos_permissions.py` — volet actif (reporté depuis M2a)
- `prompt_accessibility()` — `AXIsProcessTrustedWithOptions` avec l'option
  `kAXTrustedCheckOptionPrompt = True` : enregistre le process dans la liste
  Accessibilité et montre le dialogue système **une fois** (macOS dédoublonne).
- `open_accessibility_settings()` — `subprocess.run(["open",
  "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"])`.
- Dégradent en silence (retour `None`/`False`), jamais de crash. Tests mockés.

### 4. Glue du parcours guidé
Quand `paste_text` mac échoue faute d'Accessibilité : **avant** de lever, appeler
une fois `prompt_accessibility()` + `open_accessibility_settings()`, puis lever
`ClipboardError` avec un message d'aide clair. `_deliver()` l'affiche dans la
notif « ⚠️ Dictée non insérée » **déjà existante**. **CLI + natif, aucun écran web.**

### 5. Garde-fou HTTP — `desktop.py`
Sur Darwin, `POST /api/paste` → **404**. Sans ça, activer le mac branch ouvrirait
le « proxy de privilèges » que le plan interdit (une page web déclencherait une
action Accessibilité). **Linux inchangé.**

**⇐ C'EST LA QUESTION CENTRALE À TRANCHER (l'utilisateur ne peut pas juger
techniquement) :**
- **Option A (ma recommandation)** : M3 ne désactive que `/api/paste` — la seule
  route dans le périmètre exact de M3, et le seul vrai proxy de privilèges (le
  collage exige l'Accessibilité). `/api/copy` (pbcopy, **aucune** permission TCC)
  et `/api/update/apply` (git/pip, concern de M7) sont désactivés **avec leur
  lot**. Chirurgical, périmètre net.
- **Option B** : désactiver les **trois** routes système d'un coup en M3. Même
  garde-fou partout, plus cohérent d'un bloc, mais **déborde** de M3 vers des
  concerns d'autres lots, et `/api/copy`/`/api/update/apply` ne sont pas des
  proxys de privilèges au sens strict (pas de TCC).

### 6. Textes d'aide fr+en
Message d'Accessibilité (chaîne d'erreur CLI/notif, **pas** de chaîne web). Alignés
sur le ton existant des `ClipboardError`/notifs. Passage `/humanize` optionnel après.

### 7. Tests mockés
- `test_macos_insert.py` (neuf) : Quartz mocké — bons events postés pour Cmd+V et
  pour la frappe Unicode ; `raise` si framework absent / post échoue.
- `test_clipboard.py` : branche paste Mac — copie d'abord, bon helper appelé selon
  le mode, `ClipboardError` si Accessibilité manque.
- `test_macos_permissions.py` : `prompt_accessibility` + `open_accessibility_settings`
  mockés, dégradation gracieuse.
- Garde-fou : `POST /api/paste` → 404 sur Darwin, intact sur Linux.
- Preuve : suite verte + **sortie Linux identique** (vérifiée en lançant `dictate`
  et `doctor` sur l'hôte Linux).

## Points sensibles (que j'assume, à challenger)

1. **Les tests mockés ne prouvent pas le comportement natif réel** de CGEvent :
   ni que Cmd+V arrive intact dans Slack/Mail/Electron, ni que la frappe Unicode
   gère les composés. C'est structurel au portage (M8 = smoke manuelle). Le mock
   verrouille le **contrat** (appels faits, erreurs levées), pas l'effet OS.
2. **L'agressivité du parcours guidé** : ouvrir les Réglages + prompt à **chaque**
   échec d'insertion pourrait spammer si l'utilisateur refuse volontairement. Une
   fois accordé, ça ne se reproduit jamais. Faut-il un garde (ne prompter qu'une
   fois par process) ou est-ce acceptable en l'état ?
3. **`kCGHIDEventTap` vs `kCGSessionEventTap`** pour poster les events, et la
   nécessité (ou non) d'un court délai entre keydown/keyup pour que la cible
   enregistre le raccourci : je ne peux pas le mesurer ici. Je pars sur HID sans
   délai, à confirmer sur Mac.
4. **CGEvent sans Accessibilité ne lève pas** — il échoue **silencieusement**
   (l'event est ignoré par le système). D'où le **gate explicite**
   `accessibility_trusted()` **avant** de poster, sinon `paste_text` renverrait un
   succès mensonger. Point critique du design.
5. **Le mode `terminal` collapsé en Cmd+V** : un utilisateur qui a réglé
   `paste_mode="terminal"` sur Linux et migre sa config verrait un comportement
   différent. Acceptable (le concept terminal-paste n'existe pas sur Mac) mais à
   acter.

## Alternatives écartées

- **`osascript`/System Events** : écarté par le plan global (invite Automatisation
  en plus, casse la typo française). Non rediscuté.
- **Frappe Unicode en principal** (pas de Cmd+V) : plus lent, plus fragile sur
  texte long, et perd le presse-papiers comme filet. Cmd+V d'abord est le bon défaut.
- **Router l'insertion par une route HTTP même sur Mac** : viole la règle de
  sécurité du plan (proxy de privilèges). Écarté.
- **Faire M2b (bouton web « Ouvrir les Réglages ») dans M3** : ce serait de l'UI
  web → `/impeccable` + touche à la règle « pas de route à effet système ». Gardé
  **hors** M3, séparé et optionnel. **Conséquence assumée : M3 ne passe pas par
  `/impeccable`** (aucun écran visible), contrairement à ce que je pensais au départ.
- **Faire le toggle in-process robuste (`RecordingController`)** : c'est **M4**.
  M3 livre la **capacité** d'insertion, ses appelants CLI existent déjà.
- **Le raccourci global** : c'est **M5**.
