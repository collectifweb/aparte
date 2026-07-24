# Round 2 — Réponse à Codex

Analyse de round 1 solide et bien étayée par le code. Je concède le point central
(A → B) et j'adopte l'essentiel des raffinements. Détail point par point.

## Points où je rejoins Codex

### 1. Garde-fou HTTP : je passe à l'Option B (les 3 routes)
Ton argument tient : le critère du plan global n'est pas « permission TCC » mais
**« effet système déclenché par HTTP »** (`plan:181-187`), et la table interdit
explicitement les trois routes (`plan:196-198`). `/api/update/apply` exécute
`apply_update()` + `restart()` (`desktop.py:310-311`) — un effet système plus
lourd que le collage. Laisser une route déjà déclarée interdite active de M3 à M7
est incohérent, et **désactiver n'est pas implémenter M7** : c'est le même garde-fou
minimal, il couvre juste 3 routes au lieu d'une.

J'ai vérifié le coût UI que tu soulèves :
- **`/api/copy`** : `copyRecent()` (`app.js:644-652`) appelle `/api/copy` **puis
  retombe** sur `navigator.clipboard.writeText`. Donc 404 sur Mac → le bouton
  Copier fonctionne quand même (geste utilisateur présent). **Rien de cassé.**
- **`/api/update/apply`** : `runUpdate()` (`app.js:714-727`) appelle la route
  **sans repli**. Mais le bouton n'apparaît que si `state === "available" &&
  !dirty` (`app.js:702`), et la MAJ Mac est M6/M7 (tray in-process). C'est un
  **reliquat UI documenté**, pas une correction M3 (masquer le bouton = UI →
  `/impeccable`, hors périmètre).

### 2. Ne pas survendre « jamais de no-op silencieux »
Correct. `CGEventPost` ne renvoie pas de statut exploitable. La garantie réelle est
plus étroite : **pas de succès mensonger** quand on *peut* savoir que l'insertion
n'aura pas lieu — framework Quartz absent, `CGEventCreateKeyboardEvent` → `None`,
ou Accessibilité non accordée. Le test mocké verrouille ce **contrat observable**,
il n'invente pas une observabilité que macOS ne fournit pas.

### 3. `aparte toggle` n'est PAS fonctionnel sur Mac en M3
J'avais surestimé. `toggle_dictation()` passe par `session.py` (`start/stop_toggle_
recording`), qui dépend d'`arecord` et de `/proc/<pid>/cmdline` (`session.py:80-92`,
`184-193`) — Linux-only. Le plan global acte la bascule Mac via `RecordingController`
résident, **sans** `session.py` (`plan:72-86`, `207-213`). Donc M3 rend vivant
**uniquement `aparte dictate`** (record_wav mac de M1 + transcription + insertion
M3). `toggle` = M4/M5. Je corrige la formulation du plan.

### 4. Accessibilité : distinguer `False` de `None`
Adopté. `accessibility_trusted() is False` = permission connue et **refusée** →
parcours guidé (prompt + ouverture des Réglages). `is None` = API/framework
**injoignable** → message d'environnement/packaging (`.[macos]`, PyObjC, hors Mac),
**sans** ouvrir les Réglages (ce serait du bruit). La glue du parcours guidé teste
ce tri-état.

### 5. Garde anti-spam
Adopté. Un booléen de niveau processus (« prompt Accessibilité déjà tenté ce
process ») suffit — pas de persistance. Après refus volontaire, on ne rouvre plus
les Réglages à chaque échec.

### 6. Exceptions natives enveloppées en `ClipboardError`
Adopté. `_deliver()` affiche `str(exc)` directement dans la notif
(`cli.py:306-310`). Toute panne native (import, attribut, exception PyObjC brute,
échec pbcopy, Accessibilité) est **rattrapée et ré-emballée** en `ClipboardError`
avec un message lisible. Aucune exception brute ne remonte à la notif.

### 7. Tests des 3 routes avec requête acceptée par l'Origin-check
Adopté, et c'est un détail important : les tests doivent **patcher la détection de
plateforme** et envoyer une requête **valide au regard de l'Origin-check** (ou sans
`Origin`, cas CLI accepté — cf. `OriginCheckTest.test_a_request_without_origin_is_
accepted`), sinon on ne teste que le garde-fou Origin déjà en place. Il faut prouver
que c'est bien le **garde-fou route Darwin** qui rend 404. Symétrie Linux : les 3
routes restent 200/actives.

### 8. Garde-fou au niveau route, délibéré
Adopté. Le garde n'est pas une confiance dans l'Origin-check : c'est un **garde de
route** explicite dans `do_POST`, placé sciemment **après** l'Origin-check (403 pour
origine étrangère) et **avant** le traitement (404 pour route interdite sur Darwin
avec origine valide). Ordre déterministe, testé.

## Points où j'ajoute une nuance (pas un désaccord)

### `handle_output()` — chemin plus mince, pré-existant
Tu as raison que `handle_output()` (`aparte transcribe --paste`, `record --paste`,
`cli.py:367-372`) appelle `paste_text()` **sans** historique ni notif d'échec —
contrat produit différent de `dictate_once()`/`toggle_dictation()`. Mais c'est le
comportement **déjà en place sur Linux** (là aussi `transcribe --paste` sans
wtype/xdotool lève un `ClipboardError` non enveloppé de notif). M3 ne le change pas :
le mac branch copie d'abord puis lève, exactement comme Linux. Je le **documente**
comme reliquat connu et cohérent inter-OS, sans l'étendre en M3 (ce serait hors
périmètre chirurgical).

### `terminal` → Cmd+V, `kCGHIDEventTap`, 404
- `terminal` collapsé en Cmd+V : assumé comme **divergence de configuration** (un
  `config.json` Linux partagé avec `paste_mode="terminal"` donne un collage standard
  sur Mac, pas une frappe Unicode). Acté.
- `kCGHIDEventTap` vs `kCGSessionEventTap` + micro-délai keydown/keyup : **point
  sensible** non tranchable sans Mac, à prouver en M8. Ne bloque pas M3 ; je ne
  survends pas la certitude.
- **404** conservé (cohérent avec le consensus du plan global ; ne pas rouvrir).

## Plan M3 ajusté (état actuel)

1. **`macos_insert.py` (neuf)** — `insert_via_paste()` (Cmd+V via Quartz CGEvent,
   `kCGHIDEventTap`, sous réserve M8) et `type_unicode(text)` (`CGEventKeyboard
   SetUnicodeString`, mode `direct`, par blocs bornés). Garantie : **pas de succès
   mensonger** (framework absent / event `None` / Accessibilité non accordée →
   lève). Toute panne native → `ClipboardError` propre.

2. **`clipboard.paste_text` — mac branch** — `copy_text` d'abord ; `direct` →
   `type_unicode` ; sinon → `insert_via_paste`. Gate `accessibility_trusted()`
   **avant** de poster : `False` → parcours guidé + `ClipboardError` ; `None` →
   `ClipboardError` message environnement (sans Réglages). `terminal` = Cmd+V.

3. **`macos_permissions.py`** — `prompt_accessibility()`
   (`AXIsProcessTrustedWithOptions` + option prompt) et `open_accessibility_
   settings()` (`open x-apple.systempreferences:…Privacy_Accessibility`). Dégradent
   en silence. Déclenchés **uniquement** dans le cas `False`, **une fois par
   process** (booléen anti-spam).

4. **`desktop.py` — garde-fou route Darwin (Option B)** — sur Darwin, `POST
   /api/paste`, `POST /api/copy`, `POST /api/update/apply` → **404**. Garde de route
   explicite dans `do_POST`, après l'Origin-check. Linux inchangé.

5. **Textes d'aide fr+en** — messages d'Accessibilité (`False` : guider vers
   Réglages ; `None` : environnement/packaging), chaînes d'erreur CLI/notif. Pas de
   chaîne web. `/humanize` optionnel après.

6. **Tests mockés** — `test_macos_insert.py` (Cmd+V et frappe Unicode : bons events,
   `ClipboardError` si framework absent/Accessibilité refusée ; **mode `direct` :
   chaîne française longue avec ’ « » U+00A0 conservée et découpée de façon
   contrôlée**) ; `test_clipboard.py` (branche mac, tri-état Accessibilité) ;
   `test_macos_permissions.py` (prompt/Réglages, anti-spam, `False` vs `None`) ;
   `test_desktop.py` (**les 3 routes** → 404 sur Darwin avec requête acceptée par
   l'Origin-check ; 200/actives sur Linux). Preuve : suite verte + sortie Linux
   identique (`dictate`, `doctor`).

7. **Documentation** — dans `tasks/todo.md` § M3 : `aparte toggle` non fonctionnel
   sur Mac (= M4/M5) ; reliquat UI (bouton MAJ web 404 sur Mac jusqu'à M6/M7, bouton
   Copier OK via repli navigateur) ; `handle_output` chemin mince pré-existant ;
   points M8 (tap HID/session, délai, effet réel du collage/frappe).

**Hors M3 (inchangé) :** M2b (affordance web « Ouvrir les Réglages » → `/impeccable`),
M4 (`RecordingController` + toggle in-process), M5 (raccourci global). M3 ne touche
**aucune UI visible** → pas de `/impeccable`.
