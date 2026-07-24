# Round 2 - Codex : contre-reponse

## Points resolus depuis le round precedent

### 1. Callback tardif / stream mal ferme

J'accepte le fix propose : un callback en fermeture, propre a chaque capture, est
le bon remede. Il corrige mieux le defaut que mon diagnostic minimal, parce qu'il
supprime le chemin par lequel un vieux stream peut ecrire dans le buffer courant.

La condition importante est que la fermeture capture une capsule mutable par
capture, pas seulement une liste. Cette capsule doit porter au minimum `frames`,
`frame_count`, `max_frames`, `active`, et idealement les statuts
`truncated`/`overflowed`. Un callback stale ne doit plus ecrire dans
`self._frames`, `self._frame_count`, `self._truncated` ou `self._overflowed` apres
l'arret de sa capture. Avec cette precision, garder `_close_stream` en
best-effort redevient acceptable : une fermeture ratee peut laisser le device
ouvert, mais ne peut plus contaminer la capture suivante.

Les tests proposes sont les bons : nourrir l'ancien callback apres stop, puis
forcer un `close()` qui echoue et verifier que la capture suivante reste propre.

### 2. Bip de demarrage avant capture

Accord. Le bip `start` avant `stream.start()` aligne macOS sur le contrat explicite
de `audio.py` et sur le comportement Linux. Il n'est pas indispensable que le bip
precede la construction de `RawInputStream`; le point de correction est qu'il
precede le demarrage effectif de la capture.

Pour le bip `stop`, le deplacer apres fermeture est coherent. Le retour audio peut
etre legerement plus tardif si `stop()`/`close()` tarde, mais comme cette fermeture
part dans le worker, ce n'est pas un blocage de la run loop et cela evite toute
ambiguite de capture.

### 3. Polissage manquant

Accord sur le defaut fonctionnel : sans polissage, le futur raccourci macOS
livrerait un texte brut alors que le chemin principal Linux livre le texte poli.
C'est bien une correction avant M5.

Je change d'avis sur l'emplacement : le worker est le meilleur endroit, pas
`_transcribe_capture()`. L'argument de Claude est convaincant. `_transcribe_capture`
est la primitive serveur-locale de transcription brute, equivalente conceptuelle
de `/api/transcribe`, et elle doit rester reutilisable sans effet de polissage
cache. Le pipeline produit est bien :

1. transcription brute sous `inference_lock`;
2. polissage selon les reglages du raccourci resident;
3. `deliver_transcript`.

Le helper partage avec la CLI est la bonne forme, sous reserve qu'il exprime
clairement ce pipeline commun au lieu de dupliquer une construction fragile
d'`argparse.Namespace`. Le plus important est que le worker utilise une meme
snapshot de `Settings` pour polir puis livrer, afin d'eviter un texte poli avec un
jeu de reglages et insere/historise avec un autre.

### 4. Stop robuste, jamais `PROCESSING` colle

Accord. Le trou d'erreur dans `_stop_locked` est reel et le fix propose le ferme :
si `settings_provider()` ou `Thread.start()` leve pendant l'arret, le stream doit
etre ferme, les references nettoyees, et l'etat doit passer a `ERROR`, pas rester
en `PROCESSING`.

La precision a garder dans l'implementation : lire le bip avant la transition
`PROCESSING` ne suffit pas si l'exception n'est pas attrapee. Le test annonce par
Claude doit etre le contrat : exception de `settings_provider` ou de
`Thread.start` pendant stop => stream ferme + `ERROR` observable.

### 5. Fuite de stream dans l'`except` de `_begin_locked`

Accord. C'est chirurgical et sans contrepartie : avant de mettre `_stream = None`,
le chemin d'erreur doit fermer le stream deja cree/assigne. Cela couvre notamment
le cas ou `_arm_cap_timer()` leve apres `stream.start()`.

### 6. Redondance plafond en frames / timer

Point resolu : on garde les deux. Le timer est la semantique produit
d'auto-stop; le plafond en frames est la borne memoire si le timer tarde ou si le
callback pousse un bloc de plus. La seule correction attendue est documentaire :
ce plafond est "max + un bloc de callback", pas une limite stricte a la frame pres.

## Points encore en debat

Aucun desaccord substantiel ne subsiste de mon cote.

Sur le polissage, je valide la position de Claude : le worker est le bon endroit.
Je ne tiens plus a `_transcribe_capture()`, tant que le helper partage garde une
separation lisible entre transcription brute, polissage et livraison.

Sur les points reportes :

- `toggle()` qui tient le lock pendant de l'I/O : report accepte. Ce n'est pas une
  correction M4, mais une contrainte ferme de M5. Le callback Carbon/AppKit doit
  dispatcher hors run loop avant d'appeler `toggle()`.
- `shutdown()` non cable : report accepte, avec une borne. Des que M5 rend la
  capture declenchable dans l'application residente, `run_desktop()` doit appeler
  le `shutdown()` du controleur au shutdown applicatif. Le choix plus fin
  "abandon immediat" vs `join()` borne peut rester M5/M6.
- Ancrage `DesktopHandler._recording_controller` : report accepte. Il ne bloque
  pas M5, mais M5 doit garder une reference explicite dans `run_desktop()` et la
  passer au hotkey/tray; le handler HTTP doit seulement observer.
- `_truncated`/`_overflowed` et surface d'etat riche : report accepte vers M6/M8.
  Cela devient utile quand le tray/doctor doit diagnostiquer une capture reelle,
  pas pour brancher le raccourci.
- Debounce : report accepte. Le comportement exact doit etre decide apres
  observation de `RegisterEventHotKey`; avant cela, le seuil actuel reste
  defensible car il est sous le seuil minimal transcrivable.
- Worker daemon et fermeture pendant `PROCESSING` : report accepte vers le cycle
  de vie M6, tant que M5 documente clairement la semantique retenue au shutdown.

## Evaluation globale

Le plan est pret : le decoupage M4 tient, les corrections a faire avant M5 sont
locales, et les reports sont dates au bon lot. Je ne vois plus de defaut qui
oblige a revoir l'architecture du `RecordingController`.

Le punch-list M4 a valider avant M5 est donc :

1. callback par capture, isole des callbacks tardifs;
2. bip `start` avant capture active, bip `stop` apres fermeture;
3. polissage dans le worker via helper partage avec la CLI;
4. stop robuste sans `PROCESSING` orphelin;
5. fermeture du stream dans le chemin d'erreur de start.

Avec les tests annonces sur ces cinq points, le plan M4 -> M5 est valide en
l'etat.

CONSENSUS_ATTEINT
