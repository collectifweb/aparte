# Plan : Lot M3 — Insertion macOS (Aparté)

> Tranche d'exécution du portage macOS. Le plan global fait autorité :
> [`docs/plan-portage-macos.md`](plan-portage-macos.md). Ce document ne couvre que
> **M3 (insertion)** et intègre le consensus de la revue croisée du 24/07
> (archive : `docs/archives/confront-codex-portage-macos-m3-2026-07-24-0940/`).

## Contexte

Aparté est une dictée vocale **Linux d'abord, français d'abord**, portée sur macOS
comme un **compagnon**. La machine de développement est sous Linux : **le code
macOS ne s'exécute pas ici**. Il est écrit dormant, couvert par des tests
**mockés**, et validé sur un vrai Mac plus tard (M8, smoke suite manuelle).

Déjà livré et poussé sur `feat/portage-macos` : **M0** (couture `platform_dispatch`,
extra `[macos]`), **M1** (`pbcopy`, notifs natives, `afplay`, micros PortAudio,
`record_wav` mac), **M2a** (diagnostics + `macos_permissions.py`).

M3 apporte la **capacité d'insérer** le texte dicté dans la fenêtre active sur
macOS. Son seul appelant vivant à ce stade est **`aparte dictate`** (une passe :
`record_wav` mac + transcription + insertion). `aparte toggle` reste **hors
périmètre** : il dépend de `session.py` (`arecord`, `/proc/<pid>/cmdline`), et sa
version macOS passe par le `RecordingController` résident (M4) et le raccourci
global (M5).

### Contraintes non négociables

- Comportement **Linux inchangé**, suite verte
  (`PYTHONPATH=src python3 -m unittest discover -s tests -t tests`).
- Le plus simple d'abord, modifications chirurgicales.
- macOS **dormant** + tests **mockés** seulement.
- Windows hors périmètre (zéro ligne).
- **Aucune UI visible en M3** → pas de `/impeccable`. L'affordance web « Ouvrir les
  Réglages » est M2b, séparée et optionnelle.

## Approche

### Insertion : Cmd+V d'abord, frappe Unicode en repli

Chemin **principal** : `pbcopy` (déjà là depuis M1) puis **Cmd+V synthétique** via
Quartz CGEvent. Pour une dictée française longue, le collage natif arrive intact
dans Slack, Mail, navigateurs, Electron — mieux qu'une rafale d'événements clavier.

**Repli / mode spécialisé** : frappe Unicode directe
(`CGEventKeyboardSetUnicodeString`), pour le mode `direct`. Correct pour les
caractères critiques du français (`’`, `« »`, espace insécable U+00A0), par blocs
bornés.

Écarté (décision du plan global) : `osascript`/System Events keystroke — il ajoute
une invite Automatisation et massacre les caractères hors disposition clavier.

Le mode `terminal` (Ctrl+Shift+V sous Linux) **n'a pas d'équivalent Mac** : il est
collapsé vers **Cmd+V**. Divergence de configuration assumée — un `config.json`
Linux partagé avec `paste_mode="terminal"` donne un collage standard sur Mac, pas
une frappe Unicode.

### Le gate Accessibilité (point critique)

CGEvent **ne lève pas** sans permission Accessibilité : le système ignore
silencieusement l'événement. Sans garde, Aparté annoncerait un **succès mensonger**.
Donc : vérifier `accessibility_trusted()` **avant** de poster, en tri-état :

- `True` → poster.
- `False` (permission connue et **refusée**) → **parcours guidé** (prompt + ouvrir
  les Réglages), puis lever `ClipboardError`.
- `None` (framework/API **injoignable**, p. ex. hors Mac ou `.[macos]` absent) →
  lever `ClipboardError` avec un message **d'environnement/packaging**, **sans**
  ouvrir les Réglages (ce serait du bruit).

Garantie réelle de `macos_insert` : **pas de succès mensonger** quand on peut savoir
d'avance que l'insertion échouera (Quartz absent, event `None`, Accessibilité
refusée ou injoignable). On **ne promet pas** de détecter un échec de `CGEventPost`
(retour non exploitable) — l'effet réel se valide en M8.

### Continuité comportementale (invariants repris à l'identique)

Ces invariants sont **déjà** dans le code partagé et OS-agnostique de `cli.py`
(`dictate_once`, `_deliver`). Le mac branch de `paste_text` n'a qu'à honorer sa
part du contrat :

- sortie vide → **ni copie, ni collage, ni historique** ;
- historique écrit **avant** insertion ;
- notification de succès **après** insertion ;
- échec → texte récupérable (presse-papiers + historique), pas de succès prématuré.

Comme `_deliver()` affiche `str(exc)` dans la notification « ⚠️ Dictée non insérée »,
**toute panne native est enveloppée en `ClipboardError`** avec un message lisible
(aucune `ImportError`/`AttributeError`/exception PyObjC brute ne remonte), sans
double emballage si un `ClipboardError` est déjà levé.

`handle_output()` (`aparte transcribe --paste`, `record --paste`) est un chemin plus
mince — pas d'historique ni de notif d'échec. C'est le comportement **pré-existant
et cohérent avec Linux** ; M3 ne le change pas, on le **documente** seulement.

### Sécurité : aucune route HTTP à effet système sur Darwin

Le critère du plan global n'est pas « permission TCC » mais **« effet système
déclenché par HTTP »**. Sur Darwin, on désactive donc **les trois** routes système
(`plan-portage-macos.md:196-198`) dès M3 :

| Route | Darwin |
|---|---|
| `POST /api/paste` (insertion, Accessibilité) | **404** |
| `POST /api/copy` (`pbcopy`) | **404** |
| `POST /api/update/apply` (`git`/`pip` + redémarrage) | **404** |

Désactiver n'est pas implémenter M7 : c'est un **garde de route** minimal dans
`desktop.py`. Il est explicite (pas une confiance dans l'Origin-check), placé
**après** l'Origin-check (origine étrangère → 403) et **avant** les handlers (route
interdite sur Darwin avec requête autrement acceptable → 404). Ordre déterministe.

Coût UI (reliquats documentés, **pas** corrigés en M3) :
- **Bouton Copier** : `copyRecent()` retombe sur `navigator.clipboard.writeText`
  après l'échec de `/api/copy` → **attendu OK via repli navigateur, à confirmer en
  M8** (le comportement réel dépend du navigateur et de l'activation utilisateur).
- **Bouton « Mettre à jour »** : appelle `/api/update/apply` sans repli → échouerait
  sur Mac (404). Il n'apparaît que si une MAJ est disponible ; la MAJ Mac passe par
  le tray (M6/M7). Reliquat UI à traiter avec son lot, pas en M3.

## Étapes d'implémentation

1. **`src/aparte/macos_insert.py` (module natif neuf)** — jumeau de
   `macos_permissions.py`, importé uniquement depuis le mac branch de `paste_text`.
   - `insert_via_paste()` — Cmd+V via `CGEventCreateKeyboardEvent` +
     `kCGEventFlagMaskCommand`, `CGEventPost` sur `kCGHIDEventTap` (choix sous
     réserve M8, cf. Vigilance).
   - `type_unicode(text)` — `CGEventKeyboardSetUnicodeString`, par blocs bornés.
   - Contrat : lève si Quartz absent / event `None` ; jamais de succès mensonger ;
     toute panne native → `ClipboardError` propre.

2. **`src/aparte/clipboard.py` — mac branch de `paste_text`** — `copy_text(text)`
   d'abord ; `mode == "direct"` → `type_unicode` ; sinon (`clipboard`, `terminal`)
   → `insert_via_paste`. **Gate `accessibility_trusted()` tri-état** avant de poster
   (voir Approche). Linux inchangé.

3. **`src/aparte/macos_permissions.py` — volet actif (reporté depuis M2a)** —
   `prompt_accessibility()` (`AXIsProcessTrustedWithOptions` + option prompt) et
   `open_accessibility_settings()`
   (`open x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility`).
   Dégradent en silence. Déclenchés **uniquement** dans le cas `False`, **une fois
   par processus** (booléen anti-spam, sans persistance).

4. **`src/aparte/desktop.py` — garde de route Darwin (Option B)** — `POST /api/paste`,
   `POST /api/copy`, `POST /api/update/apply` → **404** sur Darwin. Garde explicite
   dans `do_POST`, après l'Origin-check. Linux inchangé.

5. **Textes d'aide fr+en** — messages d'Accessibilité (`False` : guider vers les
   Réglages ; `None` : environnement/packaging), chaînes d'erreur CLI/notif. **Pas
   de chaîne web.** Passage `/humanize` optionnel après.

6. **Tests mockés**
   - `test_macos_insert.py` (neuf) : Quartz mocké — bons events pour Cmd+V et pour
     la frappe Unicode ; `ClipboardError` si framework absent / Accessibilité
     refusée ; **mode `direct` : chaîne française longue avec `’ « » U+00A0`
     conservée et découpée de façon contrôlée**.
   - `test_clipboard.py` : branche mac, tri-état Accessibilité, copie d'abord, bon
     helper selon le mode.
   - `test_macos_permissions.py` : `prompt_accessibility`/`open_accessibility_
     settings` mockés, anti-spam, `False` vs `None`.
   - `test_desktop.py` : **les 3 routes** → 404 sur Darwin avec une requête
     **acceptée par l'Origin-check** (détection de plateforme patchée) — on prouve
     le garde de route, pas le garde Origin. Côté **Linux**, l'assertion est
     **« le garde Darwin ne s'applique pas et le handler est atteint »** (backends
     mockés si on affirme un 200), pas un statut dépendant de l'environnement.
   - Preuve : suite verte + **sortie Linux identique** (`aparte dictate`,
     `aparte doctor` lancés sur l'hôte Linux).

7. **Documentation** — `tasks/todo.md` § M3 : `aparte toggle` non fonctionnel sur
   Mac (= M4/M5) ; reliquats UI (bouton MAJ, bouton Copier) ; `handle_output` chemin
   mince pré-existant ; points M8. `CHANGELOG.md` [Unreleased]/Added.

## Points de vigilance

1. **Les tests mockés ne prouvent pas l'effet OS** de CGEvent (collage réel dans
   Slack/Mail/Electron, frappe Unicode des composés). Structurel au portage → M8.
   Le mock verrouille le **contrat observable**, pas l'effet système.
2. **`kCGHIDEventTap` vs `kCGSessionEventTap`** et la nécessité d'un micro-délai
   keydown/keyup : non tranchable sans Mac. Ne bloque pas M3 ; à prouver en M8.
3. **Le gate Accessibilité est critique** : sans lui, succès mensonger. À ne pas
   retirer.
4. **Reliquats UI** (boutons Copier / Mettre à jour sur Mac) : documentés, à traiter
   avec leur lot, jamais en corrigeant de l'UI dans M3.
5. **404** conservé (cohérent avec le consensus du plan global ; ne pas rouvrir).

## Décisions explicitement écartées

- **Option A (désactiver seulement `/api/paste`)** : trop étroite. Le critère est
  « effet système par HTTP », pas « TCC » ; `/api/update/apply` est déjà interdite
  et plus lourde que le collage. Retenu : **Option B, les 3 routes**.
- **`osascript`/System Events** : invite Automatisation en plus, casse la typo
  française. Écarté par le plan global.
- **Frappe Unicode en principal** : plus lente, plus fragile sur texte long, perd le
  presse-papiers comme filet. Cmd+V d'abord.
- **Router l'insertion par HTTP même sur Mac** : viole « aucune route à effet
  système sur Darwin ».
- **M2b, M4, M5 dans M3** : hors périmètre. M3 livre la capacité d'insertion ; ses
  appelants CLI (`dictate`) existent déjà.
