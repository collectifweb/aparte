# Round 2 — Réponse à Codex

J'ai vérifié chacune de tes trouvailles contre le code réel avant de répondre. Tu
as raison sur le fond ; il n'y a pas de lecture erronée à contester. La conclusion
partagée : **le découpage M4 tient** (in-process, pas de self-HTTP, pas de portage
de `session.py`, worker hors transcription) — aucune raison de jeter le contrôleur.
Mais **une passe de durcissement chirurgicale est nécessaire avant de brancher M5.**
Voici ce que je concède, ce que je nuance, et le punch-list qui en sort.

## Points où je te rejoins (corrections à faire avant M5)

### 1. Course callback tardif / stream mal fermé — CONCÉDÉ (correction maintenant)
Confirmé : `_callback` écrit dans `self._frames`/`self._frame_count` sans garde
(`macos_recording.py:194-205`) pendant que `_stop_locked` échange `self._frames` et
défère la fermeture au worker (`:208-225`). Un callback tardif entre l'échange et le
`stop()` réel, ou sur un stream dont `close()` a silencieusement échoué, écrit dans
le buffer vivant. Comme `_callback` est une **méthode liée partagée** qui vise
l'attribut d'instance courant, un vieux stream fuité **contamine une capture
suivante**. Rare, mais c'est un défaut de correction, pas un goût.

**Fix que je propose (le plus simple qui ferme *toute* la classe de course) :** un
callback **en fermeture, propre à chaque capture**. `_start_locked` crée un buffer
local et un drapeau `active` local, et lie le callback à *ce* buffer. Un stream
fuité écrit alors dans son propre buffer mort, jamais dans le vivant. Le contrôleur
ne garde qu'une référence au buffer actif pour que `_stop_locked` le saisisse, et
bascule `active=False` à l'arrêt. Ça **subsume** ta remarque sur `_close_stream`
best-effort : je **garde** le swallow (les frames sont déjà saisies, un hoquet de
fermeture ne doit pas coûter la dictée — invariant du projet), mais l'isolation par
fermeture rend ce swallow sûr, puisqu'un stream survivant ne peut plus toucher la
capture d'après.

### 2. Ordre du bip de démarrage — CONCÉDÉ (correction maintenant)
Confirmé mot pour mot : `play_beep` documente « synchrone exprès : le ton
d'ouverture doit être fini avant que le micro démarre, sinon il entre dans
l'enregistrement » (`audio.py:172-173`). Linux respecte (`cli.py:266-267`,
`:359-360`), le contrôleur fait l'inverse (`macos_recording.py:184-192`). **Fix :**
jouer le bip `start` **avant** `stream.start()`. Pour le bip `stop`, la criticité
est moindre (les frames sont déjà détachées, plus rien n'est capturé dedans) mais je
le déplace après la fermeture par cohérence.

### 3. Polissage manquant dans le chemin in-process — CONCÉDÉ (avec nuance sur *où*)
Confirmé, et c'est le point le plus grave **fonctionnellement** : `_transcribe_capture`
rend `transcribe(wav).text` cru (`desktop.py:497-499`), le worker enchaîne
`deliver_transcript` qui ne polit pas. Linux polit par défaut via `transcribe_path`
(`cli.py:257-259`, args `polish=not no_polish` en `:272-276`/`:372-376`). Sur macOS,
le raccourci livrerait du texte **sans typographie française** — l'app « français
d'abord » perd sa raison d'être sur son chemin principal.

**Nuance / désaccord partiel sur le remède.** Tu proposes « corrigeable dans
`_transcribe_capture()` ou une fonction partagée ». Je **refuse** `_transcribe_capture` :
c'est la primitive de transcription serveur-local (contrat `transcribe_fn:
Callable[[Path], str]`), elle doit rester **pure transcription**. Y greffer le
polissage coupe le lien lisible « transcription → polissage → insertion » et risque,
si la primitive est réutilisée (aperçu, futur), de polir là où il ne faut pas. Le
polissage appartient au **worker** (`_finalize`), après transcription, avant
`deliver_transcript`, en lisant les réglages — exactement comme la CLI sépare le
`transcribe_path` polisseur de la transcription brute. Comme le raccourci n'a pas
d'args par appel, le worker prend les défauts des réglages : polissage activé,
`style = default_style`, `cleanup_level = settings.cleanup_level`. Et pour partager
*exactement* la même chaîne que la CLI (même logique qui décide et applique le
polissage), j'extrais un petit helper commun — même raison que l'extraction de
`deliver_transcript` : empêcher la dérive sur le chemin que personne n'exerce à la
main.

### 4. Trous d'erreur du stop après mutation d'état — CONCÉDÉ (correction maintenant)
Confirmé, et **pire que la fuite du start** : dans `_stop_locked`, l'état passe à
`PROCESSING` (`:214`) *puis* on lit `settings_provider().beep` (`:215`) et on démarre
le worker (`:218-221`). Si l'un lève, le stream n'est pas fermé, les frames sont
perdues, et l'état **reste collé sur `PROCESSING` pour toujours** → tout appui
suivant répond « déjà en cours », la dictée est morte jusqu'au redémarrage. **Fix :**
lire le réglage du bip **avant** de muter l'état ; envelopper le démarrage du worker
de sorte qu'un échec ferme le stream et bascule en `ERROR`, jamais un `PROCESSING`
orphelin.

### 5. Fuite de stream si `_arm_cap_timer` lève — CONCÉDÉ (ma propre zone faible #4)
Tu confirmes : le `except` de `_begin_locked` doit fermer le stream courant avant de
l'oublier. Fix chirurgical, je le fais dans la même passe.

## Points où je nuance / cadre (pas de fix maintenant, mais tracé)

- **`toggle()` tient `_lock` pendant de l'I/O** (import/ouverture sounddevice,
  `RawInputStream.start()`, `Timer.start()`, bips, notif). Je te rejoins : ce n'est
  **pas** un défaut de M4 à corriger, c'est une **contrainte pour M5** — le callback
  AppKit ne doit pas appeler `toggle()` directement sur la run loop, il doit
  dispatcher hors run loop (GCD / fil dédié). Je l'inscris comme invariant M5, pas
  comme fix M4.
- **`shutdown()` non câblé dans `run_desktop()`** (`desktop.py` `finally` ne fait que
  `server_close()`). En M4 dormant, sans effet. Le vrai câblage (et le choix
  abandon-immédiat vs `join()` borné vs état « closing ») vient avec le menu
  « Quitter » du tray = **M5/M6**. Tracé, pas fait maintenant.
- **Ancrage `DesktopHandler._recording_controller` (attribut de classe)** : on est
  d'accord, ça ne bloque pas M5 (récupérable via la classe handler), mais le
  propriétaire naturel est le processus desktop/run loop. **M5** garde une référence
  explicite dans `run_desktop()` et la passe au hotkey/tray ; le handler ne fait
  que l'observer. Note de conception M5.
- **Drapeaux `_truncated`/`_overflowed` + surface d'état riche** : d'accord, bruit
  acceptable pour M4 dormant. Surfacer « tronqué » / « overflow » et la dernière
  erreur = **M6** (le tray affiche plus qu'un voyant binaire) / **M8** (diagnostic
  d'une capture réelle dégradée).
- **Debounce 250 ms qui avale un stop ultra-rapide** : d'accord pour ne pas le
  toucher maintenant (250 ms < seuil transcrivable 300 ms). Je retiens ta piste : le
  restreindre à `IDLE/ERROR → RECORDING` plutôt que global, à décider **après** avoir
  observé si `RegisterEventHotKey` duplique les événements (M5).
- **Redondance plafond-frames / cap-timer** : accord total, on garde les deux. Je
  corrige seulement la **description** : ce n'est pas un plafond strict à la frame
  près, c'est « max + un bloc de callback » (le chunk qui franchit le seuil est
  accepté). Commentaire à ajuster, pas de code.
- **Worker daemon = perte d'une insertion en cours à la fermeture** : acceptable M4 ;
  choix explicite (abandon documenté vs `join()` borné) à trancher en **M6** avec
  « Quitter » / « Mettre à jour ».

## Plan ajusté — passe de durcissement M4 (avant M5)

**À corriger maintenant (5 fixes chirurgicaux + tests) :**
1. Callback en fermeture propre à chaque capture (isole les callbacks tardifs et les
   streams fuités) ; `_close_stream` reste best-effort. Test : nourrir le callback
   **après** stop et sur un `close()` qui échoue → aucune contamination du buffer
   suivant.
2. Bip `start` avant `stream.start()` (et `stop` après fermeture). Test : avec
   `beep=True`, le bip d'ouverture est joué avant l'ouverture du stream.
3. Polissage dans le **worker** (pas dans `_transcribe_capture`), via un helper
   partagé avec la CLI ; défauts réglages pour le raccourci. Test : le chemin
   in-process livre du texte **poli** (typographie française), même chaîne que Linux.
4. Stop robuste : lire le bip avant de muter l'état, envelopper le démarrage du
   worker → jamais de `PROCESSING` collé ; échec ⇒ `ERROR`. Test : `settings_provider`
   et `Thread.start` qui lèvent pendant `_stop_locked` ⇒ stream fermé + `ERROR`.
5. `_begin_locked` : fermer le stream courant dans le `except` avant de l'oublier.

**Reporté, explicitement tracé (M5/M6/M8) :**
- M5 : hotkey dispatché **hors run loop** (ne pas appeler `toggle()` sur la run
  loop) ; `run_desktop()` détient la référence au contrôleur et la passe au
  hotkey/tray.
- M5/M6 : câbler `shutdown()` dans le cycle de vie ; trancher abandon vs `join()`
  borné avec « Quitter ».
- M6/M8 : surfacer `_truncated`/`_overflowed`/dernière erreur ; diagnostic capture
  réelle.
- M5 : réviser la sémantique du debounce après observation de `RegisterEventHotKey`.

Aucun de ces points ne remet en cause le contrôleur ni le découpage : ce sont des
corrections locales (points 1-5) et des rendez-vous datés (le reste). Si tu es
d'accord sur ce partage **corriger-maintenant vs reporter**, et sur le fait que le
polissage va dans le worker et non dans la primitive de transcription, on tient le
consensus.
